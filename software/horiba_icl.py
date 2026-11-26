"""Cliente ICL (EzSpec-SDK) del HORIBA iHR320, compatible con Python 3.7.

Portado de ``Software_calibracióniHR320/spectral_calibration/horiba.py``, que
fue validado con el equipo del laboratorio (ICL API 300, icl.exe 2.1.0.19,
iHR320 serie 2756D-1626-IHR320). Usa directamente el protocolo WebSocket JSON
documentado por HORIBA (``EzSpec-python-sdk/docs/icl_api20251029.md``) con el
paquete ``websocket-client``, porque el SDK Python oficial exige Python >= 3.9
y el entorno ``pump_probe_gui`` es Python 3.7.

Principios heredados del software de calibración:

- El estado físico es la lectura de ICL, nunca el valor pedido en la interfaz.
- Cada movimiento se confirma por relectura (``mono_isBusy=false``,
  ``initialized`` y posición dentro de tolerancia), no por el acuse.
- Sin reenvíos ni reversiones automáticas tras error, timeout o cancelación.
  Cancelar abandona la espera: no frena un motor que ya recibió la orden.
- Sin homing implícito: ``mono_init(force=false)`` sólo desde ``initialize``
  y sólo si ICL informa que falta. Nunca se usa ``mono_setPosition``.

Este módulo no importa Qt, VISA ni Kinesis.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import math
import threading
import time


logger = logging.getLogger(__name__)

DEFAULT_ICL_URL = "ws://127.0.0.1:25010"
WEBSOCKET_REQUIREMENT = "websocket-client==1.6.1"

# ICL API 300, mono_getConfig. Límites/paso: documentación HORIBA iHR.
SLIT_LOCATIONS = {1: "Entrada axial", 2: "Entrada lateral", 3: "Salida axial", 4: "Salida lateral"}
SLIT_TYPES = {1: (2.0, .00225), 2: (7.0, .00625)}
# mono_getMirrorPosition / mono_moveMirror: índices de comando desde cero.
# En esta unidad configuration.mirrors enumera 2, pero el comando usa EXIT=1.
EXIT_MIRROR = 1
OUTPUT_POSITIONS = {"Axial": 0, "Lateral": 1}
# SDK oficial Monochromator.Grating: FIRST=0, SECOND=1, THIRD=2.
GRATING_POSITIONS = {1: 0, 2: 1, 3: 2}


class HoribaError(RuntimeError):
    """Fallo de comunicación o de confirmación con el iHR320."""


class HoribaCancelled(RuntimeError):
    """Se abandonó una espera. El movimiento ya enviado puede continuar."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def number(value, label, minimum=None, strict=False):
    try:
        result = float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        raise ValueError("{}: ingrese un número.".format(label))
    if not math.isfinite(result):
        raise ValueError("{}: debe ser finito.".format(label))
    if minimum is not None and (result < minimum or (strict and result == minimum)):
        raise ValueError("{}: debe ser {} {}.".format(label, ">" if strict else ">=", minimum))
    return result


def integer(value, label, minimum=0, maximum=100000):
    result = number(value, label, minimum)
    if not result.is_integer() or result > maximum:
        raise ValueError("{}: entero entre {} y {}.".format(label, minimum, maximum))
    return int(result)


@dataclass(frozen=True)
class InstrumentStatus:
    state: str = "disconnected"
    detail: str = "Sin sesión con el instrumento."


@dataclass
class HoribaSettings:
    url: str = DEFAULT_ICL_URL
    index: int = 0
    timeout_s: float = 8
    move_timeout_s: float = 180
    tolerance_nm: float = .01
    minimum_nm: float = 1
    maximum_nm: float = 1500
    slit_in: int = 0
    slit_out: int = 0
    initialize_timeout_s: float = 180
    slit_timeout_s: float = 30

    def validate(self):
        if self.url not in ("ws://127.0.0.1:25010", "ws://localhost:25010"):
            raise ValueError("Use el ICL local: " + DEFAULT_ICL_URL + ".")
        self.index = integer(self.index, "Índice ICL", 0, 99)
        for key in ("timeout_s", "move_timeout_s", "initialize_timeout_s", "slit_timeout_s",
                    "tolerance_nm", "minimum_nm", "maximum_nm"):
            setattr(self, key, number(getattr(self, key), key, 0, True))
        if self.maximum_nm <= self.minimum_nm:
            raise ValueError("El límite superior de λ debe superar al inferior.")
        for key in ("slit_in", "slit_out"):
            setattr(self, key, integer(getattr(self, key), key, 0, 4))
        if bool(self.slit_in) != bool(self.slit_out) or (self.slit_in and self.slit_in == self.slit_out):
            raise ValueError("Rendijas: detección de ambas (0/0), o dos ubicaciones distintas entre 1 y 4.")
        if self.slit_in not in (0, 1, 2) or self.slit_out not in (0, 3, 4):
            raise ValueError("Rendija de entrada: 1 o 2; salida: 3 o 4; 0/0 detecta los puertos instalados.")
        return self


