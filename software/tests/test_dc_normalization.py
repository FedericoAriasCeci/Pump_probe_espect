import csv
import json
import math
import os
import tempfile
import unittest
from unittest.mock import patch

from acquisition_service import (
    AcquisitionRunner, MeasurementConfig, MEASUREMENT_POSITION_FIXED,
    aux_for_row, save_measurement_result, value_for_channel_with_aux_map,
)
from acquisition_utils import AcquisitionDataManager, DATA_COLUMNS
from dc_normalization import DC_EXTRA_COLUMNS, measured_dc, normalize_by_dc, valid_dc
from hardware_adapter import SimulatedHardwareAdapter
from session_manager import SessionManager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import gui_pyqt


class DCNormalizationTest(unittest.TestCase):
    def make_runner(self):
        hardware = SimulatedHardwareAdapter()
        config = MeasurementConfig()
        config.measurement_type = MEASUREMENT_POSITION_FIXED
        config.lambda_sections = [(640.0, 642.0, 2.0)]
        config.auto_gain_enabled = False
        config.average_aux = False
        config.simulation_delay_scale = 0
        config.integration_time_override = 0
        runner = AcquisitionRunner(hardware, config)
        return runner, hardware, config

    def signal_row(self, hardware, dc=2.0):
        return [3.0, 4.0, 5.0, 53.13, dc, 1000.0,
                hardware.bundle.bbd.posicion, hardware.bundle.mono.posicion]

    def run_with_means(self, runner, hardware, means):
        runner.config.average_aux = True
        runner.config.integration_time_override = .18
        runner.config.simulation_delay_scale = 1
        clock = [0.0]
        readings = iter(dc for mean in means for dc in [mean - .3, mean - .1, mean + .1, mean + .3, 2.0])

        def acquire():
            clock[0] += .01
            return self.signal_row(hardware, next(readings))

        def sleep(seconds):
            clock[0] += seconds

        with patch("acquisition_service.time.monotonic", side_effect=lambda: clock[0]), patch(
            "acquisition_service.time.sleep", side_effect=sleep
        ), patch.object(hardware, "acquire_row", side_effect=acquire):
            return runner.run()

    def test_voltage_ratio_preserves_sign(self):
        self.assertEqual(normalize_by_dc(3, 2), 1.5)
        self.assertEqual(normalize_by_dc(3, -2), -1.5)

    def test_zero_nonfinite_and_saturated_dc_do_not_produce_valid_ratios(self):
        for dc in [0, float("nan"), float("inf"), -float("inf"), 10.5, -10.5, 11, "bad"]:
            with self.subTest(dc=dc):
                self.assertFalse(valid_dc(dc))
                self.assertTrue(math.isnan(normalize_by_dc(3, dc)))

    def test_existing_eight_field_rows_remain_supported(self):
        self.assertEqual(measured_dc([3, 4, 5, 0, 2, 1000, 219, 640]), 2)
        manager = AcquisitionDataManager()
        manager.append_row([3, 4, 5, 0, 2, 1000, 219, 640, 99])
        self.assertEqual(len(manager.finish_run()["rows"][0]), len(DATA_COLUMNS))

    def test_same_snap_supplies_signal_and_pointwise_dc_without_extra_read(self):
        runner, hardware, config = self.make_runner()
        with patch.object(hardware, "acquire_row", side_effect=lambda: self.signal_row(hardware)) as acquire:
            result = runner.run()
        self.assertEqual(result.error_message, "")
        self.assertEqual(acquire.call_count, result.acquired_points)
        for row in result.runs[0]["rows"]:
            self.assertEqual(len(row), 8 + len(DC_EXTRA_COLUMNS))
            self.assertEqual(row[4], 2)
            self.assertEqual(measured_dc(row), 2)
            self.assertEqual(value_for_channel_with_aux_map(row, 4, config, 0, {}), 1.5)
            self.assertEqual(value_for_channel_with_aux_map(row, 5, config, 0, {}), 2.5)
            self.assertEqual(value_for_channel_with_aux_map(row, 6, config, 0, {}), 2)

    def test_averaged_denominator_preserves_instantaneous_dc_and_each_repetition(self):
        runner, hardware, config = self.make_runner()
        config.average_aux = True
        config.repetitions = 2
        result = self.run_with_means(runner, hardware, [4, 6, 8, 10])
        self.assertEqual(result.error_message, "")
        for run, expected in zip(result.runs, [(4, 6), (8, 10)]):
            for row, denominator in zip(run["rows"], expected):
                self.assertAlmostEqual(row[4], denominator)
                self.assertEqual(measured_dc(row), 2)
                self.assertAlmostEqual(value_for_channel_with_aux_map(
                    row, 4, config, result.average_aux_value, result.average_aux_by_lambda
                ), 3.0 / denominator)

    def test_invalid_mean_never_falls_back_to_another_repetitions_dc(self):
        for dc in [0, float("nan")]:
            row = [3, 4, 5, 0, dc, 1000, 219, 640, 2]
            denominator = aux_for_row(row, True, 8, {"640.0": 8})
            self.assertTrue(math.isnan(normalize_by_dc(3, denominator)))

    def test_invalid_dc_keeps_signal_and_logs_the_missing_normalization(self):
        runner, hardware, config = self.make_runner()
        logs = []
        runner.callbacks["log"] = logs.append
        with patch.object(hardware, "acquire_row", side_effect=lambda: self.signal_row(hardware, dc=0)):
            result = runner.run()
        self.assertEqual(result.error_message, "")
        self.assertEqual(result.acquired_points, 2)
        self.assertEqual(result.runs[0]["rows"][0][0], 3)
        self.assertTrue(any("normalizacion NaN" in message for message in logs))

    def test_saved_csv_contains_dc_and_matches_the_plotted_ratios(self):
        runner, hardware, config = self.make_runner()
        result = self.run_with_means(runner, hardware, [4, 8])
        self.assertEqual(result.error_message, "")
        with tempfile.TemporaryDirectory() as folder:
            paths = save_measurement_result(result, "", [], [], SessionManager(folder))
            with open(paths["normalized_path"], encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            for saved, row in zip(rows, result.runs[0]["rows"]):
                self.assertEqual(float(saved["DC_instantanea_V"]), 2)
                self.assertEqual(float(saved["DC_normalizacion_V"]), row[4])
                self.assertEqual(float(saved["DC_muestras"]), 4)
                self.assertAlmostEqual(float(saved["DC_desvio_V"]), math.sqrt(.2 / 3))
                self.assertAlmostEqual(float(saved["DC_duracion_s"]), .18)
                self.assertEqual(float(saved["DC_muestras_invalidas"]), 0)
                for column, channel in [("X_DC", 4), ("R_DC", 5)]:
                    self.assertEqual(float(saved[column]), value_for_channel_with_aux_map(
                        row, channel, config, result.average_aux_value, result.average_aux_by_lambda
                    ))
            with open(paths["raw_paths"][0], encoding="utf-8", newline="") as handle:
                raw = [row for row in csv.reader(handle) if row and not row[0].startswith("#")]
            self.assertEqual(raw[0][-5:], DC_EXTRA_COLUMNS)
            self.assertEqual(len(raw[0]), len(raw[1]))
            self.assertEqual(float(raw[1][-5]), 2)
            with open(paths["metadata_path"], encoding="utf-8") as handle:
                metadata = json.load(handle)
            self.assertEqual(metadata["dc_input"], "SR830 AUX IN 1")
            self.assertEqual(metadata["config"]["dc_normalization_mode"], "mean_during_settling_per_point")


@unittest.skipIf(gui_pyqt.QT_IMPORT_ERROR is not None, "PyQt5 unavailable")
class DCGuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = gui_pyqt.QApplication.instance() or gui_pyqt.QApplication([])

    def test_dc_status_and_normalized_graphs_use_the_correct_values(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = gui_pyqt.QSettings(os.path.join(folder, "settings.ini"), gui_pyqt.QSettings.IniFormat)
            window = gui_pyqt.PumpProbeWindow(settings=settings)
            try:
                config = MeasurementConfig()
                config.average_aux = True
                window.active_config = config
                window.reset_plots(config)
                # Mean DC = 4 V; the independently retained instantaneous DC = 2 V.
                window.on_point_acquired([3, 4, 5, 53.13, 4, 1000, 219, 650, 2], 1, 1, 1)
                self.assertEqual(window.plot_views[4]["lines"][1]["y"], [.75])
                self.assertEqual(window.plot_views[5]["lines"][1]["y"], [1.25])
                self.assertEqual(window.plot_views[6]["lines"][1]["y"], [4])
                self.assertEqual(window.status_labels["dc_voltage"].text(), "4.0")
                self.assertTrue(all(window.channel_checks[index].isChecked() for index in (4, 5, 6)))
                self.assertTrue(window.average_aux_check.isChecked())
                self.assertTrue(window.collect_config()[0].average_aux)
            finally:
                window.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
