"""Timing and acquisition tests without VISA, .NET or laboratory hardware."""

import ast
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from acquisition_service import (
    AcquisitionRunner, MeasurementConfig, MeasurementResult,
    MEASUREMENT_LAMBDA_FIXED, MEASUREMENT_POSITION_FIXED, MEASUREMENT_DOUBLE,
    estimate_seconds, validate_measurement_config,
)
from hardware_adapter import BaseHardwareAdapter, SimulatedHardwareAdapter
from sr830_timing import (
    filter_settings, query_filter_settings, settling_seconds, time_constant_seconds,
)


class SR830ParametersTest(unittest.TestCase):
    def test_real_driver_preserves_filter_and_queries_all_indices(self):
        # Load the actual driver class without importing the Thorlabs/.NET stack.
        # Instrument I/O and configuration sleeps are replaced with mocks.
        path = os.path.join(os.path.dirname(__file__), "hardware_tier.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        lockin_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LockIn")
        namespace = {
            "time": Mock(), "time_constant_seconds": time_constant_seconds,
            "query_filter_settings": query_filter_settings, "settling_seconds": settling_seconds,
        }
        exec(compile(ast.Module(body=[lockin_class], type_ignores=[]), path, "exec"), namespace)
        lockin = namespace["LockIn"]()
        address = Mock()
        address.query.return_value = "10\n"
        lockin.address = address
        lockin.Configurar()
        writes = [call[0][0] for call in address.write.call_args_list]
        self.assertIn("FMOD0", writes)  # Keep existing reference/input setup.
        self.assertFalse(any(command.startswith(("OFLT", "OFSL")) for command in writes))
        address.query.side_effect = ["11\n", "3\n"]
        self.assertEqual(lockin.ConsultarFiltro(), filter_settings(11, 3))
        address.query.side_effect = None
        for index in range(20):
            address.query.return_value = str(index)
            self.assertEqual(lockin.ConstanteDeIntegracion(), time_constant_seconds(index))

    def test_all_twenty_time_constants_in_seconds(self):
        expected = [
            .00001, .00003, .0001, .0003, .001, .003, .01, .03, .1, .3,
            1, 3, 10, 30, 100, 300, 1000, 3000, 10000, 30000,
        ]
        for index, seconds in enumerate(expected):
            with self.subTest(index=index):
                self.assertEqual(time_constant_seconds(str(index) + "\r\n"), seconds)

    def test_slopes_and_total_recommended_factors(self):
        for index, slope, factor in [(0, 6, 5), (1, 12, 7), (2, 18, 9), (3, 24, 10)]:
            with self.subTest(slope=slope):
                settings = filter_settings(9, index)
                self.assertEqual(settings["slope_db_oct"], slope)
                self.assertEqual(settings["recommended_settling_factor"], factor)
                self.assertAlmostEqual(settling_seconds(factor, .3), factor * .3)

    def test_manual_fractional_factor_is_not_multiplied_by_filter_order(self):
        for slope_index in range(4):
            settings = filter_settings(11, slope_index)
            self.assertEqual(settling_seconds(2.5, settings["time_constant_seconds"]), 7.5)

    def test_invalid_responses_and_nonpositive_or_nonfinite_times(self):
        for invalid in [-1, 20, "", "bad", "1.5", "nan", None]:
            with self.subTest(oflt=invalid), self.assertRaises(ValueError):
                time_constant_seconds(invalid)
        for invalid in [-1, 4, "0.5", ""]:
            with self.subTest(ofsl=invalid), self.assertRaises(ValueError):
                filter_settings(0, invalid)
        for invalid in [0, -1, float("nan"), float("inf")]:
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    settling_seconds(invalid, 1)
                with self.assertRaises(ValueError):
                    settling_seconds(5, invalid)

    def test_query_is_read_only_and_status_uses_cache(self):
        address = Mock()
        address.query.side_effect = ["10\n", "3\n"]
        adapter = BaseHardwareAdapter(False)
        adapter.bundle = SimpleNamespace(
            lockin=SimpleNamespace(address=address),
            bbd=SimpleNamespace(), mono=SimpleNamespace(),
        )
        settings = adapter.refresh_lockin_filter()
        adapter.set_lockin_constants(2.5)
        self.assertEqual(settings, filter_settings(10, 3))
        self.assertEqual(adapter.status()["integration_time"], 2.5)
        self.assertEqual([call[0][0] for call in address.query.call_args_list], ["OFLT?", "OFSL?"])
        address.write.assert_not_called()

    def test_query_failure_never_uses_a_stale_filter(self):
        hardware = SimulatedHardwareAdapter()
        with patch.object(hardware.bundle.lockin, "ConsultarFiltro", side_effect=TimeoutError("VISA timeout")):
            with self.assertRaisesRegex(RuntimeError, "VISA timeout"):
                hardware.refresh_lockin_filter()
        self.assertIsNone(hardware.status()["lockin_filter"])


