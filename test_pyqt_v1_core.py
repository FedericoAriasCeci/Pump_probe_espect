import json
import os
import shutil
import tempfile
import unittest

import matplotlib
matplotlib.use("Agg")

from acquisition_service import (
    MEASUREMENT_DOUBLE,
    MEASUREMENT_LAMBDA_FIXED,
    MEASUREMENT_POSITION_FIXED,
    PLOT_SCALE_LOG,
    MeasurementConfig,
    AcquisitionRunner,
    heatmap_grid_from_rows,
    save_measurement_result,
    validate_measurement_config,
)
from hardware_adapter import BaseHardwareAdapter, SimulatedHardwareAdapter, normalize_gpib_address, normalize_sms_port
from session_manager import SessionManager


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)


class SessionManagerTest(TempDirTestCase):
    def test_create_session_and_write_files(self):
        manager = SessionManager(self.temp_dir)
        first = manager.create_session()
        second = manager.create_session()

        self.assertNotEqual(first.root_path, second.root_path)
        self.assertTrue(os.path.isdir(first.root_path))
        self.assertTrue(os.path.isdir(first.plots_path))

        metadata = {"sample": "test"}
        manager.write_metadata(first, metadata)
        manager.write_notes(first, "nota de prueba")
        manager.write_log(first, ["linea 1", "linea 2"])

        self.assertTrue(os.path.isfile(first.metadata_json))
        self.assertTrue(os.path.isfile(first.notes_txt))
        self.assertTrue(os.path.isfile(first.log_txt))
        with open(first.metadata_json, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        self.assertEqual(loaded["sample"], "test")


class HardwareAdapterTest(unittest.TestCase):
    def test_normalizes_sms_port_number(self):
        self.assertEqual(normalize_sms_port("5"), "COM5")
        self.assertEqual(normalize_sms_port(" COM7 "), "COM7")
        self.assertEqual(normalize_sms_port("COM12"), "COM12")
        self.assertEqual(normalize_sms_port("SIM"), "SIM")

    def test_normalizes_gpib_address(self):
        self.assertEqual(normalize_gpib_address("8"), "GPIB0::8::INSTR")
        self.assertEqual(normalize_gpib_address(" GPIB0::8::INSTR "), "GPIB0::8::INSTR")

    def test_mono_connection_falls_back_without_dsrdtr(self):
        class FakeAddress:
            def __init__(self):
                self.is_open = False
                self.port = None
                self.dsrdtr = True

            def open(self):
                if self.dsrdtr:
                    raise Exception("Cannot configure port")
                self.is_open = True

            def close(self):
                self.is_open = False

        class FakeMono:
            def __init__(self):
                self.address = FakeAddress()
                self.puerto = None

            def AsignarPuerto(self, port):
                self.address.port = port
                self.puerto = port
                self.address.open()

        class FakeBundle:
            def __init__(self):
                self.mono = FakeMono()

        class TestAdapter(BaseHardwareAdapter):
            def _create_serial_address(self):
                return FakeAddress()

        adapter = TestAdapter(False)
        adapter.bundle = FakeBundle()
        port = adapter.connect_mono("9")
        self.assertEqual(port, "COM9")
        self.assertTrue(adapter.bundle.mono.address.is_open)
        self.assertEqual(adapter.bundle.mono.serial_profile, "sin control de lineas")

    def test_lockin_autorange_changes_only_sens(self):
        class FakeAddress:
            def __init__(self):
                self.writes = list()

            def query(self, command):
                if command == "SENS?":
                    return "20\n"
                raise Exception("Unexpected query " + command)

            def write(self, command):
                self.writes.append(command)

        class FakeLockin:
            def __init__(self):
                self.address = FakeAddress()

            def Adquirir(self):
                return "0,0,0.02,0,1,1000"

        class FakeAxis:
            posicion = 0.0

        class FakeBundle:
            def __init__(self):
                self.lockin = FakeLockin()
                self.bbd = FakeAxis()
                self.mono = FakeAxis()

        adapter = BaseHardwareAdapter(False)
        adapter.bundle = FakeBundle()
        result = adapter.autorange_lockin_sensitivity()
        self.assertTrue(result["changed"])
        self.assertEqual(adapter.bundle.lockin.address.writes, ["SENS 22"])


class ValidationTest(unittest.TestCase):
    def base_config(self):
        config = MeasurementConfig()
        config.measurement_type = MEASUREMENT_LAMBDA_FIXED
        config.bbd_sections = [(219.0, 220.0, 0.5)]
        config.lambda_sections = [(640.0, 642.0, 1.0)]
        config.channels = [1, 0, 0, 0, 0, 0]
        config.simulation_mode = True
        return config

    def test_rejects_no_channels(self):
        config = self.base_config()
        config.channels = [0, 0, 0, 0, 0, 0]
        errors = validate_measurement_config(config, {})
        self.assertTrue(any("canal" in error.lower() for error in errors))

    def test_rejects_zero_step(self):
        config = self.base_config()
        config.bbd_sections = [(219.0, 220.0, 0.0)]
        errors = validate_measurement_config(config, {})
        self.assertTrue(any("cero" in error.lower() for error in errors))

    def test_rejects_bad_step_sign(self):
        config = self.base_config()
        config.bbd_sections = [(219.0, 220.0, -0.5)]
        errors = validate_measurement_config(config, {})
        self.assertTrue(any("signo" in error.lower() for error in errors))

    def test_rejects_missing_real_hardware(self):
        config = self.base_config()
        config.simulation_mode = False
        errors = validate_measurement_config(
            config,
            {
                "bbd_connected": False,
                "mono_connected": False,
                "lockin_connected": False,
            },
        )
        self.assertTrue(any("bbd" in error.lower() for error in errors))
        self.assertTrue(any("monocromador" in error.lower() for error in errors))
        self.assertTrue(any("lock-in" in error.lower() for error in errors))

    def test_lambda_fixed_can_skip_monochromator(self):
        config = self.base_config()
        config.simulation_mode = False
        config.use_monochromator = False
        errors = validate_measurement_config(
            config,
            {
                "bbd_connected": True,
                "mono_connected": False,
                "lockin_connected": True,
            },
        )
        self.assertEqual(errors, [])

    def test_lambda_sweep_still_requires_monochromator(self):
        config = self.base_config()
        config.measurement_type = MEASUREMENT_POSITION_FIXED
        config.simulation_mode = False
        config.use_monochromator = False
        errors = validate_measurement_config(
            config,
            {
                "bbd_connected": True,
                "mono_connected": False,
                "lockin_connected": True,
            },
        )
        self.assertTrue(any("monocromador" in error.lower() for error in errors))


class SimulationRunnerTest(unittest.TestCase):
    def run_config(self, config):
        hardware = SimulatedHardwareAdapter()
        runner = AcquisitionRunner(hardware, config)
        result = runner.run()
        self.assertEqual(result.error_message, "")
        self.assertFalse(result.cancelled)
        self.assertEqual(len(result.runs), 1)
        return result

    def base_config(self):
        config = MeasurementConfig()
        config.simulation_mode = True
        config.simulation_delay_scale = 0.0
        config.integration_time_override = 0.0
        config.channels = [1, 0, 1, 0, 0, 0]
        config.plot_channels = [1, 0, 1, 0, 0, 0]
        return config

    def test_lambda_fixed_simulation(self):
        config = self.base_config()
        config.measurement_type = MEASUREMENT_LAMBDA_FIXED
        config.bbd_sections = [(219.0, 219.5, 0.25)]
        result = self.run_config(config)
        self.assertEqual(len(result.runs[0]["rows"]), 3)

    def test_lambda_fixed_without_monochromator_uses_manual_lambda(self):
        config = self.base_config()
        config.measurement_type = MEASUREMENT_LAMBDA_FIXED
        config.use_monochromator = False
        config.longitud_onda_fija_nm = 532.0
        config.bbd_sections = [(219.0, 219.25, 0.25)]
        result = self.run_config(config)
        self.assertEqual(len(result.runs[0]["rows"]), 2)
        for row in result.runs[0]["rows"]:
            self.assertEqual(row[7], 532.0)

    def test_position_fixed_simulation(self):
        config = self.base_config()
        config.measurement_type = MEASUREMENT_POSITION_FIXED
        config.lambda_sections = [(640.0, 644.0, 2.0)]
        result = self.run_config(config)
        self.assertEqual(len(result.runs[0]["rows"]), 3)

    def test_aux_average_is_updated_by_lambda(self):
        config = self.base_config()
        config.measurement_type = MEASUREMENT_POSITION_FIXED
        config.lambda_sections = [(640.0, 642.0, 2.0)]
        config.average_aux = True
        config.average_aux_seconds = 0.01
        config.simulation_delay_scale = 0.0
        config.integration_time_override = 0.0
        result = self.run_config(config)
        self.assertEqual(len(result.average_aux_by_lambda), 2)
        first_row = result.runs[0]["rows"][0]
        second_row = result.runs[0]["rows"][1]
        self.assertEqual(round(first_row[7], 6), 640.0)
        self.assertEqual(round(second_row[7], 6), 642.0)
        self.assertEqual(first_row[4], result.average_aux_by_lambda["640.0"])
        self.assertEqual(second_row[4], result.average_aux_by_lambda["642.0"])

    def test_autorange_sensitivity_runs_once_per_lambda(self):
        class CountingHardware(SimulatedHardwareAdapter):
            def __init__(self):
                SimulatedHardwareAdapter.__init__(self)
                self.autorange_calls = 0

            def autorange_lockin_sensitivity(self):
                self.autorange_calls = self.autorange_calls + 1
                return {"changed": False, "r": 0.0}

        config = self.base_config()
        config.measurement_type = MEASUREMENT_POSITION_FIXED
        config.lambda_sections = [(640.0, 644.0, 2.0)]
        config.auto_gain_enabled = True
        config.simulation_delay_scale = 0.0
        config.integration_time_override = 0.0

        hardware = CountingHardware()
        runner = AcquisitionRunner(hardware, config)
        result = runner.run()
        self.assertEqual(result.error_message, "")
        self.assertEqual(hardware.autorange_calls, 3)

    def test_double_simulation(self):
        config = self.base_config()
        config.measurement_type = MEASUREMENT_DOUBLE
        config.bbd_sections = [(219.0, 219.25, 0.25)]
        config.lambda_sections = [(640.0, 642.0, 2.0)]
        result = self.run_config(config)
        self.assertEqual(len(result.runs[0]["rows"]), 4)

    def test_double_heatmap_grid(self):
        config = self.base_config()
        config.measurement_type = MEASUREMENT_DOUBLE
        config.bbd_sections = [(219.0, 219.5, 0.25)]
        config.lambda_sections = [(640.0, 644.0, 2.0)]
        config.plot_scale = PLOT_SCALE_LOG
        result = self.run_config(config)
        x_points, lambda_points, matrix = heatmap_grid_from_rows(
            result.runs[0]["rows"],
            config,
            2,
            result.average_aux_value,
        )
        self.assertEqual(len(x_points), 3)
        self.assertEqual(len(lambda_points), 3)
        self.assertEqual(matrix.shape, (3, 3))
        self.assertFalse(matrix[0, 0] != matrix[0, 0])


class SavingTest(TempDirTestCase):
    def test_save_raw_average_metadata_notes_and_plots(self):
        config = MeasurementConfig()
        config.measurement_type = MEASUREMENT_LAMBDA_FIXED
        config.bbd_sections = [(219.0, 219.5, 0.25)]
        config.channels = [1, 0, 1, 0, 0, 0]
        config.plot_channels = [1, 0, 1, 0, 0, 0]
        config.repetitions = 2
        config.average_repetitions = True
        config.simulation_mode = True
        config.simulation_delay_scale = 0.0
        config.integration_time_override = 0.0

        hardware = SimulatedHardwareAdapter()
        runner = AcquisitionRunner(hardware, config)
        result = runner.run()
        self.assertTrue(result.average_result.get("ok", False))

        manager = SessionManager(self.temp_dir)
        paths = save_measurement_result(
            result,
            "notas",
            ["inicio", "fin"],
            [0, 2],
            manager,
        )

        self.assertTrue(os.path.isdir(paths["session_path"]))
        self.assertTrue(os.path.isfile(paths["raw_paths"][0]))
        self.assertTrue(os.path.isfile(paths["average_path"]))
        self.assertTrue(os.path.isfile(paths["metadata_path"]))
        self.assertTrue(os.path.isfile(paths["notes_path"]))
        self.assertTrue(os.path.isfile(paths["log_path"]))
        self.assertEqual(len(paths["plot_paths"]), 2)
        for path in paths["plot_paths"]:
            self.assertTrue(os.path.isfile(path))
        with open(paths["raw_paths"][0], "r", encoding="utf-8") as handle:
            raw_text = handle.read()
        self.assertIn("repeticion", raw_text)

    def test_save_double_heatmap_plot(self):
        config = MeasurementConfig()
        config.measurement_type = MEASUREMENT_DOUBLE
        config.bbd_sections = [(219.0, 219.5, 0.25)]
        config.lambda_sections = [(640.0, 644.0, 2.0)]
        config.channels = [0, 0, 1, 0, 0, 0]
        config.plot_channels = [0, 0, 1, 0, 0, 0]
        config.plot_scale = PLOT_SCALE_LOG
        config.simulation_mode = True
        config.simulation_delay_scale = 0.0
        config.integration_time_override = 0.0

        hardware = SimulatedHardwareAdapter()
        runner = AcquisitionRunner(hardware, config)
        result = runner.run()

        manager = SessionManager(self.temp_dir)
        paths = save_measurement_result(result, "", [], [2], manager)
        self.assertEqual(len(paths["plot_paths"]), 1)
        self.assertTrue(os.path.isfile(paths["plot_paths"][0]))


if __name__ == "__main__":
    unittest.main()
