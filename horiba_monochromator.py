"""Adapter that presents the legacy SMS API on top of HoribaBridge.exe.

The measurement code only needs a monochromator with ``Mover()``,
``LeerPosicion()`` and ``CalcularTiempoSleep()``.  This module keeps that
contract while running the 32-bit .NET/COM bridge in a separate process, so
the Pump-Probe application itself may use either 32- or 64-bit Python.
"""

import os
import sys
import time


DEFAULT_DEVICE_ID = "Mono1"


def _load_horiba_client():
    bridge_directory = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "HoribaBridge")
    )
    if bridge_directory not in sys.path:
        sys.path.insert(0, bridge_directory)
    try:
        from horiba import Horiba
    except Exception as exc:
        raise RuntimeError(
            "No se pudo cargar el cliente Horiba. Primero compile "
            + os.path.join(bridge_directory, "build.ps1")
            + ". Detalle: "
            + str(exc)
        )
    return Horiba


def normalize_device_id(value):
    """Accept old COM-number settings while defaulting them to the iHR320."""
    text = str(value or "").strip()
    if text == "" or text.upper().startswith("COM") or text.isdigit():
        return DEFAULT_DEVICE_ID
    return text


class HoribaMonochromator:
    """iHR320 driver compatible with the methods used by the existing GUI."""

    def __init__(self, client_factory=None, motion_timeout_s=180.0, poll_interval_s=0.10):
        # BBD-only measurements must not require the bridge to be installed.
        # Resolve it only when the monochromator is actually connected.
        self._client_factory = client_factory
        self._client = None
        self.motion_timeout_s = float(motion_timeout_s)
        self.poll_interval_s = float(poll_interval_s)
        self.connected = False
        self.puerto = DEFAULT_DEVICE_ID  # Legacy name retained for CSV metadata.
        self.device_id = DEFAULT_DEVICE_ID
        self.device_name = ""
        self.posicion = 0.0
        self.velocidadNmPorSegundo = 0.0
        self.resolucion = None

    def AsignarPuerto(self, device_id):
        """Legacy entry point. ``device_id`` is normally ``Mono1``, not a COM port."""
        self.CerrarPuerto()
        self.device_id = normalize_device_id(device_id)
        self.puerto = self.device_id
        factory = self._client_factory or _load_horiba_client()
        self._client = factory()
        try:
            info = self._client.connect(self.device_id)
            self.connected = True
            self.device_id = str(info.get("device_id") or self.device_id)
            self.puerto = self.device_id
            self.device_name = str(info.get("device_name") or "")
            self.posicion = float(self._client.wavelength())
            return self.device_id
        except Exception:
            self.CerrarPuerto()
            raise

    def CerrarPuerto(self):
        client = self._client
        self._client = None
        self.connected = False
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    def Configurar(self):
        """The bridge already performed Load/OpenCommunications/Initialize."""
        self._require_connected()
        self.posicion = self.LeerPosicion()

    def Identificar(self):
        if not self.connected or self._client is None:
            return False
        try:
            status = self._client.status()
            return status.get("state") == "ready"
        except Exception:
            self.connected = False
            return False

    def LeerPosicion(self):
        self._require_connected()
        self.posicion = float(self._client.wavelength())
        return self.posicion

    def Mover(self, longitud_onda_nm):
        """Move to a wavelength and wait until the SDK reports it is idle."""
        self._require_connected()
        target = float(longitud_onda_nm)
        self._client.move_wavelength(target)
        self._wait_for_motion(target)
        return self.posicion

    def CalcularTiempoSleep(self, longitud_onda_nm):
        # Mover() waits on the Horiba SDK's IsBusy state, which is safer than a
        # fixed-speed estimate. Existing acquisition loops can therefore keep
        # their call unchanged and sleep for zero additional seconds.
        return 0.0

    def Calibrar(self):
        raise RuntimeError("La calibracion del iHR320 debe hacerse desde SinerJY; no se expone como comando de medicion.")

    def CambiarVelocidad(self, velocidad):
        raise RuntimeError("La velocidad del iHR320 no se configura desde esta interfaz.")

    def CambiarRed(self, grating):
        raise RuntimeError("Seleccione la torreta/red del iHR320 en SinerJY antes de medir.")

    def _require_connected(self):
        if not self.connected or self._client is None:
            raise RuntimeError("HORIBA iHR320 no conectado. Use Conectar con el ID Mono1.")

    def _wait_for_motion(self, target):
        deadline = time.monotonic() + self.motion_timeout_s
        while True:
            status = self._client.status()
            if status.get("state") != "ready":
                raise RuntimeError("El iHR320 dejo de estar listo: " + str(status))
            current = float(self._client.wavelength())
            busy = bool(status.get("busy", False))
            if not busy and abs(current - target) <= 0.001:
                self.posicion = current
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "El iHR320 no termino el movimiento a " + str(target) + " nm en " + str(self.motion_timeout_s) + " s."
                )
            time.sleep(self.poll_interval_s)