class RecordingHardware(SimulatedHardwareAdapter):
    def __init__(self):
        self.events = []
        super().__init__()
        self.bundle.lockin.time_constant_index = 10  # tau = 1 s
        self.change_gain = False
        self.events.clear()

    def refresh_lockin_filter(self):
        self.events.append("filter")
        return super().refresh_lockin_filter()

    def move_bbd(self, position):
        super().move_bbd(position)
        self.events.append(("bbd_done", position))

    def move_mono(self, wavelength):
        super().move_mono(wavelength)
        self.events.append(("mono_done", wavelength))

    def calculate_bbd_sleep(self, position):
        return 3.0  # Distinct mechanical margin, deliberately unlike N*tau.

    def calculate_mono_sleep(self, wavelength):
        return 2.0

    def acquire_row(self):
        self.events.append("acquire")
        return super().acquire_row()

    def autorange_lockin_sensitivity(self):
        self.events.append("autorange")
        self.acquire_row()  # Real autorange also needs a settled SNAP reading.
        if self.change_gain:
            self.events.append("sens_changed")
        return {"changed": self.change_gain}


class SettlingSequenceTest(unittest.TestCase):
    def make_runner(self):
        hardware = RecordingHardware()
        config = MeasurementConfig()
        config.auto_gain_enabled = False
        config.average_aux = False  # These tests isolate filter settling from DC sampling.
        config.lockin_settling_factor = 4.5
        config.bbd_sections = [(219.0, 220.0, 1.0)]
        config.lambda_sections = [(640.0, 642.0, 2.0)]
        runner = AcquisitionRunner(hardware, config)
        runner.sleep_cancellable = lambda seconds: hardware.events.append(("sleep", seconds)) or True
        return runner, hardware, config

    def test_each_point_waits_after_motion_and_mechanical_margin_in_all_modes(self):
        for mode, count in [(MEASUREMENT_LAMBDA_FIXED, 2), (MEASUREMENT_POSITION_FIXED, 2), (MEASUREMENT_DOUBLE, 4)]:
            with self.subTest(mode=mode):
                runner, hardware, config = self.make_runner()
                config.measurement_type = mode
                result = runner.run()
                self.assertEqual(result.error_message, "")
                self.assertEqual(result.acquired_points, count)
                for index, event in enumerate(hardware.events):
                    if event == "acquire":
                        self.assertEqual(hardware.events[index - 4:index], [
                            ("sleep", 2.0 if mode == MEASUREMENT_POSITION_FIXED else 3.0),
                            "filter", ("sleep", 4.5), "filter",
                        ])
                        self.assertIn(hardware.events[index - 5][0], ["mono_done", "bbd_done"])

    def test_filter_change_during_wait_restarts_using_actual_tau_and_slope(self):
        for manual, expected in [(None, [5.0, 30.0]), (2.5, [2.5, 7.5])]:
            with self.subTest(manual=manual):
                runner, hardware, config = self.make_runner()
                config.lockin_settling_factor = manual
                waits = []

                def wait(seconds):
                    waits.append(seconds)
                    hardware.bundle.lockin.time_constant_index = 11  # 3 s
                    hardware.bundle.lockin.slope_index = 3
                    return True

                runner.sleep_cancellable = wait
                self.assertTrue(runner.wait_for_lockin())
                self.assertEqual(waits, expected)
                self.assertEqual(config.lockin_settling_factor, manual)
                self.assertNotIn("acquire", hardware.events)

    def test_filter_change_between_points_updates_timing_and_metadata(self):
        runner, hardware, config = self.make_runner()
        config.lockin_settling_factor = None

        def point(*args):
            hardware.bundle.lockin.slope_index = 2
            hardware.bundle.lockin.time_constant_index = 11

        runner.callbacks["point"] = point
        result = runner.run()
        self.assertEqual(result.error_message, "")
        waits = [event[1] for event in hardware.events if isinstance(event, tuple) and event[0] == "sleep"]
        self.assertEqual(waits, [2.0, 3.0, 5.0, 3.0, 27.0])
        history = result.metadata["lockin_filter_history"]
        self.assertEqual([item["settling_factor"] for item in history], [5.0, 9.0])
        self.assertIsNone(result.metadata["config"]["lockin_settling_factor"])

    def test_autorange_and_final_read_reuse_settling_unless_sensitivity_changes(self):
        for changed, expected_waits in [(False, 1), (True, 2)]:
            with self.subTest(sensitivity_changed=changed):
                runner, hardware, config = self.make_runner()
                config.auto_gain_enabled = True
                hardware.change_gain = changed
                result = MeasurementResult(config)
                self.assertTrue(runner.maybe_auto_gain_for_lambda(650))
                self.assertTrue(runner.acquire_point(result, 1, 0, 1))
                waits = [i for i, event in enumerate(hardware.events) if event == ("sleep", 4.5)]
                self.assertEqual(len(waits), expected_waits)
                self.assertLess(waits[0], hardware.events.index("autorange"))
                if changed:
                    self.assertLess(hardware.events.index("sens_changed"), waits[1])
                    self.assertLess(waits[1], len(hardware.events) - 1)

    def test_filter_communication_error_stops_and_keeps_completed_points(self):
        runner, hardware, config = self.make_runner()
        with patch.object(hardware.bundle.lockin, "ConsultarFiltro", side_effect=[
            filter_settings(10, 0), filter_settings(10, 0), TimeoutError("VISA timeout"),
        ]):
            result = runner.run()
        self.assertIn("VISA timeout", result.error_message)
        self.assertEqual(result.acquired_points, 1)
        self.assertEqual(len(result.runs[0]["rows"]), 1)
        self.assertEqual(hardware.events.count("acquire"), 1)

    def test_cancel_interrupts_a_long_wait_before_any_signal_is_read(self):
        hardware = SimulatedHardwareAdapter()
        config = MeasurementConfig()
        config.bbd_sections = [(219, 220, 1)]
        config.auto_gain_enabled = False
        config.simulation_delay_scale = 1.0
        config.lockin_settling_factor = 10000  # 300 s, without actually waiting.
        waiting = threading.Event()
        runner = AcquisitionRunner(hardware, config, {
            "status": lambda message: waiting.set() if message.startswith("Estabilizando") else None,
        })
        results = []
        thread = threading.Thread(target=lambda: results.append(runner.run()))
        thread.start()
        try:
            self.assertTrue(waiting.wait(2))
        finally:
            runner.cancel()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertTrue(results[0].cancelled)
        self.assertEqual(results[0].acquired_points, 0)

    def test_real_hardware_cannot_bypass_wait_with_test_override(self):
        runner, hardware, config = self.make_runner()
        config.simulation_mode = False
        config.integration_time_override = 0
        self.assertTrue(any("simulacion" in error for error in validate_measurement_config(config, hardware.status())))
        result = runner.run()
        self.assertIn("simulacion", result.error_message)
        self.assertEqual(result.acquired_points, 0)

    def test_preview_uses_current_factor_and_real_tau(self):
        runner, hardware, config = self.make_runner()
        hardware.refresh_lockin_filter()
        config.simulation_mode = False
        seconds = estimate_seconds(config, hardware.status())
        self.assertAlmostEqual(seconds, 2 * 4.5 + .1)

    def test_simulation_scale_cannot_shorten_a_real_hardware_wait(self):
        runner, hardware, config = self.make_runner()
        hardware.simulation_mode = False
        config.simulation_delay_scale = 0
        # A monotonic clock advances with each simulated sleep; no wall time.
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        with patch("acquisition_service.time.monotonic", side_effect=lambda: clock[0]), patch("acquisition_service.time.sleep", side_effect=sleep):
            self.assertTrue(AcquisitionRunner.sleep_cancellable(runner, .2))
        self.assertAlmostEqual(clock[0], .2)