class ICLMonochromator:
    """Sesión ICL con un monocromador. Todas las llamadas son bloqueantes."""

    def __init__(self, settings=None, socket_factory=None):
        self.settings = (settings or HoribaSettings()).validate()
        self.socket_factory = socket_factory
        self.socket = None
        self.sequence = 0
        self.opened = False
        self.info, self.device = {}, {}
        self.status = InstrumentStatus()
        self.last_snapshot = self.last_initialization = None
        self.slit_ports, self.slit_positions = {}, {}
        self.last_slit_move = None
        self.output_position = None
        self.output_monitoring = False
        self.gratings = {}
        self.grating_position = self.grating_wavelength_nm = None
        self.grating_monitoring = False
        self._initialization_lock = threading.Lock()

    # ------------------------------------------------------------ transporte
    def _connect_socket(self):
        if self.socket is None:
            factory = self.socket_factory
            if factory is None:
                try:
                    from websocket import create_connection
                except ImportError as exc:
                    raise HoribaError(
                        "Falta el paquete websocket-client en este entorno de Python. Active pump_probe_gui "
                        "(activate.bat) y ejecute: python -m pip install " + WEBSOCKET_REQUIREMENT
                        + " (ver docs/HORIBA_iHR320.md).") from exc
                factory = create_connection
            try:
                self.socket = factory(self.settings.url, timeout=self.settings.timeout_s)
            except Exception as exc:
                raise HoribaError("No se pudo conectar a ICL en {}. Abra icl.exe y revise su licencia: {}".format(
                    self.settings.url, exc)) from exc

    def request(self, command, parameters=None, timeout=None):
        self.sequence += 1
        request_id = self.sequence
        deadline = time.monotonic() + (self.settings.timeout_s if timeout is None else timeout)
        try:
            self._connect_socket()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("ICL no respondió dentro del timeout.")
            self.socket.settimeout(remaining)
            self.socket.send(json.dumps(dict(id=request_id, command=command, parameters=parameters or {})))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("ICL no respondió dentro del timeout.")
                self.socket.settimeout(remaining)
                payload = self.socket.recv()
                if time.monotonic() > deadline:
                    raise TimeoutError("ICL respondió después del timeout.")
                if isinstance(payload, bytes):
                    continue  # Eventos binarios ajenos a la respuesta solicitada.
                response = json.loads(payload)
                if response.get("id") != request_id:
                    continue
                if response.get("command") != command:
                    raise ValueError("Respuesta ICL con comando inesperado.")
                errors = response.get("errors") or []
                if errors:
                    detail = "; ".join(str(e) for e in errors)
                    if any(";-1;" in str(e) for e in errors):
                        detail += (" · ICL no tiene un parser para este módulo. Revise Modules/Mono=true y "
                                   "Model=SDK en icl_settings.ini (repair_icl.py del software de calibración).")
                    raise HoribaError(command + ": " + detail)
                return response.get("results") or {}
        except Exception as exc:
            self.drop()
            self.status = InstrumentStatus("error", "{}: {}".format(command, exc))
            logger.warning("ICL comando=%s id=%s índice=%s: %s", command, request_id, self.settings.index, exc)
            if isinstance(exc, HoribaError):
                raise
            raise HoribaError("Falló {}: {}. Reconecte; no se reintenta la orden.".format(command, exc)) from exc

    def command(self, command, deadline=None, timeout_message=None, **parameters):
        timeout = self.settings.timeout_s
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HoribaError(timeout_message or "Timeout de la operación; estado sin confirmar.")
            timeout = min(timeout, remaining)
        return self.request(command, dict(index=self.settings.index, **parameters), timeout=timeout)

    def _flag(self, command, key, deadline=None, timeout_message=None):
        value = self.command(command, deadline=deadline, timeout_message=timeout_message).get(key)
        if type(value) is not bool:
            self.status = InstrumentStatus("error", "Respuesta inválida de {}: {}".format(command, key))
            raise HoribaError(self.status.detail)
        return value

    def _wait_idle(self, deadline, cancel, timeout_message, cancel_message):
        while True:
            if cancel.is_set():
                raise HoribaCancelled(cancel_message)
            if not self._flag("mono_isBusy", "busy", deadline, timeout_message):
                return
            if cancel.wait(min(.1, max(0, deadline - time.monotonic()))):
                raise HoribaCancelled(cancel_message)

    def _ready(self, detail):
        self.status = InstrumentStatus("ready", detail)

    # ------------------------------------------------------------ sesión
    def diagnose(self):
        """No abre ni inicializa motores; enumera dispositivos USB."""
        self.info = self.request("icl_info")
        discovered = self.request("mono_discover")
        devices = self.request("mono_list").get("devices", [])
        return dict(icl=self.info, discovery=discovered, devices=devices)

    def _open(self):
        if self.opened and self.socket is not None:
            return
        report = self.diagnose()
        matches = [d for d in report["devices"] if d.get("index") == self.settings.index]
        if len(matches) != 1:
            self.drop()
            raise HoribaError("No se encontró el monocromador con índice {}. Detectados: {}".format(
                self.settings.index, report["devices"]))
        self.device = matches[0]
        self.command("mono_open")
        self.opened = True

    def open_session(self):
        """Abre la sesión y consulta disponibilidad; nunca inicia homing."""
        self._open()
        if self.info.get("nodeApiVersion") != 300:
            self.status = InstrumentStatus("error", "Control documentado para ICL API 300; versión recibida: {}.".format(
                self.info.get("nodeApiVersion")))
            raise HoribaError(self.status.detail)
        flags = self.read_flags()
        if flags["busy"]:
            self.status = InstrumentStatus("busy", "HORIBA ocupado; espere y vuelva a consultar.")
        elif not flags["initialized"]:
            self.status = InstrumentStatus("not_initialized", "Sesión abierta; el instrumento no está inicializado.")
        else:
            self._ready("Sesión abierta; instrumento inicializado.")
        return dict(flags, device=dict(self.device), icl=dict(self.info))

    def read_flags(self, deadline=None):
        return dict(busy=self._flag("mono_isBusy", "busy", deadline),
                    initialized=self._flag("mono_isInitialized", "initialized", deadline))

    def require_ready(self, deadline=None):
        if self._flag("mono_isBusy", "busy", deadline):
            self.status = InstrumentStatus("error", "Instrumento ocupado; disponibilidad sin confirmar.")
            raise HoribaError("HORIBA ocupado; espere a que termine el movimiento en curso.")
        if not self._flag("mono_isInitialized", "initialized", deadline):
            self.status = InstrumentStatus("not_initialized", "Instrumento sin inicializar.")
            raise HoribaError("HORIBA sin inicializar. Pulse Inicializar HORIBA.")

    def snapshot(self, deadline=None):
        self.require_ready(deadline)
        result = dict(wavelength_nm=number(self.command("mono_getPosition", deadline=deadline)["wavelength"], "λ leída", 0, True),
                      grating="G{}".format(integer(self.command("mono_getGratingPosition", deadline=deadline)["position"], "Grating", 0, 2)+1))
        self.grating_position = int(result["grating"][1:])
        self.grating_wavelength_nm = result["wavelength_nm"]
        if self.grating_monitoring:
            if self.grating_position not in self.gratings:
                self.grating_position = self.grating_wavelength_nm = None
                raise HoribaError("La torreta informó un grating ausente en su configuración.")
            result["grating_info"] = dict(self.gratings[self.grating_position])
        for key, location in (("slit_in_mm", self.settings.slit_in), ("slit_out_mm", self.settings.slit_out)):
            if location:
                result[key] = number(self.command("mono_getSlitPositionInMM", deadline=deadline, locationId=location)["position"], key, 0)
                maximum = self.slit_ports.get(key, {}).get("maximum_mm", 7)
                if result[key] > maximum + 1e-6:
                    raise HoribaError("Rendija en puerto {}: lectura fuera del rango 0–{} mm.".format(location, maximum))
        self.slit_positions = {key: result[key] for key in ("slit_in_mm", "slit_out_mm") if key in result}
        if self.output_monitoring:
            result["output_port"] = self._read_output_position(deadline)
        self.last_snapshot = result
        self._ready("ICL confirmó inicialización y lectura: λ={} nm, {} ({}).".format(
            result["wavelength_nm"], result["grating"], self.device.get("serialNumber", "serie no informada")))
        return result

    def initialize(self, cancel=None):
        """ICL API 300: homing explícito, sin forzar ni repetir órdenes inciertas.

        La apertura usa el timeout de consulta; el presupuesto de
        inicialización cubre comprobaciones, homing y lectura final.
        Cancelar abandona la espera, no detiene los motores.
        """
        if not self._initialization_lock.acquire(blocking=False):
            raise HoribaError("Ya hay una operación de inicialización o rendijas en curso.")
        cancel = cancel or threading.Event()
        sent = False
        self.status = InstrumentStatus("initializing", "Abriendo comunicación y consultando el instrumento…")
        try:
            if cancel.is_set():
                raise HoribaCancelled("Inicialización cancelada antes de abrir el equipo.")
            self._open()
            if self.info.get("nodeApiVersion") != 300:
                raise HoribaError("Inicialización documentada para ICL API 300; versión recibida: {}.".format(
                    self.info.get("nodeApiVersion")))
            deadline = time.monotonic() + self.settings.initialize_timeout_s
            message = "Timeout de inicialización. El homing puede continuar; consulte el estado antes de reintentar."
            if self._flag("mono_isBusy", "busy", deadline, message):
                raise HoribaError("HORIBA ocupado. No se envió mono_init; espere y consulte el estado.")
            already = self._flag("mono_isInitialized", "initialized", deadline, message)
            if cancel.is_set():
                raise HoribaCancelled("Inicialización cancelada antes de enviar homing.")
            if not already:
                self.status = InstrumentStatus("initializing", "Homing en curso; esperando confirmación de ICL…")
                # El envío puede haber llegado aunque se pierda la respuesta.
                sent = True
                self.command("mono_init", deadline=deadline, timeout_message=message, force=False)
                self._wait_idle(deadline, cancel, message,
                                "Espera de inicialización cancelada. El homing puede continuar.")
            if cancel.is_set():
                raise HoribaCancelled("Espera de inicialización cancelada. El homing puede continuar.")
            snapshot = self.snapshot(deadline)
            self.last_initialization = dict(utc=utc_now(), already_initialized=already,
                                            initialization_sent=sent, snapshot=snapshot, device=dict(self.device))
            logger.info("Inicialización ICL índice=%s serie=%s enviada=%s lectura=%s",
                        self.settings.index, self.device.get("serialNumber"), sent, snapshot)
            return self.last_initialization
        except Exception as exc:
            # Sin reenvío ni órdenes de motor/cierre tras un resultado incierto.
            self.drop()
            detail = str(exc)
            if sent and "homing puede continuar" not in detail:
                detail += " El homing puede continuar; consulte el estado antes de reintentar."
            self.status = InstrumentStatus("error", detail)
            logger.warning("Inicialización ICL índice=%s serie=%s enviada=%s: %s",
                           self.settings.index, self.device.get("serialNumber"), sent, detail)
            if isinstance(exc, (HoribaError, HoribaCancelled)):
                raise type(exc)(detail) from exc
            raise HoribaError("No se confirmó la inicialización: " + detail) from exc
        finally:
            self._initialization_lock.release()

    # ------------------------------------------------------------ rendijas
    def _load_slit_ports(self):
        response = self.command("mono_getConfig").get("configuration")
        config = json.loads(response) if isinstance(response, str) else response
        if not isinstance(config, dict) or not isinstance(config.get("ports"), list):
            raise HoribaError("ICL no informó una configuración válida de rendijas.")
        installed = {}
        for item in config["ports"]:
            location = integer(item.get("locationId"), "Puerto de rendija", 1, 4)
            if location in installed:
                raise HoribaError("ICL informó un puerto de rendija duplicado.")
            installed[location] = item.get("slitType")
        selected = {}
        for key, chosen, allowed in (("slit_in_mm", self.settings.slit_in, (1, 2)),
                                     ("slit_out_mm", self.settings.slit_out, (3, 4))):
            name = "Entrada" if key == "slit_in_mm" else "Salida"
            candidates = [location for location in installed if location in allowed]
            if not chosen:
                if len(candidates) != 1:
                    raise HoribaError("{}: puertos detectados {}. Configure el puerto de rendija en horiba/slit_in y horiba/slit_out.".format(name, candidates))
                chosen = candidates[0]
            if chosen not in candidates:
                raise HoribaError("{}: el puerto {} no está instalado para esta función.".format(name, chosen))
            slit_type = installed[chosen]
            if type(slit_type) is not int or slit_type not in SLIT_TYPES:
                raise HoribaError("Puerto {}: tipo de rendija desconocido {}; movimiento bloqueado.".format(chosen, slit_type))
            maximum, step = SLIT_TYPES[slit_type]
            selected[key] = dict(locationId=chosen, label=SLIT_LOCATIONS[chosen], slitType=slit_type,
                                 minimum_mm=0., maximum_mm=maximum, step_mm=step)
        self.slit_ports = selected
        self.settings.slit_in = selected["slit_in_mm"]["locationId"]
        self.settings.slit_out = selected["slit_out_mm"]["locationId"]

    def _read_slit_positions(self, deadline=None):
        actual = {}
        message = "Timeout de ajuste de rendijas; posición sin confirmar."
        for key, port in self.slit_ports.items():
            value = number(self.command("mono_getSlitPositionInMM", deadline, message,
                                        locationId=port["locationId"])["position"], "Apertura leída [mm]", 0)
            if value > port["maximum_mm"] + 1e-6:
                raise HoribaError("Puerto {}: apertura leída fuera de rango: {} mm.".format(port["locationId"], value))
            actual[key] = value
        self.slit_positions = actual
        return dict(actual)

    def read_slits(self):
        """Detecta puertos y lee ambas aperturas sin inicializar ni mover."""
        try:
            self._open()
            self.require_ready()
            if self.info.get("nodeApiVersion") != 300:
                raise HoribaError("Control de rendijas documentado para ICL API 300.")
            self._load_slit_ports()
            actual = self._read_slit_positions()
            self._ready("Rendijas leídas: entrada={} mm, salida={} mm.".format(
                actual["slit_in_mm"], actual["slit_out_mm"]))
            return dict(utc=utc_now(), ports=dict(self.slit_ports), actual_mm=actual)
        except Exception as exc:
            self.drop()
            self.status = InstrumentStatus("error", str(exc))
            logger.warning("Lectura de rendijas índice=%s: %s", self.settings.index, exc)
            raise HoribaError("No se confirmaron las rendijas: " + str(exc)) from exc

    def move_slits(self, entrance_mm=None, exit_mm=None, cancel=None):
        """Aplica una o ambas aperturas secuencialmente, con lectura posterior.

        No se reenvía un movimiento incierto ni se intenta rollback automático.
        La lectura de ICL es la confirmación disponible; no implica un encoder.
        """
        requested = {key: number(value, "Apertura solicitada [mm]", 0)
                     for key, value in (("slit_in_mm", entrance_mm), ("slit_out_mm", exit_mm)) if value is not None}
        if not requested or any(value > 7 for value in requested.values()):
            raise ValueError("Indique al menos una apertura entre 0 y 7 mm.")
        if not self._initialization_lock.acquire(blocking=False):
            raise HoribaError("Otra operación de inicialización o rendijas está en curso.")
        cancel = cancel or threading.Event()
        report = dict(utc=utc_now(), state="checking", requested_mm=requested, confirmed_moves=[])
        self.last_slit_move = report
        sent = False
        message = "Timeout de ajuste de rendijas; posición sin confirmar."
        try:
            if cancel.is_set():
                raise HoribaCancelled("Ajuste de rendijas cancelado antes del movimiento.")
            initial = self.read_slits()
            report.update(ports=initial["ports"], before_mm=initial["actual_mm"])
            # Valida ambos destinos antes de enviar el primero.
            for key, value in requested.items():
                if value > self.slit_ports[key]["maximum_mm"]:
                    raise ValueError("{}: rango de la rendija instalada: 0–{} mm.".format(
                        self.slit_ports[key]["label"], self.slit_ports[key]["maximum_mm"]))
            expected = dict(initial["actual_mm"])
            deadline = time.monotonic() + self.settings.slit_timeout_s
            report["state"] = "moving"
            for key, target in requested.items():
                if cancel.is_set():
                    raise HoribaCancelled("Espera de ajuste de rendijas cancelada.")
                if abs(expected[key]-target) > 1e-9:
                    sent = True
                    self.command("mono_moveSlitMM", deadline, message,
                                 locationId=self.slit_ports[key]["locationId"], position=target)
                    self._wait_idle(deadline, cancel, message, "Espera de ajuste de rendijas cancelada.")
                if cancel.is_set():
                    raise HoribaCancelled("Espera de ajuste de rendijas cancelada.")
                if self.command("mono_isInitialized", deadline, message).get("initialized") is not True:
                    raise HoribaError("El instrumento no confirmó inicialización después del ajuste.")
                actual = self._read_slit_positions(deadline)
                report["actual_mm"] = actual
                # Un paso documentado admite la cuantización del controlador.
                tolerance = self.slit_ports[key]["step_mm"] + 1e-6
                if abs(actual[key]-target) > tolerance:
                    raise HoribaError("{}: solicitado {} mm, leído {} mm (tolerancia {:.6g} mm).".format(
                        self.slit_ports[key]["label"], target, actual[key], tolerance))
                for other in actual:
                    if other != key and abs(actual[other]-expected[other]) > 1e-6:
                        raise HoribaError("La otra rendija cambió inesperadamente: {} de {} a {} mm.".format(
                            self.slit_ports[other]["label"], expected[other], actual[other]))
                expected = actual
                report["confirmed_moves"].append(key)
            report.update(state="confirmed", finished_utc=utc_now())
            self._ready("Rendijas confirmadas por ICL: entrada={} mm, salida={} mm.".format(
                expected["slit_in_mm"], expected["slit_out_mm"]))
            logger.info("Rendijas índice=%s solicitud=%s lectura=%s", self.settings.index, requested, expected)
            return report
        except Exception as exc:
            report.update(state="error", error=str(exc))
            if sent:
                detail = str(exc) + " El movimiento enviado puede continuar; consulte las rendijas antes de reintentar."
                self.drop()
            else:
                detail = str(exc)
            self.status = InstrumentStatus("error", detail)
            logger.warning("Ajuste de rendijas índice=%s solicitud=%s confirmados=%s última_lectura=%s: %s",
                           self.settings.index, requested, report["confirmed_moves"], report.get("actual_mm"), detail)
            if isinstance(exc, (HoribaCancelled, ValueError)):
                raise type(exc)(detail) from exc
            raise HoribaError(detail) from exc
        finally:
            self._initialization_lock.release()

    # ------------------------------------------------------------ salida y red
    def _read_output_position(self, deadline=None):
        response = self.command("mono_getMirrorPosition", deadline, locationId=EXIT_MIRROR)
        code = response.get("position")
        if type(code) is not int or code not in OUTPUT_POSITIONS.values():
            self.output_position = None
            self.status = InstrumentStatus("error", "Posición desconocida del espejo de salida: {!r}.".format(code))
            raise HoribaError(self.status.detail)
        self.output_position = next(name for name, value in OUTPUT_POSITIONS.items() if value == code)
        return self.output_position

    def read_output(self):
        """Consulta exclusivamente el espejo de salida; no homing ni movimientos."""
        try:
            self._open()
            self.require_ready()
            position = self._read_output_position()
            self.output_monitoring = True
            self._ready("Salida óptica leída por ICL: " + position + ".")
            return dict(utc=utc_now(), locationId=EXIT_MIRROR, position=position,
                        position_code=OUTPUT_POSITIONS[position])
        except Exception as exc:
            self.drop()
            self.status = InstrumentStatus("error", str(exc))
            logger.warning("Lectura de salida índice=%s espejo=%s: %s", self.settings.index, EXIT_MIRROR, exc)
            raise HoribaError("No se confirmó la salida óptica: " + str(exc)) from exc

    def read_gratings(self):
        """Consulta catálogo, selección y λ; no homing ni movimientos."""
        try:
            self._open()
            self.require_ready()
            config = self.command("mono_getConfig").get("configuration")
            config = json.loads(config) if isinstance(config, str) else config
            if not isinstance(config, dict) or not isinstance(config.get("gratings"), list) or not config["gratings"]:
                raise HoribaError("ICL no informó un catálogo válido de gratings instalados.")
            gratings = {}
            for item in config["gratings"]:
                code = item.get("positionIndex")
                if type(code) is not int or code not in GRATING_POSITIONS.values() or code+1 in gratings:
                    raise HoribaError("Configuración de torreta con posición inválida o duplicada.")
                density = item.get("grooveDensity")
                if density is not None:
                    density = number(density, "Densidad informada", 0)
                blaze = item.get("blaze")
                if blaze is not None:
                    blaze = number(blaze, "Blaze informado", 0)
                # Se conserva blaze sin asignarle unidades no documentadas.
                gratings[code+1] = dict(number=code+1, positionIndex=code, grooves_per_mm=density,
                                        blaze_reported=blaze, description=str(item.get("description") or item.get("name") or ""))
            position = self.command("mono_getGratingPosition").get("position")
            if type(position) is not int or position+1 not in gratings:
                raise HoribaError("Posición de torreta desconocida o no configurada: {!r}.".format(position))
            wavelength = number(self.command("mono_getPosition")["wavelength"], "λ central leída [nm]", 0)
            self.gratings = gratings
            self.grating_position, self.grating_wavelength_nm = position+1, wavelength
            self.grating_monitoring = True
            self._ready("Grating {} leído; λ={} nm.".format(position+1, wavelength))
            return dict(utc=utc_now(), gratings=[dict(gratings[n]) for n in sorted(gratings)],
                        number=position+1, wavelength_nm=wavelength)
        except Exception as exc:
            self.drop()
            self.status = InstrumentStatus("error", str(exc))
            logger.warning("Lectura de torreta índice=%s: %s", self.settings.index, exc)
            raise HoribaError("No se confirmó la torreta: " + str(exc)) from exc

    # ------------------------------------------------------------ longitud de onda
    def move_to(self, target, cancel=None):
        target = number(target, "Destino [nm]", 0, True)
        if not self.settings.minimum_nm <= target <= self.settings.maximum_nm:
            raise ValueError("Destino {} nm fuera de los límites configurados para HORIBA ({}–{} nm).".format(
                target, self.settings.minimum_nm, self.settings.maximum_nm))
        cancel = cancel or threading.Event()
        self.require_ready()
        if cancel.is_set():
            raise HoribaCancelled("Movimiento cancelado antes de enviarse.")
        deadline = time.monotonic() + self.settings.move_timeout_s
        # moveToPosition mueve el motor. setPosition redefine la calibración y NO se utiliza.
        self.request("mono_moveToPosition", dict(index=self.settings.index, wavelength=target),
                     timeout=self.settings.move_timeout_s)
        while True:
            if cancel.is_set():
                raise HoribaCancelled("Medición cancelada. El movimiento de λ ya enviado puede continuar; espere a que HORIBA quede libre.")
            if time.monotonic() >= deadline:
                self.drop()
                raise HoribaError("Timeout de movimiento de λ; no se adquirió el punto. Reconecte y compruebe HORIBA.")
            if not self.command("mono_isBusy")["busy"]:
                break
            cancel.wait(.1)
        actual = self.snapshot()
        if abs(actual["wavelength_nm"]-target) > self.settings.tolerance_nm:
            raise HoribaError(
                "HORIBA informó {} nm para un destino de {} nm; excede la tolerancia de {} nm. Si la diferencia es "
                "sistemática, aumente Tolerancia lambda en el grupo HORIBA (la λ leída se guarda en "
                "longitud_onda_leida_nm).".format(actual["wavelength_nm"], target, self.settings.tolerance_nm))
        return dict(actual, target_nm=target)

    # ------------------------------------------------------------ cierre
    def describe(self):
        return dict(interface="ICL", settings=asdict(self.settings), icl=dict(self.info), device=dict(self.device),
                    initialization=self.last_initialization, slit_ports=dict(self.slit_ports),
                    last_slit_move=self.last_slit_move, output_port=self.output_position,
                    gratings=[dict(self.gratings[n]) for n in sorted(self.gratings)])

    def drop(self):
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
        self.socket, self.opened = None, False
        self.slit_positions = {}
        self.output_position = None
        self.grating_position = self.grating_wavelength_nm = None
        self.status = InstrumentStatus()

    def close(self):
        if self.opened and self.socket is not None:
            try:
                self.command("mono_close")
            except Exception:
                pass
        self.drop()
