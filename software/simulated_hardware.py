import math
import random
import threading

from horiba_icl import HoribaCancelled, HoribaError
from sr830_timing import filter_settings, settling_seconds


class SimulatedBBD301:
    def __init__(self):
        self.connected = False
        self.homed = False
        self.posicion = 220.0
        self.velocidadMmPorSegundo = 100.0
        self.resolucion = 0.0001
        self._stopped = False

    def Conectar(self):
        self.connected = True
        self._stopped = False

    def Home(self):
        self.homed = True
        self.posicion = 220.0

    def Mover(self, posicion_mm):
        self._stopped = False
        self.posicion = float(posicion_mm)

    def Detener(self):
        self._stopped = True

    def CalcularTiempoSleep(self, posicion_mm):
        return abs(float(posicion_mm) - self.posicion) / self.velocidadMmPorSegundo

    def Cerrar(self):
        self.connected = False


class SimulatedMonochromator:
    """Mismo contrato que HoribaMonochromator (ICL), sin comunicación."""

    def __init__(self):
        self._cancel = threading.Event()
        self.connected = False
        self.initialized = False
        self.puerto = "SIM"
        self.posicion = 650.0
        self.posicion_leida = None
        self.velocidadNmPorSegundo = 9.0
        self.rendijas = {"slit_in_mm": 1.0, "slit_out_mm": 1.0}
        self.red = {"nombre": "G1", "lineas_mm": 1200.0}
        self.salida_optica = "Lateral"
        self.ultimo_ajuste_rendijas = None
        self.detalle = "Simulado."

    def Conectar(self, indice=None):
        self.connected = True
        self.initialized = True
        self.posicion_leida = self.posicion
        return self.estado()

    def AsignarPuerto(self, puerto):
        self.puerto = str(puerto)
        self.Conectar()
        return self.puerto

    def CerrarPuerto(self):
        self.connected = False

    def Inicializar(self):
        return self.Conectar()

    def Configurar(self):
        return self.Inicializar()

    def Identificar(self):
        return self.connected

    def LeerEstado(self):
        self._require_connected()
        self.posicion_leida = self.posicion
        return self.estado()

    def LeerPosicion(self):
        self._require_connected()
        self.posicion_leida = self.posicion
        return self.posicion_leida

    def Mover(self, longitud_onda_nm):
        self._require_connected()
        if self._cancel.is_set():
            raise HoribaCancelled("Movimiento simulado cancelado.")
        self.posicion = float(longitud_onda_nm)
        self.posicion_leida = self.posicion
        return self.posicion_leida

    def CalcularTiempoSleep(self, longitud_onda_nm):
        return abs(float(longitud_onda_nm) - self.posicion) / self.velocidadNmPorSegundo

    def AjustarRendijas(self, entrada_mm=None, salida_mm=None):
        self._require_connected()
        if self._cancel.is_set():
            raise HoribaCancelled("Ajuste de rendijas simulado cancelado.")
        before = dict(self.rendijas)
        requested = dict()
        for key, value in (("slit_in_mm", entrada_mm), ("slit_out_mm", salida_mm)):
            if value is None:
                continue
            value = float(value)
            if not 0.0 <= value <= 7.0:
                raise ValueError("Apertura de rendija entre 0 y 7 mm.")
            requested[key] = value
        if not requested:
            raise ValueError("Indique al menos una apertura de rendija.")
        updated = dict(self.rendijas)
        updated.update(requested)
        self.rendijas = updated
        changed = [key for key in requested if before.get(key) != requested[key]]
        report = {"state": "confirmed" if changed else "unchanged", "requested_total_mm": dict(requested),
                  "before_mm": before, "actual_mm": dict(self.rendijas), "confirmed_moves": changed,
                  "simulado": True}
        self.ultimo_ajuste_rendijas = dict(report)
        return report

    def CancelarEspera(self):
        self._cancel.set()

    def RearmarCancelacion(self):
        self._cancel.clear()

    def Detener(self):
        self.CancelarEspera()

    def estado(self):
        return {
            "conectado": bool(self.connected),
            "inicializado": bool(self.initialized) if self.connected else None,
            "estado": "ready" if self.connected else "disconnected",
            "detalle": self.detalle,
            "indice": "SIM",
            "serie": "SIM",
            "modelo": "iHR320 simulado",
            "lambda_comandada_nm": self.posicion,
            "lambda_leida_nm": self.posicion_leida,
            "rendija_entrada_mm": self.rendijas.get("slit_in_mm"),
            "rendija_salida_mm": self.rendijas.get("slit_out_mm"),
            "red": self.red.get("nombre"),
            "red_lineas_mm": self.red.get("lineas_mm"),
            "salida_optica": self.salida_optica,
            "limites_nm": [1.0, 1500.0],
            "tolerancia_nm": 0.0,
            "ultima_lectura_utc": None,
        }

    def describe(self):
        return {"controlador": "SIM", "estado": self.estado(),
                "ultimo_ajuste_rendijas": self.ultimo_ajuste_rendijas}

    def _require_connected(self):
        if not self.connected:
            raise HoribaError("HORIBA simulado desconectado.")


