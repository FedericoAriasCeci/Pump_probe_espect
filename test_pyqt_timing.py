import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from acquisition_service import AcquisitionRunner, MeasurementConfig, validate_measurement_config
from hardware_adapter import BaseHardwareAdapter, RealHardwareAdapter, SimulatedHardwareAdapter, SR830_TIME_CONSTANTS
from session_manager import SessionManager
import gui_pyqt


class VirtualClock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class FakeSR830Resource:
    def __init__(self):
        self.index = 8
        self.reject_changes = False
        self.writes = []

    def query(self, command):
        if command != "OFLT?":
            raise AssertionError("Unexpected command: " + command)
        return str(self.index) + "\n"

    def write(self, command):
        self.writes.append(command)
        if not command.startswith("OFLT "):
            raise AssertionError("Unexpected command: " + command)
        if not self.reject_changes:
            self.index = int(command.split()[1])


class FakeLockin:
    def __init__(self, clock):
        self.clock = clock
        self.connected = True
        self.time_constant_s = 0.1
        self.numeroDeConstantesDeTiempo = 1
        self.TiempoDeIntegracionTotal = 0.1
        self.read_times = []
        self.applied_constants = []
        self.address = FakeSR830Resource()

    def SetearNumeroDeConstantesDeIntegracion(self, constants):
        self.applied_constants.append(constants)
        self.numeroDeConstantesDeTiempo = constants
        self.time_constant_s = SR830_TIME_CONSTANTS[int(self.address.query("OFLT?"))][1]
        self.TiempoDeIntegracionTotal = constants * self.time_constant_s

    def Adquirir(self):
        self.read_times.append(self.clock.now())
        return "1,2,3,4,1,1000"


class FakeBBD:
    def __init__(self, clock):
        self.clock = clock
        self.connected = True
        self.homed = True
        self.posicion = 219.0
        self.arrivals = []

    def Mover(self, position):
        moved = position != self.posicion
        if moved:
            self.clock.sleep(0.2)  # Represents a completed synchronous move.
        self.posicion = position
        self.arrivals.append((self.clock.now(), moved))

    def CalcularTiempoSleep(self, position):
        raise AssertionError("Do not add the legacy travel estimate after MoveTo")


class ClosedSMS:
    posicion = 0.0
    address = SimpleNamespace(is_open=False)

    def Mover(self, wavelength):
        raise AssertionError("A manual-lambda sweep must not move the SMS")

    def CalcularTiempoSleep(self, wavelength):
        raise AssertionError("A manual-lambda sweep must not wait for the SMS")


class ScriptedRealAdapter(RealHardwareAdapter):
    def __init__(self, clock):
        BaseHardwareAdapter.__init__(self, False)
        self.bundle = SimpleNamespace(
            bbd=FakeBBD(clock),
            mono=ClosedSMS(),
            lockin=FakeLockin(clock),
            bbd_settle_time_s=1.0,
        )


