"""
mono_horiba.py
==============
Driver SINCRONO para un monocromador Horiba iHR320, construido sobre el EzSpec SDK
(paquete `horiba_sdk`, que habla por websocket JSON con `icl.exe`).

Idea central
------------
El SDK es asincrono (async/await) pero el resto de pump_probe (hardware_adapter,
AcquisitionRunner, GUI) es sincrono y corre en hilos de Qt. Este modulo oculta la
asincronia: crea UN hilo propio con UN event loop y traduce cada llamada sincrona a
`asyncio.run_coroutine_threadsafe(...).result(timeout)`.

Contrato que respeta (el mismo que usaba la clase SMS):
    atributos : posicion (nm comandado), connected
    metodos   : Conectar, Identificar, Configurar, Mover(nm), CalcularTiempoSleep(nm), Cerrar
Extras: posicion_leida, info, config, set_rejilla, set_rendija, set_espejo, leer_posicion,
        cancelar_espera / reiniciar_cancelacion, status_dict.

Requiere Python >= 3.9 y `pip install horiba-sdk` (ver explicacion de versiones).
"""
import asyncio
import concurrent.futures
import logging
import threading
import time

try:
    from horiba_sdk.devices.device_manager import DeviceManager
    from horiba_sdk.devices.single_devices import Monochromator
    SDK_IMPORT_ERROR = None
except Exception as exc:  # el modulo sigue siendo importable sin el SDK (p. ej. en simulacion)
    DeviceManager = None
    Monochromator = None
    SDK_IMPORT_ERROR = exc

log = logging.getLogger("mono_horiba")


class MonoError(Exception):
    """Error de comunicacion o de estado del monocromador."""


def _slit_enum(nombre):
    clave = str(nombre).strip().upper()
    try:
        return getattr(Monochromator.Slit, clave)
    except AttributeError:
        raise ValueError("Rendija desconocida: " + str(nombre) + " (usar A, B, C o D)")


def _mirror_enum(nombre):
    clave = str(nombre).strip().upper()
    try:
        return getattr(Monochromator.Mirror, clave)
    except AttributeError:
        raise ValueError("Espejo desconocido: " + str(nombre) + " (usar ENTRANCE o EXIT)")


def _mirror_pos_enum(nombre):
    clave = str(nombre).strip().upper()
    try:
        return getattr(Monochromator.MirrorPosition, clave)
    except AttributeError:
        raise ValueError("Posicion de espejo desconocida: " + str(nombre) + " (usar AXIAL o LATERAL)")