class SimulatedLockIn:
    def __init__(self, bbd, mono):
        self.bbd = bbd
        self.mono = mono
        self.connected = False
        self.puerto = "SIM"
        self.numeroDeConstantesDeTiempo = 1
        self.TiempoDeIntegracionTotal = 0.03
        self.time_constant_index = 7  # 30 ms, from the real SR830 table.
        self.slope_index = 0
        self.noise = 0.01

    def AsignarPuerto(self, puerto):
        self.puerto = puerto
        self.connected = True

    def Configurar(self):
        self.connected = True

    def Identificar(self):
        return True

    def SetearNumeroDeConstantesDeIntegracion(self, numero_de_constantes):
        self.numeroDeConstantesDeTiempo = numero_de_constantes
        self.TiempoDeIntegracionTotal = settling_seconds(
            numero_de_constantes, self.ConsultarFiltro()["time_constant_seconds"]
        )

    def ConsultarFiltro(self):
        return filter_settings(self.time_constant_index, self.slope_index)

    def Adquirir(self):
        row = self.acquire_row()
        return ",".join(str(value) for value in row[:6])

    def acquire_row(self):
        posicion = float(self.bbd.posicion)
        longitud_onda = float(self.mono.posicion)
        delay = posicion * 0.21
        spectral = (longitud_onda - 650.0) / 35.0
        envelope = math.exp(-0.5 * spectral * spectral)
        oscillation = math.sin(delay) * envelope
        baseline = 0.12 * math.cos(posicion / 8.0)
        noise_x = random.uniform(-self.noise, self.noise)
        noise_y = random.uniform(-self.noise, self.noise)
        x = oscillation + baseline + noise_x
        y = math.cos(delay * 0.8) * envelope * 0.35 + noise_y
        r = math.sqrt(x * x + y * y)
        theta = math.degrees(math.atan2(y, x))
        aux = 1.0 + 0.05 * math.sin(posicion / 11.0) + 0.02 * math.cos(longitud_onda / 20.0)
        frecuencia = 1000.0 + 0.2 * math.sin(posicion / 4.0)
        return [x, y, r, theta, aux, frecuencia, posicion, longitud_onda]


class SimulatedHardwareBundle:
    def __init__(self):
        self.bbd = SimulatedBBD301()
        self.mono = SimulatedMonochromator()
        self.lockin = SimulatedLockIn(self.bbd, self.mono)

    def connect_all(self):
        self.bbd.Conectar()
        self.bbd.Home()
        self.mono.Conectar()
        self.lockin.AsignarPuerto("SIM")
        self.lockin.Configurar()

    def close(self):
        self.bbd.Cerrar()
        self.mono.CerrarPuerto()