class SweepTimingTest(unittest.TestCase):
    def manual_config(self):
        config = MeasurementConfig()
        config.simulation_mode = False
        config.use_monochromator = False
        config.longitud_onda_fija_nm = 532.0
        config.bbd_sections = [(219.0, 219.25, 0.25)]
        config.auto_gain_enabled = False
        config.lockin_constants = 7
        return config

    def test_latest_constants_and_time_constant_are_used_after_arrival(self):
        clock = VirtualClock()
        hardware = ScriptedRealAdapter(clock)
        # Change both N and the instrument's tau after the initial connection.
        hardware.set_lockin_constants(1)
        hardware.bundle.lockin.address.index = 9
        config = self.manual_config()
        config.repetitions = 2
        with patch("acquisition_service.time.time", clock.now), patch("acquisition_service.time.sleep", clock.sleep):
            result = AcquisitionRunner(hardware, config).run()

        self.assertEqual(result.error_message, "")
        self.assertFalse(result.cancelled)
        self.assertEqual(result.acquired_points, 4)
        self.assertEqual(hardware.bundle.lockin.applied_constants, [1, 7])
        for read_time, (arrival_time, moved) in zip(hardware.bundle.lockin.read_times, hardware.bundle.bbd.arrivals):
            mechanical_margin = 1.0 if moved else 0.1
            self.assertAlmostEqual(read_time - arrival_time, mechanical_margin + 2.1)
        for run in result.runs:
            self.assertEqual([row[7] for row in run["rows"]], [532.0, 532.0])
        self.assertEqual(result.metadata["config"]["lockin_constants"], 7)
        self.assertAlmostEqual(result.metadata["hardware_status"]["integration_time"], 2.1)

    def test_timing_query_failure_prevents_any_motion(self):
        clock = VirtualClock()
        hardware = ScriptedRealAdapter(clock)
        with patch.object(hardware, "set_lockin_constants", side_effect=RuntimeError("OFLT query failed")):
            result = AcquisitionRunner(hardware, self.manual_config()).run()
        self.assertIn("OFLT query failed", result.error_message)
        self.assertEqual(hardware.bundle.bbd.arrivals, [])
        self.assertEqual(hardware.bundle.lockin.read_times, [])

    def test_real_wait_preserves_only_the_mechanical_margin(self):
        hardware = ScriptedRealAdapter(VirtualClock())
        self.assertEqual(hardware.calculate_bbd_sleep(219.0), 0.1)
        self.assertEqual(hardware.calculate_bbd_sleep(220.0), 1.0)
        self.assertEqual(hardware.calculate_bbd_sleep(200.0), 1.0)

    def test_selected_time_constant_is_applied_before_motion(self):
        clock = VirtualClock()
        hardware = ScriptedRealAdapter(clock)
        config = self.manual_config()
        config.lockin_time_constant_index = 10  # 1 s, with N=7.
        with patch("acquisition_service.time.time", clock.now), patch("acquisition_service.time.sleep", clock.sleep):
            result = AcquisitionRunner(hardware, config).run()
        self.assertEqual(result.error_message, "")
        self.assertEqual(hardware.bundle.lockin.address.writes, ["OFLT 10"])
        for read_time, (arrival_time, moved) in zip(hardware.bundle.lockin.read_times, hardware.bundle.bbd.arrivals):
            self.assertAlmostEqual(read_time - arrival_time, (1.0 if moved else 0.1) + 7.0)
        self.assertEqual(result.metadata["config"]["lockin_time_constant_index"], 10)

    def test_rejected_time_constant_prevents_any_motion(self):
        hardware = ScriptedRealAdapter(VirtualClock())
        hardware.bundle.lockin.address.reject_changes = True
        config = self.manual_config()
        config.lockin_time_constant_index = 11
        result = AcquisitionRunner(hardware, config).run()
        self.assertIn("no acepto", result.error_message)
        self.assertEqual(result.acquired_points, 0)
        self.assertEqual(hardware.bundle.bbd.arrivals, [])


class RepetitionReturnTest(unittest.TestCase):
    def run_sweep(self, prepare_aux=False, fail_return=False):
        clock = VirtualClock()
        hardware = ScriptedRealAdapter(clock)
        bbd = hardware.bundle.bbd
        events = []
        state = {"repetition": 0}

        def move(position):
            repetition = state["repetition"]
            events.append(("move_start", repetition, position, clock.now()))
            returning = position == 219.0 and bbd.posicion != 219.0
            if returning and fail_return:
                raise TimeoutError("Return to start timed out")
            if position != bbd.posicion:
                # The return takes much longer than N*tau (1.2 s).
                clock.sleep(8.0 if returning else 0.2)
            bbd.posicion = position
            events.append(("arrival", repetition, position, clock.now()))

        bbd.Mover = move
        acquire = hardware.acquire_row

        def record_read():
            events.append(("read", state["repetition"], bbd.posicion, clock.now()))
            return acquire()

        hardware.acquire_row = record_read

        def autorange():
            hardware.acquire_row()
            return {"changed": False}

        hardware.autorange_lockin_sensitivity = autorange
        config = MeasurementConfig()
        config.simulation_mode = False
        config.use_monochromator = False
        config.longitud_onda_fija_nm = 532.0
        config.bbd_sections = [(219.0, 221.0, 1.0)]
        config.repetitions = 3
        config.lockin_time_constant_index = 9  # tau = 300 ms.
        config.lockin_constants = 4
        config.auto_gain_enabled = prepare_aux
        config.average_aux = prepare_aux
        config.average_aux_seconds = 0.1

        class TracedRunner(AcquisitionRunner):
            def run_repetition(self, result, repetition, bbd_points, lambda_points):
                state["repetition"] = repetition
                return super().run_repetition(result, repetition, bbd_points, lambda_points)

            def sleep_cancellable(self, seconds):
                if abs(float(seconds) - 1.2) < 1e-9:
                    events.append(("integration_start", state["repetition"], bbd.posicion, clock.now()))
                return super().sleep_cancellable(seconds)

        with patch("acquisition_service.time.time", clock.now), patch("acquisition_service.time.sleep", clock.sleep):
            result = TracedRunner(hardware, config).run()
        return result, events

    def test_integration_of_repetitions_two_and_three_starts_after_long_return(self):
        result, events = self.run_sweep()
        self.assertEqual(result.error_message, "")
        self.assertEqual(result.acquired_points, 9)
        for repetition in [2, 3]:
            with self.subTest(repetition=repetition):
                start = next(e for e in events if e[:3] == ("move_start", repetition, 219.0))
                arrival = next(e for e in events if e[:3] == ("arrival", repetition, 219.0))
                integration = next(e for e in events if e[0] == "integration_start" and e[1] == repetition)
                read = next(e for e in events if e[0] == "read" and e[1] == repetition)
                self.assertAlmostEqual(arrival[3] - start[3], 8.0)
                self.assertEqual(integration[2], 219.0)
                self.assertAlmostEqual(integration[3] - arrival[3], 1.0)
                self.assertAlmostEqual(read[3] - integration[3], 1.2)
                self.assertEqual(result.runs[repetition - 1]["rows"][0][6], 219.0)

    def test_aux_and_autorange_also_wait_for_return_to_start(self):
        result, events = self.run_sweep(prepare_aux=True)
        self.assertEqual(result.error_message, "")
        for repetition in [1, 2, 3]:
            with self.subTest(repetition=repetition):
                arrival = next(e for e in events if e[:3] == ("arrival", repetition, 219.0))
                first_read = next(e for e in events if e[0] == "read" and e[1] == repetition)
                self.assertEqual(first_read[2], 219.0)
                mechanical_margin = 0.1 if repetition == 1 else 1.0
                self.assertGreaterEqual(first_read[3] + 1e-9, arrival[3] + mechanical_margin)

    def test_return_timeout_prevents_all_reads_in_second_repetition(self):
        result, events = self.run_sweep(prepare_aux=True, fail_return=True)
        self.assertIn("Return to start timed out", result.error_message)
        self.assertEqual(result.acquired_points, 3)
        self.assertEqual(len(result.runs), 1)
        self.assertFalse(any(e[0] in ("read", "integration_start") and e[1] >= 2 for e in events))


