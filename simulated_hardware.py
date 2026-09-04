import math
import random


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


class SimulatedSMS:
    def __init__(self):
        self.connected = False
        self.puerto = "SIM"
        self.posicion = 650.0
        self.velocidadNmPorSegundo = 9.0
        self.resolucion = 0.3125

    def AsignarPuerto(self, puerto):
        self.puerto = puerto
        self.connected = True

    def CerrarPuerto(self):
        self.connected = False

    def Configurar(self):
        self.connected = True

    def Identificar(self):
        return True

    def Mover(self, longitud_onda_nm):
        self.posicion = float(longitud_onda_nm)

    def CalcularTiempoSleep(self, longitud_onda_nm):
        return abs(float(longitud_onda_nm) - self.posicion) / self.velocidadNmPorSegundo


class SimulatedLockIn:
    def __init__(self, bbd, mono):
        self.bbd = bbd
        self.mono = mono
        self.connected = False
        self.puerto = "SIM"
        self.numeroDeConstantesDeTiempo = 1
        self.TiempoDeIntegracionTotal = 0.05
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
        self.TiempoDeIntegracionTotal = max(0.01, 0.05 * float(numero_de_constantes))

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
        self.mono = SimulatedSMS()
        self.lockin = SimulatedLockIn(self.bbd, self.mono)

    def connect_all(self):
        self.bbd.Conectar()
        self.bbd.Home()
        self.mono.AsignarPuerto("SIM")
        self.mono.Configurar()
        self.lockin.AsignarPuerto("SIM")
        self.lockin.Configurar()

    def close(self):
        self.bbd.Cerrar()
        self.mono.CerrarPuerto()
