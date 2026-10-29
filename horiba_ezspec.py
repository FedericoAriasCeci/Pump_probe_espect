"""Control independiente del HORIBA iHR320 mediante EzSpec-SDK (horiba-sdk).

API sincrona para la futura integracion pump-probe. El SDK y su websocket viven
siempre en un unico bucle asyncio, alojado en un hilo propio. No importa la GUI,
el lock-in, Kinesis ni el adaptador COM existente. Requiere Python >= 3.9.
"""

import asyncio
import copy
import math
import re
import threading
import warnings
from concurrent.futures import TimeoutError as FutureTimeoutError


class HoribaError(RuntimeError):
    """Error de comunicacion, estado o verificacion del instrumento."""


class HoribaTimeoutError(HoribaError, TimeoutError):
    """Vencio un plazo; el movimiento fisico puede seguir ejecutandose."""


def _finite(value, name, minimum=0.0, positive=False):
    if isinstance(value, bool):
        raise ValueError(name + " debe ser un numero finito.")
    result = float(value)
    if not math.isfinite(result) or result < minimum or (positive and result == minimum):
        raise ValueError(name + " fuera de rango.")
    return result


def _integer(value, name, minimum, maximum=None):
    if isinstance(value, bool):
        raise ValueError(name + " debe ser entero.")
    number = _finite(value, name, minimum)
    if not number.is_integer() or (maximum is not None and number > maximum):
        raise ValueError(name + " fuera de rango.")
    return int(number)


def _default_manager_factory(**kwargs):
    try:
        from horiba_sdk.devices import DeviceManager
    except ImportError as exc:
        raise HoribaError(
            "No se pudo importar EzSpec-SDK. Use Python >= 3.9 e instale "
            "requirements-horiba-ezspec.txt en ese mismo entorno. Detalle: " + str(exc)
        ) from exc
    return DeviceManager(**kwargs)


