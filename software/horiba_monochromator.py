"""HORIBA iHR320 para el programa pump-probe, controlado por ICL (EzSpec-SDK).

Conserva el contrato que usan las rutinas de medición desde el SMS LambdaScan
(``Mover``, ``posicion``, ``CalcularTiempoSleep``, ``CerrarPuerto``) y agrega
lo que el iHR320 permite configurar antes del experimento: inicialización
explícita, lectura del estado y apertura de las rendijas de entrada y salida.

Semántica de las posiciones, igual que en el SMS:

- ``posicion``: última λ solicitada y confirmada por ICL. Es la que se guarda
  en la columna ``longitud_onda_nm`` y la base de los pasos de los barridos.
- ``posicion_leida``: λ informada por ICL después del movimiento (columna
  ``longitud_onda_leida_nm``). Difiere de la solicitada dentro de la tolerancia.

Todas las operaciones son bloqueantes y se serializan entre hilos; deben
llamarse desde un hilo de trabajo. ``CancelarEspera`` puede llamarse desde
cualquier hilo: abandona la espera en curso, pero no frena un motor que ya
recibió la orden (la API ICL usada no expone una parada).
"""
import copy
import threading

from horiba_icl import (
    HoribaCancelled, HoribaError, HoribaSettings, ICLMonochromator,
    integer, number, utc_now,
)


MAX_SLIT_MM = 7.0
SLIT_SAME_TOLERANCE_MM = 1e-6  # ICL informa float32: 0.3 -> 0.30000001192.


def parse_icl_index(value):
    """Índice del equipo en ``mono_list``. Valores heredados (Mono1, COMx) -> 0."""
    text = str(value if value is not None else "").strip()
    if text == "" or not text.isdigit():
        return 0
    return integer(text, "Índice ICL", 0, 99)


