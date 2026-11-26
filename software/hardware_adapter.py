import time

from simulated_hardware import SimulatedHardwareBundle
from sr830_timing import query_filter_settings, settling_seconds


SR830_SENSITIVITY_VALUES = [
    2e-9,
    5e-9,
    10e-9,
    20e-9,
    50e-9,
    100e-9,
    200e-9,
    500e-9,
    1e-6,
    2e-6,
    5e-6,
    10e-6,
    20e-6,
    50e-6,
    100e-6,
    200e-6,
    500e-6,
    1e-3,
    2e-3,
    5e-3,
    10e-3,
    20e-3,
    50e-3,
    100e-3,
    200e-3,
    500e-3,
    1.0,
]


def normalize_gpib_address(port):
    text = str(port).strip()
    upper = text.upper()
    if upper.startswith("GPIB"):
        return upper
    return "GPIB0::" + text + "::INSTR"


def list_visa_resources():
    try:
        import pyvisa

        manager = pyvisa.ResourceManager()
        resources = manager.list_resources()
        return [str(resource) for resource in resources]
    except Exception:
        return list()


class BaseHardwareAdapter:
    def __init__(self, simulation_mode=False):
        self.simulation_mode = simulation_mode
        self._lockin_filter = None

    def connect_bbd(self):
        self.bundle.bbd.Conectar()

    def home_bbd(self):
        self.bundle.bbd.Home()

    # ------------------------------------------------------------ HORIBA iHR320
    # Todas estas llamadas pueden tardar (ICL, homing, motores): usarlas desde
    # un hilo de trabajo. cancel_mono_wait() es la unica segura desde la GUI.
    def connect_mono(self, index=None):
        return self.bundle.mono.Conectar(index)

    def initialize_mono(self):
        return self.bundle.mono.Inicializar()

    def read_mono_state(self):
        return self.bundle.mono.LeerEstado()

    def apply_mono_slits(self, entrance_mm=None, exit_mm=None):
        return self.bundle.mono.AjustarRendijas(entrance_mm, exit_mm)

    def cancel_mono_wait(self):
        try:
            self.bundle.mono.CancelarEspera()
        except Exception:
            pass

    def reset_mono_cancel(self):
        self.bundle.mono.RearmarCancelacion()

    def identify_mono(self):
        return bool(self.bundle.mono.Identificar())

    def close_mono(self):
        self.bundle.mono.CerrarPuerto()

    def set_mono_tolerance(self, tolerance_nm):
        """Diferencia maxima entre lambda pedida y leida; rige desde el proximo movimiento."""
        settings = getattr(self.bundle.mono, "settings", None)
        if settings is None:
            return  # Simulador: no hay diferencia entre pedida y leida.
        value = float(tolerance_nm)
        if not value > 0:
            raise ValueError("La tolerancia de lambda debe ser mayor que 0 nm.")
        settings.tolerance_nm = value

    def mono_state(self):
        """Ultimo estado conocido del iHR320, sin comunicacion."""
        mono = self.bundle.mono
        if hasattr(mono, "estado"):
            return dict(mono.estado())
        return {"conectado": bool(getattr(mono, "connected", False))}

    def mono_description(self):
        mono = self.bundle.mono
        if hasattr(mono, "describe"):
            return mono.describe()
        return {}

    def mono_read_wavelength(self):
        value = getattr(self.bundle.mono, "posicion_leida", None)
        if value is None:
            return float("nan")
        return float(value)

    def connect_lockin(self, port):
        self._lockin_filter = None
        lockin = self.bundle.lockin
        address = getattr(lockin, "address", None)
        try:
            if address is not None and hasattr(address, "close"):
                address.close()
        except Exception:
            pass
        try:
            if hasattr(lockin, "address"):
                delattr(lockin, "address")
        except Exception:
            pass
        port_text = str(port).strip()
        if self.simulation_mode or port_text.upper() == "SIM":
            self.bundle.lockin.AsignarPuerto(port_text)
            self.prepare_lockin_resource()
            return port_text
        resource_name = normalize_gpib_address(port_text)
        try:
            import pyvisa

            manager = pyvisa.ResourceManager()
            resource = manager.open_resource(resource_name, open_timeout=5000)
            lockin.address = resource
            lockin.puerto = port_text
            lockin.resource_name = resource_name
            lockin.resource_manager = manager
            self.prepare_lockin_resource()
            return port_text
        except Exception as exc:
            resources = list_visa_resources()
            message = "No se pudo abrir " + resource_name + ": " + str(exc)
            if len(resources) > 0:
                message = message + ". Recursos VISA detectados: " + ", ".join(resources)
            else:
                message = message + ". No pude listar recursos VISA."
            raise Exception(message)

    def prepare_lockin_resource(self):
        address = getattr(self.bundle.lockin, "address", None)
        if address is None:
            return
        for key, value in (
            ("timeout", 5000),
            ("read_termination", "\n"),
            ("write_termination", ""),
        ):
            try:
                setattr(address, key, value)
            except Exception:
                pass

    def identify_lockin(self):
        if hasattr(self.bundle.lockin, "Identificar"):
            return bool(self.bundle.lockin.Identificar())
        return True

    def configure_lockin(self):
        self.bundle.lockin.Configurar()

    def set_lockin_constants(self, constants):
        # Software delay only: no instrument I/O from this UI-facing method.
        constants = float(constants)
        settling_seconds(constants, 1.0)
        self.bundle.lockin.numeroDeConstantesDeTiempo = constants
        if self._lockin_filter is not None:
            self.bundle.lockin.TiempoDeIntegracionTotal = settling_seconds(
                constants, self._lockin_filter["time_constant_seconds"]
            )

    def refresh_lockin_filter(self):
        lockin = self.bundle.lockin
        try:
            if hasattr(lockin, "ConsultarFiltro"):
                settings = lockin.ConsultarFiltro()
            else:
                settings = query_filter_settings(lockin.address)
            seconds = settling_seconds(
                getattr(lockin, "numeroDeConstantesDeTiempo", settings["recommended_settling_factor"]),
                settings["time_constant_seconds"],
            )
        except Exception as exc:
            self._lockin_filter = None
            lockin.TiempoDeIntegracionTotal = 0.0
            raise RuntimeError("No se pudo consultar el filtro del SR830: " + str(exc)) from exc
        self._lockin_filter = dict(settings)
        lockin.TiempoDeIntegracionTotal = seconds
        return dict(settings)

    def auto_gain_lockin(self):
        return self.autorange_lockin_sensitivity()

    def query_lockin_sensitivity_index(self):
        address = getattr(self.bundle.lockin, "address", None)
        if address is None:
            raise Exception("Lock-in no conectado")
        value = address.query("SENS?")
        return int(str(value).strip())

    def set_lockin_sensitivity_index(self, index):
        address = getattr(self.bundle.lockin, "address", None)
        if address is None:
            raise Exception("Lock-in no conectado")
        index = int(index)
        if index < 0:
            index = 0
        if index >= len(SR830_SENSITIVITY_VALUES):
            index = len(SR830_SENSITIVITY_VALUES) - 1
        address.write("SENS " + str(index))
        return index

    def autorange_lockin_sensitivity(self):
        if self.simulation_mode:
            return {
                "changed": False,
                "old_index": None,
                "new_index": None,
                "r": 0.0,
                "reason": "simulacion",
            }
        old_index = self.query_lockin_sensitivity_index()
        if old_index < 0:
            old_index = 0
        if old_index >= len(SR830_SENSITIVITY_VALUES):
            old_index = len(SR830_SENSITIVITY_VALUES) - 1
        row = self.acquire_row()
        r_value = abs(float(row[2]))
        new_index = old_index
        high_fraction = 0.85
        low_fraction = 0.08

        while (
            new_index < len(SR830_SENSITIVITY_VALUES) - 1
            and r_value > high_fraction * SR830_SENSITIVITY_VALUES[new_index]
        ):
            new_index = new_index + 1

        while (
            new_index > 0
            and r_value < low_fraction * SR830_SENSITIVITY_VALUES[new_index]
            and r_value < high_fraction * SR830_SENSITIVITY_VALUES[new_index - 1]
        ):
            new_index = new_index - 1

        if new_index != old_index:
            self.set_lockin_sensitivity_index(new_index)
            return {
                "changed": True,
                "old_index": old_index,
                "new_index": new_index,
                "r": r_value,
                "old_scale": SR830_SENSITIVITY_VALUES[old_index],
                "new_scale": SR830_SENSITIVITY_VALUES[new_index],
            }
        return {
            "changed": False,
            "old_index": old_index,
            "new_index": new_index,
            "r": r_value,
            "old_scale": SR830_SENSITIVITY_VALUES[old_index],
            "new_scale": SR830_SENSITIVITY_VALUES[new_index],
        }

    def move_bbd(self, position_mm):
        self.bundle.bbd.Mover(position_mm)

    def move_mono(self, wavelength_nm):
        self.bundle.mono.Mover(wavelength_nm)

    def calculate_bbd_sleep(self, position_mm):
        return self.bundle.bbd.CalcularTiempoSleep(position_mm)

    def calculate_mono_sleep(self, wavelength_nm):
        return self.bundle.mono.CalcularTiempoSleep(wavelength_nm)

    def integration_time(self):
        return float(getattr(self.bundle.lockin, "TiempoDeIntegracionTotal", 0.0))

    def stop_all(self):
        try:
            self.bundle.bbd.Detener()
        except Exception:
            pass
        # El iHR320 no expone una parada: se abandona la espera de ICL.
        self.cancel_mono_wait()

    def close_bbd(self):
        bbd = self.bundle.bbd
        try:
            if hasattr(bbd, "Detener"):
                bbd.Detener()
        except Exception:
            pass
        try:
            if hasattr(bbd, "Cerrar"):
                bbd.Cerrar()
        except Exception:
            pass
        try:
            if hasattr(bbd, "connected"):
                bbd.connected = False
        except Exception:
            pass

    def close_lockin(self):
        self._lockin_filter = None
        lockin = self.bundle.lockin
        address = getattr(lockin, "address", None)
        try:
            if address is not None and hasattr(address, "write"):
                address.write("LOCL0")
        except Exception:
            pass
        try:
            if address is not None and hasattr(address, "close"):
                address.close()
        except Exception:
            pass
        try:
            if hasattr(lockin, "address"):
                delattr(lockin, "address")
        except Exception:
            pass
        try:
            if hasattr(lockin, "connected"):
                lockin.connected = False
        except Exception:
            pass

    def close(self):
        try:
            self.stop_all()
        except Exception:
            pass
        try:
            self.close_lockin()
        except Exception:
            pass
        try:
            self.close_mono()
        except Exception:
            pass
        try:
            self.close_bbd()
        except Exception:
            pass
        try:
            self.bundle.close()
        except Exception:
            pass

    def acquire_row(self):
        if hasattr(self.bundle.lockin, "acquire_row"):
            return self.bundle.lockin.acquire_row()
        last_error = None
        for attempt in range(0, 4):
            try:
                raw = self.bundle.lockin.Adquirir()
                parts = raw.split(",")
                if len(parts) < 6:
                    raise Exception("Respuesta incompleta del Lock-in: " + str(raw))
                row = [float(value) for value in parts[:6]]
                row.append(float(self.bundle.bbd.posicion))
                row.append(float(self.bundle.mono.posicion))
                return row
            except Exception as exc:
                last_error = exc
                address = getattr(self.bundle.lockin, "address", None)
                try:
                    if address is not None and hasattr(address, "clear"):
                        address.clear()
                except Exception:
                    pass
                time.sleep(0.25 + 0.25 * attempt)
        raise Exception("No se pudo leer el Lock-in despues de reintentos: " + str(last_error))

    def status(self):
        """Estado en cache, sin E/S: se llama desde la GUI durante la medicion."""
        bbd = self.bundle.bbd
        mono = self.bundle.mono
        lockin = self.bundle.lockin
        mono_state = self.mono_state()
        mono_read = mono_state.get("lambda_leida_nm")
        lockin_connected = getattr(lockin, "connected", False)
        if not lockin_connected:
            address = getattr(lockin, "address", None)
            lockin_connected = address is not None
        return {
            "bbd_connected": bool(getattr(bbd, "connected", False)),
            "bbd_homed": bool(getattr(bbd, "homed", False)),
            "bbd_position": float(getattr(bbd, "posicion", 0.0)),
            "mono_connected": bool(mono_state.get("conectado", False)),
            "mono_initialized": mono_state.get("inicializado"),
            "mono_position": float(mono_read if mono_read is not None else getattr(mono, "posicion", 0.0)),
            "mono_commanded_nm": mono_state.get("lambda_comandada_nm"),
            "mono_read_nm": mono_read,
            "mono_slit_entrance_mm": mono_state.get("rendija_entrada_mm"),
            "mono_slit_exit_mm": mono_state.get("rendija_salida_mm"),
            "mono_grating": mono_state.get("red"),
            "mono_grating_grooves_mm": mono_state.get("red_lineas_mm"),
            "mono_output": mono_state.get("salida_optica"),
            "mono_limits_nm": mono_state.get("limites_nm"),
            "mono_state": mono_state.get("estado"),
            "mono_detail": mono_state.get("detalle"),
            "mono_index": mono_state.get("indice"),
            "mono_serial": mono_state.get("serie"),
            "lockin_connected": bool(lockin_connected),
            "integration_time": self.integration_time(),
            "lockin_filter": dict(self._lockin_filter) if self._lockin_filter is not None else None,
            "simulation_mode": self.simulation_mode,
        }