class LockinTimeConstantTest(unittest.TestCase):
    def test_all_twenty_values_match_sr830_commands_in_real_and_simulated_adapters(self):
        expected_seconds = [
            10e-6, 30e-6, 100e-6, 300e-6, 1e-3, 3e-3, 10e-3, 30e-3,
            0.1, 0.3, 1, 3, 10, 30, 100, 300, 1000, 3000, 10000, 30000,
        ]
        self.assertEqual(len(SR830_TIME_CONSTANTS), 20)
        real = ScriptedRealAdapter(VirtualClock())
        simulated = SimulatedHardwareAdapter()
        for index, seconds in enumerate(expected_seconds):
            with self.subTest(index=index):
                self.assertEqual(real.set_lockin_time_constant_index(index), index)
                real.set_lockin_constants(4)
                self.assertEqual(real.bundle.lockin.address.writes[-1], "OFLT " + str(index))
                self.assertAlmostEqual(real.integration_time(), 4 * seconds)
                self.assertEqual(simulated.set_lockin_time_constant_index(index), index)
                simulated.set_lockin_constants(4)
                self.assertAlmostEqual(simulated.integration_time(), 4 * seconds)
        simulated.close()

    def test_rejected_setting_reports_the_confirmed_value(self):
        hardware = ScriptedRealAdapter(VirtualClock())
        hardware.bundle.lockin.address.reject_changes = True
        with self.assertRaisesRegex(RuntimeError, "no acepto 3 s; confirmo 100 ms"):
            hardware.set_lockin_time_constant_index(11)

    def test_invalid_indices_never_send_a_command(self):
        hardware = ScriptedRealAdapter(VirtualClock())
        for index in [-1, 20, True, 1.5, "10"]:
            with self.subTest(index=index), self.assertRaises(ValueError):
                hardware.set_lockin_time_constant_index(index)
        self.assertEqual(hardware.bundle.lockin.address.writes, [])


