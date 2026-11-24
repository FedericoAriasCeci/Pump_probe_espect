"""Per-point DC averaging with a virtual clock and no laboratory hardware."""

import math
import unittest
from unittest.mock import patch

from acquisition_service import (
    AcquisitionRunner, MeasurementConfig, MeasurementResult,
    MEASUREMENT_LAMBDA_FIXED, MEASUREMENT_POSITION_FIXED, MEASUREMENT_DOUBLE,
    estimate_seconds, value_for_channel_with_aux_map,
)
from hardware_adapter import SimulatedHardwareAdapter


class DCDuringSettlingTest(unittest.TestCase):
    def setUp(self):
        self.clock = 0.0
        self.query_times = []
        self.logs = []
        self.hardware = SimulatedHardwareAdapter()
        self.hardware.bundle.lockin.time_constant_index = 8  # 0.1 s
        self.config = MeasurementConfig()
        self.config.lockin_settling_factor = 1.8  # A 0.18 s test window.
        self.config.simulation_delay_scale = 1
        self.config.auto_gain_enabled = False
        self.config.bbd_sections = [(219, 220, 1)]
        self.config.lambda_sections = [(640, 642, 2)]
        self.runner = AcquisitionRunner(self.hardware, self.config, {"log": self.logs.append})
        self.addCleanup(patch.stopall)
        patch("acquisition_service.time.monotonic", side_effect=lambda: self.clock).start()
        patch("acquisition_service.time.sleep", side_effect=self.sleep).start()
        patch.object(self.hardware, "calculate_bbd_sleep", return_value=.2).start()
        patch.object(self.hardware, "calculate_mono_sleep", return_value=.1).start()

    def sleep(self, seconds):
        self.clock += seconds

    def row(self, dc, signal=3):
        return [signal, 4, 5, 53.13, dc, 1000,
                self.hardware.bundle.bbd.posicion, self.hardware.bundle.mono.posicion]

    def readings(self, rows, latency=.01, cancel_on=None):
        rows = iter(rows)

        def acquire():
            self.query_times.append(self.clock)
            self.clock += latency
            row = next(rows)
            if isinstance(row, Exception):
                raise row
            if len(self.query_times) == cancel_on:
                self.runner.cancel()
            # Use the axes at the time of acquisition, after actual simulated moves.
            return row[:6] + [self.hardware.bundle.bbd.posicion, self.hardware.bundle.mono.posicion]

        return patch.object(self.hardware, "acquire_row", side_effect=acquire)

    def window(self, mean):
        # Deliberately wrong transient X; final X must survive unchanged.
        return [self.row(mean + delta, signal=-100) for delta in (-.3, -.1, .1, .3)]

    def test_same_window_and_final_signal_for_every_point_in_all_modes_and_repetitions(self):
        for mode, count in [(MEASUREMENT_LAMBDA_FIXED, 2), (MEASUREMENT_POSITION_FIXED, 2), (MEASUREMENT_DOUBLE, 4)]:
            with self.subTest(mode=mode):
                self.clock = 0.0
                self.query_times.clear()
                self.config.measurement_type = mode
                self.config.repetitions = 2
                means = [2 + .5 * index for index in range(count * 2)]
                rows = [row for mean in means for row in self.window(mean) + [self.row(.5)]]
                runner = AcquisitionRunner(self.hardware, self.config)
                with self.readings(rows):
                    result = runner.run()
                self.assertEqual(result.error_message, "")
                self.assertEqual(result.acquired_points, count * 2)
                self.assertEqual(len(self.query_times), 5 * count * 2)
                for index, (row, mean) in enumerate(zip([row for run in result.runs for row in run["rows"]], means)):
                    self.assertEqual(row[:3], [3, 4, 5])
                    self.assertAlmostEqual(row[4], mean)
                    self.assertEqual(row[8:10], [.5, 4])
                    self.assertAlmostEqual(row[10], math.sqrt(.2 / 3))
                    self.assertAlmostEqual(row[11], .18)
                    self.assertEqual(row[12], 0)
                    self.assertAlmostEqual(self.query_times[index * 5 + 4] - self.query_times[index * 5], .18)
                    self.assertAlmostEqual(value_for_channel_with_aux_map(row, 4, self.config, 99, {}), 3 / mean)
                # Both mechanical margins complete before the first sample.
                self.assertAlmostEqual(self.query_times[0], .3)
                self.assertEqual(result.average_aux_by_lambda, {})

    def test_filter_change_discards_samples_and_restarts_the_existing_wait(self):
        original = self.hardware.refresh_lockin_filter
        calls = [0]

        def refresh():
            calls[0] += 1
            if calls[0] == 2:
                self.hardware.bundle.lockin.time_constant_index = 9  # 0.3 s
                self.hardware.bundle.lockin.slope_index = 3
            return original()

        # First window: 4 samples at 8 V; new window: 11 samples at 2 V.
        with patch.object(self.hardware, "refresh_lockin_filter", side_effect=refresh), self.readings(
            [self.row(8)] * 4 + [self.row(2)] * 11 + [self.row(9)]
        ):
            result = MeasurementResult(self.config)
            self.assertTrue(self.runner.acquire_point(result, 1, 0, 1))
        row = self.runner.data_manager.finish_run()["rows"][0]
        self.assertEqual(row[4], 2)
        self.assertEqual(row[9], 11)
        self.assertAlmostEqual(row[11], .54)
        self.assertEqual([item["time_constant_seconds"] for item in self.runner.lockin_filter_history], [.1, .3])

    def test_autorange_reuses_same_point_samples_only_without_a_sensitivity_change(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                self.clock = 0.0
                self.query_times.clear()
                self.config.auto_gain_enabled = True
                self.runner = AcquisitionRunner(self.hardware, self.config)
                rows = [self.row(8)] * 4 + ([self.row(2)] * 4 if changed else []) + [self.row(9)]
                with patch.object(self.hardware, "autorange_lockin_sensitivity", return_value={"changed": changed}), self.readings(rows):
                    self.assertTrue(self.runner.maybe_auto_gain_for_lambda(650))
                    self.assertTrue(self.runner.acquire_point(MeasurementResult(self.config), 1, 0, 1))
                row = self.runner.data_manager.finish_run()["rows"][0]
                self.assertEqual(row[4], 2 if changed else 8)
                self.assertEqual(row[9], 4)
                self.assertEqual(len(self.query_times), 9 if changed else 5)

    def test_invalid_sample_invalidates_mean_without_using_the_final_dc_as_fallback(self):
        for invalid in (float("nan"), float("inf"), 10.5, -10.5):
            with self.subTest(invalid=invalid):
                self.runner = AcquisitionRunner(self.hardware, self.config)
                with self.readings([self.row(dc) for dc in (1, invalid, 3, 4, 9)]):
                    self.assertTrue(self.runner.acquire_point(MeasurementResult(self.config), 1, 0, 1))
                row = self.runner.data_manager.finish_run()["rows"][0]
                self.assertTrue(math.isnan(row[4]))
                self.assertEqual(row[0], 3)
                self.assertEqual(row[8:10], [9, 4])
                self.assertTrue(math.isnan(row[10]))
                self.assertEqual(row[12], 1)

    def test_zero_samples_are_included_but_a_zero_mean_cannot_normalize(self):
        with self.readings([self.row(dc) for dc in (0, 0, 0, 0, 9)]):
            self.assertTrue(self.runner.acquire_point(MeasurementResult(self.config), 1, 0, 1))
        row = self.runner.data_manager.finish_run()["rows"][0]
        self.assertEqual(row[4], 0)
        self.assertEqual(row[9], 4)
        self.assertEqual(row[12], 0)
        self.assertTrue(math.isnan(value_for_channel_with_aux_map(row, 4, self.config, 9, {})))

    def test_sampling_error_preserves_only_previously_completed_points(self):
        with self.readings(self.window(2) + [self.row(9), self.row(8), TimeoutError("SNAP timeout")]):
            result = self.runner.run()
        self.assertIn("SNAP timeout", result.error_message)
        self.assertEqual(result.acquired_points, 1)
        self.assertEqual(len(result.runs[0]["rows"]), 1)
        self.assertAlmostEqual(result.runs[0]["rows"][0][4], 2)

    def test_a_completed_points_mean_is_not_reused_even_without_another_move(self):
        with self.readings(self.window(2) + [self.row(9)] + self.window(4) + [self.row(9)]):
            result = MeasurementResult(self.config)
            self.assertTrue(self.runner.acquire_point(result, 1, 0, 2))
            self.assertTrue(self.runner.acquire_point(result, 1, 1, 2))
        rows = self.runner.data_manager.finish_run()["rows"]
        self.assertAlmostEqual(rows[0][4], 2)
        self.assertAlmostEqual(rows[1][4], 4)
        self.assertEqual(len(self.query_times), 10)

    def test_cancel_during_sampling_or_final_snap_never_commits_a_partial_point(self):
        for cancel_on in (2, 5):
            with self.subTest(cancel_on=cancel_on):
                self.clock = 0.0
                self.query_times.clear()
                self.runner = AcquisitionRunner(self.hardware, self.config)
                with self.readings(self.window(2) + [self.row(9)], cancel_on=cancel_on):
                    result = self.runner.run()
                self.assertTrue(result.cancelled)
                self.assertEqual(result.acquired_points, 0)
                self.assertFalse(result.has_data())

    def test_slow_queries_record_actual_duration_without_a_second_window(self):
        with self.readings([self.row(1), self.row(3), self.row(9)], latency=.11):
            self.assertTrue(self.runner.acquire_point(MeasurementResult(self.config), 1, 0, 1))
        row = self.runner.data_manager.finish_run()["rows"][0]
        self.assertEqual(row[4], 2)
        self.assertEqual(row[9], 2)
        self.assertAlmostEqual(row[11], .22)
        self.assertAlmostEqual(self.query_times[-1], .22)

    def test_one_sample_has_unknown_dispersion_and_is_reported(self):
        self.config.lockin_settling_factor = .1  # 10 ms, less than one query.
        with self.readings([self.row(2), self.row(9)]):
            self.assertTrue(self.runner.acquire_point(MeasurementResult(self.config), 1, 0, 1))
        row = self.runner.data_manager.finish_run()["rows"][0]
        self.assertEqual(row[4], 2)
        self.assertEqual(row[9], 1)
        self.assertTrue(math.isnan(row[10]))
        self.assertTrue(any("menos de 2 muestras" in message for message in self.logs))

    def test_real_sampling_ignores_simulation_scale_and_preview_adds_no_average_time(self):
        self.config.simulation_mode = False
        self.hardware.simulation_mode = False
        self.config.simulation_delay_scale = 0
        self.hardware.refresh_lockin_filter()
        estimated = estimate_seconds(self.config, self.hardware.status())
        with self.readings(self.window(2) + [self.row(9)]):
            self.assertTrue(self.runner.acquire_point(MeasurementResult(self.config), 1, 0, 1))
        row = self.runner.data_manager.finish_run()["rows"][0]
        self.assertEqual(row[9], 4)
        self.assertAlmostEqual(row[11], .18)
        self.config.average_aux = False
        self.assertEqual(estimate_seconds(self.config, self.hardware.status()), estimated)


if __name__ == "__main__":
    unittest.main()
