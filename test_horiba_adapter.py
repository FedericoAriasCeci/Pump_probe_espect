import unittest
from unittest.mock import patch

from horiba_monochromator import HoribaMonochromator, normalize_device_id


class FakeHoribaClient:
    def __init__(self):
        self.value = 0.1117
        self.closed = False

    def connect(self, device_id):
        return {"device_id": device_id, "device_name": "IHR 320", "state": "ready"}

    def status(self):
        return {"state": "ready", "busy": False}

    def wavelength(self):
        return self.value

    def move_wavelength(self, wavelength_nm):
        self.value = float(wavelength_nm)

    def close(self):
        self.closed = True


class HoribaAdapterTest(unittest.TestCase):
    def test_unconnected_monochromator_does_not_load_bridge(self):
        with patch("horiba_monochromator._load_horiba_client", side_effect=RuntimeError("bridge unavailable")) as load:
            mono = HoribaMonochromator()
            load.assert_not_called()
            self.assertFalse(mono.connected)
            with self.assertRaisesRegex(RuntimeError, "bridge unavailable"):
                mono.AsignarPuerto("Mono1")

    def test_legacy_sms_contract_uses_horiba_client(self):
        client = FakeHoribaClient()
        mono = HoribaMonochromator(client_factory=lambda: client, poll_interval_s=0)

        self.assertEqual(mono.AsignarPuerto("Mono1"), "Mono1")
        self.assertTrue(mono.Identificar())
        self.assertAlmostEqual(mono.LeerPosicion(), 0.1117)
        self.assertEqual(mono.CalcularTiempoSleep(532), 0.0)

        mono.Mover(532.0)
        self.assertAlmostEqual(mono.posicion, 532.0)

        mono.CerrarPuerto()
        self.assertTrue(client.closed)

    def test_old_com_setting_defaults_to_mono1(self):
        self.assertEqual(normalize_device_id("COM3"), "Mono1")
        self.assertEqual(normalize_device_id("3"), "Mono1")
        self.assertEqual(normalize_device_id("Mono1"), "Mono1")


if __name__ == "__main__":
    unittest.main()