@unittest.skipIf(gui_pyqt.QT_IMPORT_ERROR is not None, "PyQt is unavailable")
class WindowTimingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = gui_pyqt.QApplication.instance() or gui_pyqt.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pump_probe_timing_")
        with patch("gui_pyqt.list_serial_ports", return_value=[]), patch("gui_pyqt.guess_sms_port", return_value=""):
            self.window = gui_pyqt.PumpProbeWindow()
        self.window.session_manager = SessionManager(self.temporary.name)
        self.window.show_message = lambda *args: None

    def tearDown(self):
        self.window.hardware.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def test_default_manual_lambda_does_not_require_sms(self):
        self.assertTrue(self.window.use_mono_check.isChecked())
        config, errors = self.window.collect_config()
        self.assertEqual(errors, [])
        self.assertFalse(config.use_monochromator)

    def test_preview_reapplies_constants_changed_after_connection(self):
        self.window.connect_lockin()
        self.window.lockin_constants_spin.setValue(7)
        self.window.simulation_scale_spin.setValue(1.0)
        config, preview, errors = self.window.prepare_preview(False)

        self.assertEqual(errors, [])
        self.assertEqual(config.lockin_constants, 7)
        self.assertEqual(self.window.hardware.bundle.lockin.numeroDeConstantesDeTiempo, 7)
        self.assertAlmostEqual(preview["lockin_wait_s"], 0.7)
        self.assertIn("Constantes Lock-in por punto: 7", self.window.preview_text.toPlainText())

    def test_constants_cannot_be_edited_during_a_sweep(self):
        self.window.set_controls_busy(True)
        self.assertFalse(self.window.lockin_constants_spin.isEnabled())
        self.assertFalse(self.window.lockin_time_constant_combo.isEnabled())
        self.assertFalse(self.window.apply_lockin_button.isEnabled())
        self.window.set_controls_busy(False)
        self.assertTrue(self.window.lockin_constants_spin.isEnabled())
        self.assertTrue(self.window.lockin_time_constant_combo.isEnabled())
        self.assertTrue(self.window.apply_lockin_button.isEnabled())

    def test_preview_rejects_a_failed_timing_refresh(self):
        with patch.object(self.window.hardware, "set_lockin_constants", side_effect=RuntimeError("OFLT query failed")):
            config, preview, errors = self.window.prepare_preview(False)
        self.assertIsNone(preview)
        self.assertTrue(any("OFLT query failed" in error for error in errors))

    def test_checked_manual_lambda_skips_sms_and_unchecked_requires_it(self):
        status = {"bbd_connected": True, "lockin_connected": True, "mono_connected": False}
        config, errors = self.window.collect_config()
        config.simulation_mode = False
        self.assertEqual(errors + validate_measurement_config(config, status), [])
        self.window.use_mono_check.setChecked(False)
        config, errors = self.window.collect_config()
        config.simulation_mode = False
        self.assertTrue(config.use_monochromator)
        self.assertTrue(any("monocromador" in error for error in validate_measurement_config(config, status)))

    def test_lambda_sweeps_require_sms_even_if_manual_checkbox_is_checked(self):
        self.window.measurement_type_combo.setCurrentIndex(1)
        self.assertTrue(self.window.use_mono_check.isChecked())
        self.assertFalse(self.window.use_mono_check.isEnabled())
        self.assertTrue(self.window.mono_required_for_current_ui())

    def test_connect_reads_the_existing_time_constant_when_no_value_was_selected(self):
        self.window.hardware.set_lockin_time_constant_index(10)
        self.assertIsNone(self.window.lockin_time_constant_combo.currentData())
        self.window.connect_lockin()
        self.assertEqual(self.window.lockin_time_constant_combo.currentData(), 10)
        self.assertAlmostEqual(self.window.hardware.integration_time(), 1.0)

    def test_connect_applies_a_value_selected_before_connection(self):
        self.window.lockin_time_constant_combo.setCurrentIndex(self.window.lockin_time_constant_combo.findData(11))
        self.window.connect_lockin()
        self.assertEqual(self.window.hardware.query_lockin_time_constant_index(), 11)
        self.assertAlmostEqual(self.window.hardware.integration_time(), 3.0)

    def test_apply_button_and_preview_use_tau_times_n(self):
        self.assertFalse(self.window.lockin_time_constant_combo.isEditable())
        self.assertEqual(self.window.lockin_time_constant_combo.count(), 21)
        self.window.lockin_time_constant_combo.setCurrentIndex(self.window.lockin_time_constant_combo.findData(9))
        self.window.lockin_constants_spin.setValue(4)
        self.window.apply_lockin_button.click()
        self.assertAlmostEqual(self.window.hardware.integration_time(), 1.2)
        config, preview, errors = self.window.prepare_preview(False)
        self.assertEqual(errors, [])
        self.assertEqual(config.lockin_time_constant_index, 9)
        self.assertAlmostEqual(preview["lockin_wait_s"], 1.2)
        self.assertIn("Tiempo integracion tau: 300 ms", self.window.preview_text.toPlainText())


if __name__ == "__main__":
    unittest.main()