class HoribaEzSpec:
    """Controlador sincrono del iHR320; longitudes en nm y rendijas en mm.

    ICL debe estar ejecutandose, instalado y licenciado. El controlador abre y
    cierra su conexion sin apagar el servicio ICL. connect() no hace homing.
    initialize() lo hace solamente si hace falta, o con force=True.

    Los metodos bloquean hasta completar la operacion: llamarlos desde el hilo
    de adquisicion, no desde el hilo de la interfaz grafica. Las llamadas desde
    distintos hilos se serializan. manager_factory permite pruebas sin hardware.
    """

    def __init__(
        self, device_id=None, host="127.0.0.1", port=25010,
        connection_timeout_s=60.0, motion_timeout_s=180.0,
        poll_interval_s=0.1, wavelength_tolerance_nm=0.05,
        wavelength_limits_nm=None, enable_logging=False, manager_factory=None,
    ):
        self.device_id = None if device_id is None else _integer(device_id, "device_id", 0)
        self.host = str(host).strip()
        if not self.host:
            raise ValueError("host no puede estar vacio.")
        self.port = _integer(port, "port", 1, 65535)
        self.connection_timeout_s = _finite(connection_timeout_s, "connection_timeout_s", positive=True)
        self.motion_timeout_s = _finite(motion_timeout_s, "motion_timeout_s", positive=True)
        self.poll_interval_s = _finite(poll_interval_s, "poll_interval_s", positive=True)
        self.wavelength_tolerance_nm = _finite(wavelength_tolerance_nm, "wavelength_tolerance_nm", positive=True)
        self.wavelength_limits_nm = None
        if wavelength_limits_nm is not None:
            low, high = wavelength_limits_nm
            low, high = _finite(low, "lambda minima"), _finite(high, "lambda maxima")
            if low >= high:
                raise ValueError("La longitud minima debe ser menor que la maxima.")
            self.wavelength_limits_nm = (low, high)
        self._factory = manager_factory or _default_manager_factory
        self._logging = bool(enable_logging)
        self._lock = threading.RLock()
        self._loop = None
        self._thread = None
        self._manager = None
        self._mono = None
        self._configuration = {}
        self.connected = False
        self._faulted = False
        self.posicion = None
        self.puerto = "" if self.device_id is None else str(self.device_id)
        self.device_name = ""

    def _start_loop(self):
        if self._loop is not None:
            return
        loop = asyncio.new_event_loop()
        started = threading.Event()

        def run():
            asyncio.set_event_loop(loop)
            started.set()
            try:
                loop.run_forever()
            finally:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()

        self._loop = loop
        self._thread = threading.Thread(target=run, name="HORIBA-EzSpec", daemon=True)
        self._thread.start()
        started.wait()

    def _run(self, operation, *args, timeout_s=None):
        if self._loop is None:
            raise HoribaError("HORIBA no conectado. Use connect().")
        timeout = self.connection_timeout_s if timeout_s is None else timeout_s
        future = asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(operation(*args), timeout=timeout), self._loop
        )
        try:
            return future.result(timeout=timeout + 2.0)
        except (asyncio.TimeoutError, FutureTimeoutError) as exc:
            future.cancel()
            self._faulted = True
            raise HoribaTimeoutError(
                "Tiempo agotado en " + operation.__name__ + " (" + str(timeout) +
                " s). Esto no detiene los motores. Consulte status y espere al "
                "reposo antes de desconectar y reconectar."
            ) from exc
        except (KeyboardInterrupt, SystemExit):
            future.cancel()
            self._faulted = True
            raise
        except HoribaError:
            raise
        except Exception as exc:
            raise HoribaError("EzSpec / " + operation.__name__ + ": " + str(exc)) from exc

    async def _start_manager(self):
        # start_icl=False evita que stop() envie icl_shutdown a un ICL compartido.
        self._manager = self._factory(
            start_icl=False, icl_ip=self.host, icl_port=str(self.port),
            enable_binary_messages=False, enable_logging=self._logging,
        )
        try:
            await self._manager.start()  # start() ya descubre los dispositivos.
        except OSError as exc:
            raise HoribaError(
                "No se pudo conectar a ICL en ws://" + self.host + ":" + str(self.port) +
                ". Inicie el servicio ICL de EzSpec y revise direccion/puerto. Detalle: " + str(exc)
            ) from exc

    @staticmethod
    def _is_ihr320(configuration):
        model = re.sub(r"[^a-z0-9]", "", str(configuration.get("monoModel", "")).lower())
        return model == "ihr320"

    async def _inventory(self):
        inventory = []
        for mono in self._manager.monochromators:
            # Retener la referencia hasta cerrar, incluso si open/config fallan.
            self._mono = mono
            await mono.open()
            config = await mono.configuration()
            inventory.append({
                "device_id": mono.id(), "model": config.get("monoModel", ""),
                "serial_number": config.get("serialNumber", ""), "configuration": config,
            })
            await mono.close()
            self._mono = None
        return inventory

    @classmethod
    def discover(cls, **kwargs):
        """Lista IDs, modelos y configuraciones sin inicializar ni mover."""
        probe = cls(**kwargs)
        with probe._lock:
            probe._start_loop()
            try:
                inventory = probe._run(probe._discover)
            except BaseException:
                try:
                    probe.close()
                except Exception as cleanup_error:
                    warnings.warn("Fallo al cerrar descubrimiento: " + str(cleanup_error), RuntimeWarning)
                raise
            probe.close()
            return inventory

    async def _discover(self):
        await self._start_manager()
        return await self._inventory()

    def connect(self, device_id=None):
        """Conecta un ID EzSpec, o el unico iHR320 descubierto. No hace homing."""
        with self._lock:
            if self.connected:
                raise HoribaError("Ya conectado. Cierre la conexion antes de reconectar.")
            selected = self.device_id if device_id is None else _integer(device_id, "device_id", 0)
            self._start_loop()
            try:
                self._run(self._connect, selected)
                return self.device_id
            except BaseException:
                try:
                    self.close()
                except Exception as cleanup_error:
                    warnings.warn("Fallo al cerrar despues de un error: " + str(cleanup_error), RuntimeWarning)
                raise

    async def _connect(self, selected):
        await self._start_manager()
        inventory = await self._inventory()
        candidates = [row for row in inventory if self._is_ihr320(row["configuration"])]
        if selected is not None:
            candidates = [row for row in candidates if row["device_id"] == selected]
        if len(candidates) != 1:
            raise HoribaError(
                "Se esperaba un iHR320 inequívoco. Use discover() y seleccione device_id. "
                "Dispositivos: " + str([(r["device_id"], r["model"]) for r in inventory])
            )
        info = candidates[0]
        self._mono = next(m for m in self._manager.monochromators if m.id() == info["device_id"])
        await self._mono.open()
        if not await self._mono.is_open():
            raise HoribaError("ICL no confirmo la apertura del iHR320.")
        self.device_id = info["device_id"]
        self.puerto = str(self.device_id)
        self.device_name = info["model"]
        self._configuration = copy.deepcopy(info["configuration"])
        self.connected = True
        self._faulted = False
        self.posicion = None

    async def _disconnect(self):
        errors = []
        if self._mono is not None:
            try:
                await asyncio.wait_for(self._mono.close(), timeout=5.0)
            except Exception as exc:
                errors.append("mono.close: " + str(exc))
        if self._manager is not None:
            try:
                await asyncio.wait_for(self._manager.stop(), timeout=5.0)
            except Exception as exc:
                errors.append("manager.stop: " + str(exc))
        if errors:
            raise HoribaError("; ".join(errors))

    def close(self):
        """Cierra dispositivo, websocket y hilo. No apaga ICL ni aborta motores."""
        with self._lock:
            if self._loop is None:
                return
            loop, thread = self._loop, self._thread
            try:
                self._run(self._disconnect, timeout_s=12.0)
            finally:
                self.connected = False
                self._mono = self._manager = None
                self._configuration = {}
                self.posicion = None
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=5.0)
                if thread.is_alive():
                    # Conservar referencias impide iniciar otro bucle encima del anterior.
                    self._faulted = True
                    raise HoribaError("No se pudo cerrar el hilo del SDK.")
                self._loop = self._thread = None

    def _require_connected(self):
        if not self.connected or self._mono is None:
            raise HoribaError("HORIBA no conectado. Use connect().")

    async def _wait_idle(self):
        self._require_connected()
        while await self._mono.is_busy():
            await asyncio.sleep(self.poll_interval_s)

    def wait_until_idle(self, timeout_s=None):
        with self._lock:
            timeout = self.motion_timeout_s if timeout_s is None else _finite(timeout_s, "timeout_s", positive=True)
            self._run(self._wait_idle, timeout_s=timeout)

    async def _require_ready(self):
        self._require_connected()
        if self._faulted:
            raise HoribaError("La sesion fallo. Consulte status y reconecte despues del reposo.")
        await self._wait_idle()
        if not await self._mono.is_initialized():
            raise HoribaError("El iHR320 no esta inicializado. Use initialize() / Configurar().")

    def initialize(self, force=False):
        """Inicializa y espera. force=True repite el homing aun estando inicializado."""
        with self._lock:
            return self._run(self._initialize, bool(force), timeout_s=self.motion_timeout_s)

    async def _initialize(self, force):
        self._require_connected()
        if self._faulted:
            raise HoribaError("Reconecte antes de inicializar una sesion que fallo.")
        await self._wait_idle()
        if force or not await self._mono.is_initialized():
            await self._mono.initialize()
            await self._wait_idle()
        if not await self._mono.is_initialized():
            raise HoribaError("ICL no confirmo la inicializacion.")
        return await self._read_wavelength()

    async def _read_wavelength(self):
        value = float(await self._mono.get_current_wavelength())
        if not math.isfinite(value):
            raise HoribaError("ICL devolvio una longitud de onda no finita.")
        self.posicion = value
        return value

    def get_wavelength(self):
        with self._lock:
            return self._run(self._get_wavelength, timeout_s=self.motion_timeout_s)

    async def _get_wavelength(self):
        await self._require_ready()
        return await self._read_wavelength()

    def validate_wavelength(self, value):
        """Valida nm y limites experimentales sin enviar comandos al equipo."""
        value = _finite(value, "longitud de onda [nm]")
        if self.wavelength_limits_nm is not None:
            low, high = self.wavelength_limits_nm
            if not low <= value <= high:
                raise ValueError("Longitud de onda fuera de los limites configurados: " + str(self.wavelength_limits_nm))
        return value

    def move_to(self, wavelength_nm):
        """Mueve, espera reposo y verifica lectura. Devuelve la lectura en nm."""
        target = self.validate_wavelength(wavelength_nm)
        with self._lock:
            return self._run(self._move_to, target, timeout_s=self.motion_timeout_s)

    async def _move_to(self, target):
        await self._require_ready()
        await self._mono.move_to_target_wavelength(target)
        await self._wait_idle()
        actual = await self._read_wavelength()
        if abs(actual - target) > self.wavelength_tolerance_nm:
            self._faulted = True
            raise HoribaError("Posicion incorrecta: objetivo=" + str(target) + " nm, lectura=" + str(actual) + " nm.")
        return actual

    def get_status(self):
        with self._lock:
            return self._run(self._get_status)

    async def _get_status(self):
        self._require_connected()
        opened = bool(await self._mono.is_open())
        busy = bool(await self._mono.is_busy())
        # SDK: is_initialized puede devolver False durante un movimiento.
        initialized = None if busy else bool(await self._mono.is_initialized())
        wavelength = await self._read_wavelength() if opened and initialized and not busy else None
        return {
            "device_id": self.device_id, "model": self.device_name,
            "serial_number": self._configuration.get("serialNumber", ""),
            "connected": opened, "busy": busy, "initialized": initialized,
            "faulted": self._faulted, "ready": opened and not busy and bool(initialized) and not self._faulted,
            "wavelength_nm": wavelength,
        }

    def get_configuration(self):
        with self._lock:
            self._require_connected()
            return copy.deepcopy(self._configuration)

    def _accessory(self, method, args=(), setter=False, reader=None, expected=None, tolerance=None):
        with self._lock:
            return self._run(
                self._accessory_async, method, args, setter, reader, expected, tolerance,
                timeout_s=self.motion_timeout_s,
            )

    async def _accessory_async(self, method, args, setter, reader, expected, tolerance):
        await self._require_ready()
        result = await getattr(self._mono, method)(*args)
        if setter:
            await self._wait_idle()
            read_method, read_args = reader
            result = await getattr(self._mono, read_method)(*read_args)
            actual = getattr(result, "value", result)
            matches = actual == expected if tolerance is None else abs(float(actual) - expected) <= tolerance
            if not matches:
                self._faulted = True
                raise HoribaError("No se confirmo " + method + ": objetivo=" + str(expected) + ", lectura=" + str(actual))
            await self._read_wavelength()
        return result

    def get_grating(self):
        """Numero de red para el usuario: 1, 2 o 3 (SDK usa 0, 1 o 2)."""
        return self._accessory("get_turret_grating").value + 1

    def set_grating(self, number):
        number = _integer(number, "red", 1, 3)
        with self._lock:
            self._require_connected()
            installed = {g["positionIndex"] for g in self._configuration.get("gratings", [])}
            if installed and number - 1 not in installed:
                raise ValueError("La red solicitada no figura en la configuracion del instrumento.")
            grating = self._mono.Grating(number - 1)
            return self._accessory(
                "set_turret_grating", (grating,), True,
                ("get_turret_grating", ()), number - 1,
            ).value + 1

    def _enum(self, enum_name, name):
        self._require_connected()
        enum_type = getattr(self._mono, enum_name)
        try:
            return enum_type[str(name).upper()]
        except KeyError as exc:
            raise ValueError(enum_name + " invalido: " + str(name) + ". Opciones: " + ", ".join(enum_type.__members__)) from exc

    def get_slit_width(self, slit):
        with self._lock:
            return float(self._accessory("get_slit_position_in_mm", (self._enum("Slit", slit),)))

    def set_slit_width(self, slit, width_mm):
        width = _finite(width_mm, "ancho de rendija [mm]")
        with self._lock:
            port = self._enum("Slit", slit)
            return float(self._accessory(
                "set_slit_position", (port, width), True,
                ("get_slit_position_in_mm", (port,)), width, 0.002,
            ))

    def get_mirror(self, mirror):
        with self._lock:
            return self._accessory("get_mirror_position", (self._enum("Mirror", mirror),)).name.lower()

    def set_mirror(self, mirror, position):
        with self._lock:
            mirror_enum = self._enum("Mirror", mirror)
            pos = self._enum("MirrorPosition", position)
            return self._accessory(
                "set_mirror_position", (mirror_enum, pos), True,
                ("get_mirror_position", (mirror_enum,)), pos.value,
            ).name.lower()

    def get_shutter(self):
        return self._accessory("get_current_shutter_position").name.lower()

    def set_shutter(self, opened):
        if not isinstance(opened, bool):
            raise ValueError("opened debe ser True o False.")
        return self._accessory(
            "open_shutter" if opened else "close_shutter", (), True,
            ("get_current_shutter_position", ()), int(opened),
        ).name.lower()

    # Contrato del monocromador usado por pump-probe; todavia no se conecta a la GUI.
    AsignarPuerto = connect
    Configurar = initialize
    LeerPosicion = get_wavelength
    Mover = move_to
    CerrarPuerto = close
    CambiarRed = set_grating

    def Identificar(self):
        if not self.connected:
            return False
        return self.get_status()["connected"]

    def CalcularTiempoSleep(self, wavelength_nm):
        self.validate_wavelength(wavelength_nm)
        # Mover ya espera y verifica. El retardo optico/electronico es externo.
        return 0.0

    def Calibrar(self):
        raise NotImplementedError("La calibracion espectral no forma parte de este controlador de medicion.")

    def CambiarVelocidad(self, velocidad):
        raise NotImplementedError("EzSpec no expone un equivalente a la velocidad del SMS en esta API.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.close()
        else:
            try:
                self.close()
            except Exception as cleanup_error:
                warnings.warn("Fallo al cerrar HORIBA: " + str(cleanup_error), RuntimeWarning)
        return False
