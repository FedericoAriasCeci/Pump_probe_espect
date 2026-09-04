import time

from simulated_hardware import SimulatedHardwareBundle


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


def normalize_sms_port(port):
    text = str(port).strip()
    if text == "":
        return text
    upper = text.upper()
    if upper.startswith("\\\\.\\"):
        return text
    if upper.startswith("COM"):
        return upper
    if text.isdigit():
        return "COM" + text
    return text


def list_serial_ports():
    ports = list()
    try:
        from serial.tools import list_ports
        available = list_ports.comports()
    except Exception:
        return ports
    for item in available:
        device = str(getattr(item, "device", "") or "")
        description = str(getattr(item, "description", "") or "")
        hwid = str(getattr(item, "hwid", "") or "")
        ports.append(
            {
                "device": normalize_sms_port(device),
                "description": description,
                "hwid": hwid,
            }
        )
    return ports


def guess_sms_port():
    ports = list_serial_ports()
    preferred_words = ["CH340", "USB-SERIAL", "USB SERIAL", "WCH.CN", "WCH"]
    for port in ports:
        text = (
            str(port.get("device", ""))
            + " "
            + str(port.get("description", ""))
            + " "
            + str(port.get("hwid", ""))
        ).upper()
        for word in preferred_words:
            if word in text:
                return port.get("device", "")
    if len(ports) == 1:
        return ports[0].get("device", "")
    return ""


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

    def connect_bbd(self):
        self.bundle.bbd.Conectar()

    def home_bbd(self):
        self.bundle.bbd.Home()

    def _close_serial_address(self, address):
        try:
            if address is not None:
                try:
                    if hasattr(address, "reset_input_buffer"):
                        address.reset_input_buffer()
                except Exception:
                    pass
                try:
                    if hasattr(address, "reset_output_buffer"):
                        address.reset_output_buffer()
                except Exception:
                    pass
                try:
                    if hasattr(address, "setDTR"):
                        address.setDTR(False)
                except Exception:
                    pass
                try:
                    if hasattr(address, "setRTS"):
                        address.setRTS(False)
                except Exception:
                    pass
                if getattr(address, "is_open", False):
                    address.close()
        except Exception:
            pass

    def _create_serial_address(self):
        import serial

        return serial.Serial()

    def _open_fresh_mono_serial(self, mono, normalized_port, profile_name, settings):
        address = self._create_serial_address()
        address.port = normalized_port
        for key in settings:
            try:
                setattr(address, key, settings[key])
            except Exception:
                pass
        try:
            address.open()
        except Exception:
            self._close_serial_address(address)
            raise
        mono.address = address
        mono.puerto = normalized_port
        setattr(mono, "serial_profile", profile_name)
        return normalized_port

    def connect_mono(self, port):
        normalized_port = normalize_sms_port(port)
        mono = self.bundle.mono
        address = getattr(self.bundle.mono, "address", None)
        if address is not None:
            try:
                if getattr(address, "is_open", False):
                    if normalize_sms_port(getattr(address, "port", "")) == normalized_port:
                        return normalized_port
                    address.close()
            except Exception:
                pass

        attempts = list()
        try:
            mono.AsignarPuerto(normalized_port)
            setattr(mono, "serial_profile", "heredado")
            return normalized_port
        except Exception as first_exc:
            attempts.append(("heredado", first_exc))
            self._close_serial_address(getattr(mono, "address", None))

        profiles = [
            (
                "minimo",
                {
                    "baudrate": 9600,
                    "timeout": 3,
                    "write_timeout": 3,
                },
            ),
            (
                "sin control de lineas",
                {
                    "baudrate": 9600,
                    "bytesize": 8,
                    "stopbits": 1,
                    "parity": "N",
                    "timeout": 3,
                    "write_timeout": 3,
                    "xonxoff": False,
                    "rtscts": False,
                    "dsrdtr": False,
                    "dtr": False,
                    "rts": False,
                },
            ),
        ]
        for profile_name, settings in profiles:
            try:
                return self._open_fresh_mono_serial(mono, normalized_port, profile_name, settings)
            except Exception as exc:
                attempts.append((profile_name, exc))

        parts = ["No se pudo abrir " + str(normalized_port) + "."]
        for profile_name, exc in attempts:
            parts.append("Perfil " + str(profile_name) + ": " + str(exc))
        parts.append("Sugerencias: cerrar otros programas que puedan usar el puerto, reconectar el USB, probar otro cable/puerto USB, o reinstalar el driver CH340.")
        raise Exception(" ".join(parts))

    def identify_mono(self):
        if hasattr(self.bundle.mono, "Identificar"):
            return bool(self.bundle.mono.Identificar())
        return True

    def close_mono(self):
        mono = self.bundle.mono
        address = getattr(mono, "address", None)
        self._close_serial_address(address)
        if hasattr(mono, "connected"):
            mono.connected = False

    def configure_mono(self):
        self.bundle.mono.Configurar()

    def connect_lockin(self, port):
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
        self.bundle.lockin.SetearNumeroDeConstantesDeIntegracion(constants)

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
        bbd = self.bundle.bbd
        mono = self.bundle.mono
        lockin = self.bundle.lockin
        mono_connected = getattr(mono, "connected", False)
        if not mono_connected and hasattr(mono, "address"):
            try:
                mono_connected = bool(mono.address.is_open)
            except Exception:
                mono_connected = False
        lockin_connected = getattr(lockin, "connected", False)
        if not lockin_connected:
            address = getattr(lockin, "address", None)
            lockin_connected = address is not None
        return {
            "bbd_connected": bool(getattr(bbd, "connected", False)),
            "bbd_homed": bool(getattr(bbd, "homed", False)),
            "bbd_position": float(getattr(bbd, "posicion", 0.0)),
            "mono_connected": bool(mono_connected),
            "mono_position": float(getattr(mono, "posicion", 0.0)),
            "lockin_connected": bool(lockin_connected),
            "integration_time": self.integration_time(),
            "simulation_mode": self.simulation_mode,
        }


class SimulatedHardwareAdapter(BaseHardwareAdapter):
    def __init__(self):
        BaseHardwareAdapter.__init__(self, True)
        self.bundle = SimulatedHardwareBundle()
        self.bundle.connect_all()


class RealHardwareBundle:
    def __init__(self):
        from hardware_tier import BBD301, SMS, LockIn

        self.bbd = BBD301()
        self.mono = SMS()
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
            address = getattr(self.mono, "address", None)
            if address is not None and getattr(address, "is_open", False):
                address.close()
        except Exception:
            pass
        try:
            address = getattr(self.lockin, "address", None)
            if address is not None and hasattr(address, "close"):
                address.close()
        except Exception:
            pass


class RealHardwareAdapter(BaseHardwareAdapter):
    def __init__(self):
        BaseHardwareAdapter.__init__(self, False)
        self.bundle = RealHardwareBundle()


def create_hardware_adapter(simulation_mode):
    if simulation_mode:
        return SimulatedHardwareAdapter()
    return RealHardwareAdapter()
