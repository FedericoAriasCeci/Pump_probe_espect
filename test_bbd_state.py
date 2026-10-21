"""Test the production BBD class without loading .NET or moving hardware."""

import ast
import os
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from acquisition_service import MeasurementConfig, validate_measurement_config


class BBDStateTest(unittest.TestCase):
    def make_bbd(self, homed):
        with open(os.path.join(os.path.dirname(__file__), "hardware_tier.py"), encoding="utf-8") as source:
            tree = ast.parse(source.read())
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BBD301")
        channel = Mock()
        channel.Position = Decimal("4.1331")
        channel.Status = SimpleNamespace(IsHomed=homed)
        channel.DeviceID = "103335944-1"
        device = Mock()
        device.GetChannel.return_value = channel
        factory = Mock()
        factory.CreateBenchtopBrushlessMotor.return_value = device
        namespace = {
            "DeviceManagerCLI": Mock(), "BenchtopBrushlessMotor": factory,
            "resolucionBBD_mm": .0001, "posicionExtremaBBD": 220,
            "velocidadBBD_mmPorSegundo": 100, "time": Mock(),
        }
        exec(compile(ast.Module(body=[definition], type_ignores=[]), "hardware_tier.py", "exec"), namespace)
        bbd = namespace["BBD301"]()
        with patch("builtins.print"):
            bbd.Conectar()
        return bbd, channel

    def test_connect_reads_position_and_homing_without_moving(self):
        for homed in (True, False):
            with self.subTest(homed=homed):
                bbd, channel = self.make_bbd(homed)
                self.assertTrue(bbd.connected)
                self.assertEqual(bbd.posicion, 4.1331)
                self.assertEqual(bbd.homed, homed)
                channel.Home.assert_not_called()
                channel.MoveTo.assert_not_called()

    def test_explicit_home_refreshes_position(self):
        bbd, channel = self.make_bbd(False)
        channel.Home.side_effect = lambda timeout: setattr(channel, "Position", Decimal("110"))
        with patch("builtins.print"):
            bbd.Home()
        self.assertTrue(bbd.homed)
        self.assertEqual(bbd.posicion, 110)

    def test_real_sweep_requires_reference_but_simulation_does_not(self):
        config = MeasurementConfig()
        config.bbd_sections = [(150, 170, 10)]
        config.use_monochromator = False
        status = {"bbd_connected": True, "bbd_homed": False, "lockin_connected": True}
        config.simulation_mode = False
        self.assertTrue(any("Home" in error for error in validate_measurement_config(config, status)))
        config.simulation_mode = True
        self.assertFalse(any("Home" in error for error in validate_measurement_config(config, status)))


if __name__ == "__main__":
    unittest.main()