class HoribaIHR320(object):
    def __init__(
        self,
        host="127.0.0.1",
        port=25010,
        mono_index=0,
        start_icl=True,
        grating_density=None,
        slits_mm=None,
        mirrors=None,
        settle_time_s=0.5,
        move_timeout_s=120.0,
        init_timeout_s=240.0,
        sdk_logging=False,
    ):
        # --- parametros de conexion / configuracion ---
        self.host = host
        self.port = int(port)
        self.mono_index = int(mono_index)
        self.start_icl = bool(start_icl)
        self.grating_density = grating_density      # ej. 1200 (ranuras/mm) o None = no tocar
        self.slits_mm = dict(slits_mm or {})        # ej. {"A": 0.1, "D": 0.1}
        self.mirrors = dict(mirrors or {})          # ej. {"ENTRANCE": "AXIAL", "EXIT": "AXIAL"}
        self.settle_time_s = float(settle_time_s)   # margen tras terminar de moverse
        self.move_timeout_s = float(move_timeout_s)
        self.init_timeout_s = float(init_timeout_s)
        self.sdk_logging = bool(sdk_logging)

        # --- estado visible (cache; leerlo NO hace I/O) ---
        self.connected = False
        self.posicion = 0.0          # ultima lambda COMANDADA (nm). Es la que va a row[7].
        self.posicion_leida = None   # ultima lambda LEIDA del equipo (nm). Solo informativa.
        self.last_move_s = None      # duracion del ultimo movimiento (para estimar tiempos)
        self.config = None           # dict de mono_getConfig
        self.info = dict()           # resumen: modelo, serie, rejilla actual...

        # --- internos ---
        self._gratings = dict()      # {grooveDensity: positionIndex}
        self._loop = None
        self._thread = None
        self._lock = None            # asyncio.Lock, se crea DENTRO del loop
        self._manager = None
        self._mono = None
        self._cancel = threading.Event()

    # ------------------------------------------------------------------
    # Infraestructura: hilo + event loop
    # ------------------------------------------------------------------
    def _ensure_loop(self):
        if self._loop is not None:
            return
        loop = asyncio.new_event_loop()
        started = threading.Event()

        def runner():
            asyncio.set_event_loop(loop)
            loop.call_soon(started.set)
            loop.run_forever()

        hilo = threading.Thread(target=runner, name="ihr320-loop", daemon=True)
        hilo.start()
        started.wait(5.0)
        self._loop = loop
        self._thread = hilo

    def _shutdown_loop(self):
        loop, hilo = self._loop, self._thread
        self._loop = None
        self._thread = None
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if hilo is not None:
            hilo.join(5.0)
        if hilo is None or not hilo.is_alive():
            loop.close()

    def _run(self, coro, timeout):
        """Ejecuta una corrutina en el loop del driver y espera el resultado (bloqueante)."""
        if self._loop is None:
            coro.close()
            raise MonoError("El monocromador no esta conectado (no hay loop activo).")
        futuro = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return futuro.result(timeout)
        except concurrent.futures.TimeoutError:
            futuro.cancel()
            raise MonoError("Timeout de " + str(timeout) + " s esperando al monocromador.")

    async def _call(self, funcion, *args):
        """Serializa cada comando: el SDK no correlaciona respuestas por id."""
        async with self._lock:
            return await funcion(*args)

    async def _wait_idle(self, timeout, settle=0.3, poll=0.2, cancellable=True):
        """Espera a que is_busy() sea False en dos lecturas seguidas.
        Devuelve True si quedo libre, False si se cancelo la espera."""
        loop = asyncio.get_event_loop()
        fin = loop.time() + float(timeout)
        await asyncio.sleep(settle)  # el flag busy puede tardar en subir tras el comando
        libres = 0
        while True:
            if cancellable and self._cancel.is_set():
                return False
            busy = await self._call(self._mono.is_busy)
            if busy:
                libres = 0
            else:
                libres += 1
                if libres >= 2:
                    return True
            if loop.time() > fin:
                raise TimeoutError("El monocromador sigue ocupado tras " + str(timeout) + " s.")
            await asyncio.sleep(poll)

    # ------------------------------------------------------------------
    # Cancelacion (solo corta la ESPERA; el equipo no tiene comando de stop)
    # ------------------------------------------------------------------
    def cancelar_espera(self):
        self._cancel.set()

    def reiniciar_cancelacion(self):
        self._cancel.clear()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def Conectar(self):
        if SDK_IMPORT_ERROR is not None:
            raise MonoError("No se pudo importar horiba_sdk: " + str(SDK_IMPORT_ERROR))
        if self.connected:
            return
        self._ensure_loop()
        try:
            self._run(self._conectar(), 120.0)
        except Exception:
            try:
                self._run(self._cerrar(), 60.0)
            except Exception:
                pass
            self._shutdown_loop()
            raise
        self.connected = True

    async def _conectar(self):
        self._lock = asyncio.Lock()  # dentro del loop (Python 3.9 liga el Lock al loop actual)
        self._manager = DeviceManager(
            start_icl=self.start_icl,
            icl_ip=self.host,
            icl_port=str(self.port),
            enable_binary_messages=False,
            enable_logging=self.sdk_logging,
        )
        await self._manager.start()  # arranca/espera ICL, abre websocket y descubre equipos
        monos = self._manager.monochromators
        if len(monos) == 0:
            raise MonoError("ICL no encontro ningun monocromador (USB, alimentacion, otro software abierto?).")
        if self.mono_index >= len(monos):
            raise MonoError("mono_index=" + str(self.mono_index) + " fuera de rango (hay " + str(len(monos)) + ").")
        self._mono = monos[self.mono_index]
        await self._call(self._mono.open)
        await self._wait_idle(60.0, settle=0.3, cancellable=False)

    def Cerrar(self):
        if self._loop is not None:
            try:
                self._run(self._cerrar(), 120.0)
            except Exception as exc:
                log.warning("Error al cerrar el monocromador: %s", exc)
            self._shutdown_loop()
        self.connected = False

    async def _cerrar(self):
        if self._mono is not None:
            try:
                await self._wait_idle(60.0, settle=0.0, cancellable=False)  # que termine lo que este haciendo
            except Exception:
                pass
            try:
                await self._mono.close()
            except Exception as exc:
                log.warning("mono.close fallo: %s", exc)
        if self._manager is not None:
            try:
                await self._manager.stop()  # con start_icl=True esto apaga icl.exe
            except Exception as exc:
                log.warning("manager.stop fallo: %s", exc)
        self._mono = None
        self._manager = None

    # ------------------------------------------------------------------
    # Identificacion y configuracion
    # ------------------------------------------------------------------
    async def _leer_config(self):
        cfg = await self._call(self._mono.configuration)
        self.config = cfg
        self._gratings = dict()
        for g in cfg.get("gratings", []):
            self._gratings[int(g["grooveDensity"])] = int(g["positionIndex"])
        self.info["model"] = cfg.get("model", cfg.get("monoModel"))
        self.info["serial"] = cfg.get("serialNumber")
        self.info["gratings"] = dict(self._gratings)
        return cfg

    def Identificar(self):
        """True si el equipo conectado reporta un iHR320."""
        cfg = self._run(self._leer_config(), 30.0)
        modelo = str(cfg.get("model", cfg.get("monoModel", ""))).upper()
        return "IHR320" in modelo

    def Configurar(self):
        """Homing si hace falta, rejilla, espejos, rendijas y lectura de la lambda inicial."""
        self._run(self._configurar(), self.init_timeout_s + 300.0)

    async def _configurar(self):
        await self._wait_idle(60.0, settle=0.0, cancellable=False)
        if not await self._call(self._mono.is_initialized):
            log.info("Monocromador sin inicializar: homing (puede tardar)...")
            await self._call(self._mono.initialize)
            await self._wait_idle(self.init_timeout_s, settle=1.0, cancellable=False)
        if self.config is None:
            await self._leer_config()
        if self.grating_density is not None:
            await self._set_rejilla(self.grating_density)
        for nombre, pos in self.mirrors.items():
            await self._set_espejo(nombre, pos)
        for nombre, mm in self.slits_mm.items():
            await self._set_rendija(nombre, mm)
        lam = await self._leer_lambda()
        self.posicion = lam  # punto de partida de la logica "mover solo si cambia"

    # --- rejilla / espejos / rendijas (movimientos lentos, no cancelables) ---
    async def _set_rejilla(self, densidad):
        idx = self._gratings.get(int(densidad))
        if idx is None:
            raise ValueError("Rejilla " + str(densidad) + " no disponible. Disponibles: " + str(sorted(self._gratings)))
        destino = Monochromator.Grating(idx)
        actual = await self._call(self._mono.get_turret_grating)
        if actual != destino:
            await self._call(self._mono.set_turret_grating, destino)
            await self._wait_idle(self.move_timeout_s, cancellable=False)
        self.info["grating_density"] = int(densidad)

    async def _set_espejo(self, espejo, posicion):
        await self._call(self._mono.set_mirror_position, _mirror_enum(espejo), _mirror_pos_enum(posicion))
        await self._wait_idle(self.move_timeout_s, cancellable=False)
        self.info["mirror_" + str(espejo).lower()] = str(posicion).upper()

    async def _set_rendija(self, nombre, mm):
        await self._call(self._mono.set_slit_position, _slit_enum(nombre), float(mm))
        await self._wait_idle(self.move_timeout_s, cancellable=False)
        self.info["slit_" + str(nombre).lower() + "_mm"] = float(mm)

    def set_rejilla(self, densidad):
        self._run(self._set_rejilla(densidad), self.move_timeout_s + 30.0)

    def set_espejo(self, espejo, posicion):
        self._run(self._set_espejo(espejo, posicion), self.move_timeout_s + 30.0)

    def set_rendija(self, nombre, mm):
        self._run(self._set_rendija(nombre, mm), self.move_timeout_s + 30.0)

    def leer_rendija(self, nombre):
        return self._run(self._call(self._mono.get_slit_position_in_mm, _slit_enum(nombre)), 15.0)

    # ------------------------------------------------------------------
    # Longitud de onda
    # ------------------------------------------------------------------
    async def _leer_lambda(self):
        lam = await self._call(self._mono.get_current_wavelength)
        self.posicion_leida = float(lam)
        return float(lam)

    def leer_posicion(self):
        """Consulta la lambda real al equipo (hace I/O; no llamar desde status())."""
        return self._run(self._leer_lambda(), 15.0)

    async def _mover(self, nm):
        t0 = time.time()
        await self._call(self._mono.move_to_target_wavelength, nm)  # el ack llega rapido
        self.posicion = nm  # lambda comandada: la que se guarda en row[7]
        terminado = await self._wait_idle(self.move_timeout_s)
        if terminado:
            await self._leer_lambda()
            self.last_move_s = time.time() - t0
        return terminado

    def Mover(self, longitud_onda_nm):
        """Mueve y BLOQUEA hasta que el equipo termina. Devuelve False si se cancelo la espera."""
        if not self.connected:
            raise MonoError("El monocromador no esta conectado.")
        return self._run(self._mover(float(longitud_onda_nm)), self.move_timeout_s + 30.0)

    def CalcularTiempoSleep(self, longitud_onda_nm):
        """Como Mover() ya bloquea, solo se devuelve el margen de asentamiento."""
        if float(longitud_onda_nm) == float(self.posicion):
            return 0.1
        return self.settle_time_s

    # ------------------------------------------------------------------
    # Estado cacheado (SIN I/O: seguro de llamar desde la GUI en cada punto)
    # ------------------------------------------------------------------
    def status_dict(self):
        d = dict(self.info)
        d.update(
            {
                "connected": bool(self.connected),
                "posicion": float(self.posicion),
                "posicion_leida": self.posicion_leida,
                "last_move_s": self.last_move_s,
            }
        )
        return d