import gui_pyqt


@unittest.skipIf(gui_pyqt.QT_IMPORT_ERROR is not None, "PyQt5 unavailable")
class SettlingGuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = gui_pyqt.QApplication.instance() or gui_pyqt.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = gui_pyqt.QSettings(os.path.join(self.temp.name, "settings.ini"), gui_pyqt.QSettings.IniFormat)
        self.window = gui_pyqt.PumpProbeWindow(settings=self.settings)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_manual_decimal_survives_slope_changes_and_restart(self):
        self.window.lockin_constants_spin.setValue(2.5)
        self.assertFalse(self.window.lockin_recommended_check.isChecked())
        self.window.hardware.bundle.lockin.slope_index = 3
        self.window.hardware.refresh_lockin_filter()
        self.window.update_status_labels()
        self.assertEqual(self.window.lockin_constants_spin.value(), 2.5)
        self.assertEqual(self.window.status_labels["slope_db_oct"].text(), "24")
        self.assertEqual(self.window.status_labels["integration_time"].text(), "0.075")
        config, errors = self.window.collect_config()
        self.assertEqual(config.lockin_settling_factor, 2.5)
        self.settings.sync()
        second = gui_pyqt.PumpProbeWindow(settings=self.settings)
        try:
            self.assertEqual(second.lockin_constants_spin.value(), 2.5)
            self.assertFalse(second.lockin_recommended_check.isChecked())
        finally:
            second.close()

    def test_recommended_mode_tracks_actual_slope(self):
        self.assertEqual(self.window.lockin_constants_spin.value(), 5)
        self.window.hardware.bundle.lockin.slope_index = 3
        self.window.hardware.refresh_lockin_filter()
        self.window.update_status_labels()
        self.assertEqual(self.window.lockin_constants_spin.value(), 10)
        self.assertIsNone(self.window.collect_config()[0].lockin_settling_factor)

    def test_connect_reuses_existing_input_setup_and_reads_actual_filter(self):
        with patch.object(self.window.hardware, "configure_lockin") as configure:
            self.window.connect_lockin()
        configure.assert_called_once_with()
        self.assertIsNotNone(self.window.hardware.status()["lockin_filter"])

    def test_gui_event_loop_remains_responsive_and_can_cancel_worker(self):
        config = MeasurementConfig()
        config.bbd_sections = [(219, 220, 1)]
        config.auto_gain_enabled = False
        config.lockin_settling_factor = 10000
        config.simulation_delay_scale = 1
        thread = gui_pyqt.QThread()
        worker = gui_pyqt.AcquisitionWorker(self.window.hardware, config)
        worker.moveToThread(thread)
        results = []
        waiting = []
        worker.status_changed.connect(lambda message: waiting.append(message))
        worker.measurement_cancelled.connect(results.append)
        worker.finished.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.start()
        deadline = time.monotonic() + 3
        iterations = 0
        try:
            while not any(message.startswith("Estabilizando") for message in waiting) and time.monotonic() < deadline:
                self.app.processEvents()
                iterations += 1
                time.sleep(.005)
            self.assertTrue(any(message.startswith("Estabilizando") for message in waiting))
            self.assertGreater(iterations, 0)
        finally:
            worker.cancel()
            while thread.isRunning() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
            thread.wait(1000)
            self.app.processEvents()
        self.assertFalse(thread.isRunning())
        self.assertTrue(results[0].cancelled)
        self.assertEqual(results[0].acquired_points, 0)


if __name__ == "__main__":
    unittest.main()