class HoribaMonochromator:
    def __init__(self, settings=None, controller_factory=None):
        self.settings = settings if settings is not None else HoribaSettings()
        self.settings.validate()
        self._controller_factory = controller_factory or ICLMonochromator
        self._controller = None
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self.connected = False
        self.initialized = False
        self.posicion = 0.0
        self.posicion_leida = None
        self.puerto = "ICL " + str(self.settings.index)  # Nombre heredado para metadatos.
        self.device = dict()
        self.rendijas = dict()
        self.red = None
        self.salida_optica = None
        self.ultimo_ajuste_rendijas = None
        self.ultima_lectura_utc = None
        self.detalle = "Sin sesión con el instrumento."

    # ------------------------------------------------------------ sesión
    def Conectar(self, indice=None):
        """Abre la sesión ICL. Si el equipo ya está inicializado lee su estado.

        Nunca envía homing: si falta, lo informa y hay que llamar Inicializar.
        """
        with self._lock:
            self._close_locked()
            if indice is not None:
                self.settings.index = parse_icl_index(indice)
            self.puerto = "ICL " + str(self.settings.index)
            controller = self._controller_factory(self.settings)
            self._controller = controller
            try:
                flags = controller.open_session()
                self.device = dict(flags.get("device") or {})
                self.connected = True
                self.initialized = bool(flags["initialized"])
                if flags["busy"]:
                    self.detalle = "HORIBA ocupado; espere y pulse Leer estado."
                elif self.initialized:
                    self._read_state_locked(reset_commanded=True)
                else:
                    self.detalle = "Conectado, sin inicializar. Pulse Inicializar HORIBA (hace homing)."
                return self.estado()
            except Exception as exc:
                self.detalle = str(exc)
                self._close_locked()
                raise

    def AsignarPuerto(self, indice):
        """Nombre heredado del SMS: ``indice`` es el índice ICL, no un puerto COM."""
        self.Conectar(indice)
        return self.puerto

    def Identificar(self):
        with self._lock:
            if not self._session_open():
                return False
            try:
                self._controller.read_flags()
                return True
            except Exception as exc:
                self._after_error(exc)
                return False

    def Inicializar(self):
        """Homing sólo si ICL informa que falta (mono_init force=false)."""
        with self._lock:
            if self._controller is None:
                self.puerto = "ICL " + str(self.settings.index)
                self._controller = self._controller_factory(self.settings)
            controller = self._controller
            self.detalle = "Inicializando…"
            try:
                controller.initialize(self._cancel)
                self.device = dict(controller.device)
                self.connected = True
                self.initialized = True
                return self._read_state_locked(reset_commanded=True)
            except Exception as exc:
                self._after_error(exc)
                raise

    def Configurar(self):
        """Nombre heredado: en el iHR320 equivale a Inicializar."""
        return self.Inicializar()

    def LeerEstado(self):
        """Rendijas, salida óptica, red y λ: sólo consultas, sin mover."""
        with self._lock:
            self._require_session()
            try:
                return self._read_state_locked()
            except Exception as exc:
                self._after_error(exc)
                raise

    def _read_state_locked(self, reset_commanded=False):
        controller = self._controller
        controller.read_slits()
        controller.read_output()
        controller.read_gratings()
        snapshot = controller.snapshot()
        self.initialized = True
        self._update_from_snapshot(snapshot)
        if reset_commanded:
            # Sesión nueva: como Configurar() del SMS, la base de los pasos es la lectura.
            self.posicion = self.posicion_leida
        self.detalle = "Listo."
        return self.estado()

    def LeerPosicion(self):
        with self._lock:
            self._require_session()
            try:
                self._update_from_snapshot(self._controller.snapshot())
            except Exception as exc:
                self._after_error(exc)
                raise
            return self.posicion_leida

    def LeerRendijas(self):
        estado = self.LeerEstado()
        return dict(entrada_mm=estado["rendija_entrada_mm"], salida_mm=estado["rendija_salida_mm"])

    # ------------------------------------------------------------ movimiento
    def Mover(self, longitud_onda_nm):
        """Mueve, espera mono_isBusy=false y confirma la λ dentro de tolerancia."""
        target = number(longitud_onda_nm, "λ destino [nm]", 0, True)
        with self._lock:
            self._require_session()
            try:
                snapshot = self._controller.move_to(target, self._cancel)
            except Exception as exc:
                self._after_error(exc)
                raise
            self.posicion = target
            self._update_from_snapshot(snapshot)
            self.detalle = "Listo."
            return self.posicion_leida

    def CalcularTiempoSleep(self, longitud_onda_nm):
        # Mover() ya espera el fin del movimiento y lo confirma por relectura;
        # la estabilización de la señal la cubre la espera N x tau del SR830.
        return 0.0

    def AjustarRendijas(self, entrada_mm=None, salida_mm=None):
        """Aplica las aperturas pedidas (mm) y las confirma por relectura.

        Sólo se envía la rendija cuya lectura difiere de la pedida.
        """
        requested = dict()
        for key, value, label in (("slit_in_mm", entrada_mm, "Rendija de entrada [mm]"),
                                  ("slit_out_mm", salida_mm, "Rendija de salida [mm]")):
            if value is None:
                continue
            value = number(value, label, 0)
            if value > MAX_SLIT_MM:
                raise ValueError("{}: máximo {} mm.".format(label, MAX_SLIT_MM))
            requested[key] = value
        if not requested:
            raise ValueError("Indique al menos una apertura de rendija.")
        with self._lock:
            self._require_session()
            controller = self._controller
            try:
                before = controller.read_slits()["actual_mm"]
                pending = dict((key, value) for key, value in requested.items()
                               if abs(before[key] - value) > SLIT_SAME_TOLERANCE_MM)
                if pending:
                    report = controller.move_slits(entrance_mm=pending.get("slit_in_mm"),
                                                   exit_mm=pending.get("slit_out_mm"), cancel=self._cancel)
                    report = copy.deepcopy(report)
                else:
                    report = dict(utc=utc_now(), state="unchanged", requested_mm=dict(requested),
                                  before_mm=dict(before), actual_mm=dict(before), confirmed_moves=[])
                report["requested_total_mm"] = dict(requested)
                self._set_slits(report.get("actual_mm") or before)
                self.ultimo_ajuste_rendijas = copy.deepcopy(report)
                self.detalle = "Rendijas confirmadas."
                return report
            except Exception as exc:
                self._after_error(exc)
                raise

    def CancelarEspera(self):
        """Abandona la espera actual (homing, λ o rendijas). No frena motores."""
        self._cancel.set()

    def RearmarCancelacion(self):
        self._cancel.clear()

    def Detener(self):
        self.CancelarEspera()

    # ------------------------------------------------------------ cierre
    def CerrarPuerto(self):
        with self._lock:
            self._close_locked()

    def _close_locked(self):
        controller = self._controller
        self._controller = None
        self.connected = False
        self.initialized = False
        if controller is not None:
            try:
                controller.close()
            except Exception:
                pass

    # ------------------------------------------------------------ estado sin E/S
    def estado(self):
        """Últimos valores conocidos, sin consultar al equipo (seguro desde la GUI)."""
        controller = self._controller
        detail = self.detalle
        state = "disconnected"
        if controller is not None:
            state = controller.status.state
            if controller.status.state == "error":
                detail = controller.status.detail
        rendijas = self.rendijas or {}
        red = self.red or {}
        return {
            "conectado": bool(self.connected),
            "inicializado": bool(self.initialized) if self.connected else None,
            "estado": state,
            "detalle": detail,
            "indice": self.settings.index,
            "serie": self.device.get("serialNumber"),
            "modelo": self.device.get("deviceType"),
            "lambda_comandada_nm": self.posicion,
            "lambda_leida_nm": self.posicion_leida,
            "rendija_entrada_mm": rendijas.get("slit_in_mm"),
            "rendija_salida_mm": rendijas.get("slit_out_mm"),
            "red": red.get("nombre"),
            "red_lineas_mm": red.get("lineas_mm"),
            "salida_optica": self.salida_optica,
            "limites_nm": [self.settings.minimum_nm, self.settings.maximum_nm],
            "tolerancia_nm": self.settings.tolerance_nm,
            "ultima_lectura_utc": self.ultima_lectura_utc,
        }

    def describe(self):
        controller = self._controller
        data = dict(controlador="ICL EzSpec-SDK (WebSocket JSON)", estado=self.estado(),
                    ultimo_ajuste_rendijas=copy.deepcopy(self.ultimo_ajuste_rendijas))
        if controller is not None:
            try:
                data["icl"] = copy.deepcopy(controller.describe())
            except Exception as exc:
                data["icl_error"] = str(exc)
        return data

    # ------------------------------------------------------------ SMS (sin equivalente)
    def Calibrar(self):
        raise NotImplementedError("El iHR320 no se calibra desde este programa; no se usa mono_setPosition.")

    def CambiarVelocidad(self, velocidad):
        raise NotImplementedError("La velocidad del iHR320 no se configura desde este programa.")

    def CambiarRed(self, grating):
        raise NotImplementedError("El cambio de red del iHR320 se hace desde el software de calibración.")

    # ------------------------------------------------------------ internos
    def _session_open(self):
        controller = self._controller
        return bool(self.connected and controller is not None and controller.opened)

    def _require_session(self):
        if not self._session_open():
            self.connected = False
            raise HoribaError("HORIBA desconectado. Pulse Conectar HORIBA y verifique el estado antes de continuar.")
        return self._controller

    def _after_error(self, exc):
        controller = self._controller
        self.connected = bool(controller is not None and controller.opened)
        if isinstance(exc, HoribaCancelled):
            self.detalle = str(exc)
        else:
            self.detalle = "Error: " + str(exc)

    def _set_slits(self, actual_mm):
        self.rendijas = dict((key, actual_mm[key]) for key in ("slit_in_mm", "slit_out_mm") if key in actual_mm)

    def _update_from_snapshot(self, snapshot):
        self.posicion_leida = float(snapshot["wavelength_nm"])
        self.ultima_lectura_utc = utc_now()
        slits = dict((key, snapshot[key]) for key in ("slit_in_mm", "slit_out_mm") if key in snapshot)
        if slits:
            self._set_slits(slits)
        if "output_port" in snapshot:
            self.salida_optica = snapshot["output_port"]
        grating = snapshot.get("grating")
        if grating:
            info = snapshot.get("grating_info") or {}
            self.red = dict(nombre=grating, lineas_mm=info.get("grooves_per_mm"))