class SimulatedHardwareAdapter(BaseHardwareAdapter):
    def __init__(self):
        BaseHardwareAdapter.__init__(self, True)
        self.bundle = SimulatedHardwareBundle()
        self.bundle.connect_all()
        self.refresh_lockin_filter()


class RealHardwareBundle:
    def __init__(self, horiba_settings=None):
        from hardware_tier import BBD301, LockIn
        from horiba_monochromator import HoribaMonochromator

        self.bbd = BBD301()
        self.mono = HoribaMonochromator(horiba_settings)
        self.lockin = LockIn()

    def close(self):
        try:
            if hasattr(self.bbd, "Detener"):
                self.bbd.Detener()
        except Exception:
            pass
        try:
            if hasattr(self.bbd, "Cerrar"):
                self.bbd.Cerrar()
        except Exception:
            pass
        try:
            self.mono.CerrarPuerto()
        except Exception:
            pass
        try:
            address = getattr(self.lockin, "address", None)
            if address is not None and hasattr(address, "close"):
                address.close()
        except Exception:
            pass


class RealHardwareAdapter(BaseHardwareAdapter):
    def __init__(self, horiba_settings=None):
        BaseHardwareAdapter.__init__(self, False)
        self.bundle = RealHardwareBundle(horiba_settings)


def create_hardware_adapter(simulation_mode, horiba_settings=None):
    if simulation_mode:
        return SimulatedHardwareAdapter()
    return RealHardwareAdapter(horiba_settings)
