"""HORIBA iHR320 por ICL: driver, adaptador y barridos, sin equipo ni licencia."""
import json
import math
import sys
import threading
import unittest
from unittest import mock

from acquisition_service import (
    AcquisitionRunner, MeasurementConfig, MEASUREMENT_DOUBLE, MEASUREMENT_LAMBDA_FIXED,
    MEASUREMENT_POSITION_FIXED, MONO_READ_INDEX, validate_measurement_config,
)
from hardware_adapter import BaseHardwareAdapter, SimulatedHardwareAdapter
from horiba_icl import HoribaCancelled, HoribaError, HoribaSettings, ICLMonochromator
from horiba_monochromator import HoribaMonochromator, parse_icl_index
from simulated_hardware import SimulatedBBD301, SimulatedLockIn
from tests.fake_icl import FakeICL, fake_factory


MOTION_COMMANDS = ("mono_init", "mono_moveToPosition", "mono_moveSlitMM", "mono_moveMirror",
                   "mono_moveGrating", "mono_setPosition")


class ICLDriverTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeICL()
        self.mono = ICLMonochromator(socket_factory=lambda *a, **kw: self.fake)

    def tearDown(self):
        self.mono.close()

    def motions(self):
        return [name for name in self.fake.names() if name in MOTION_COMMANDS]

    def test_open_session_only_queries(self):
        self.fake.initialized = False
        flags = self.mono.open_session()
        self.assertFalse(flags["initialized"])
        self.assertEqual(self.mono.status.state, "not_initialized")
        self.assertEqual(self.motions(), [])
        self.assertIn("mono_open", self.fake.names())

    def test_initialize_homes_only_when_needed_and_never_redefines_origin(self):
        self.fake.initialized = False
        report = self.mono.initialize()
        self.assertTrue(report["initialization_sent"])
        self.assertEqual(self.motions(), ["mono_init"])
        self.assertEqual(self.fake.commands[self.fake.names().index("mono_init")]["parameters"],
                         dict(index=0, force=False))
        self.fake.commands.clear()
        report = self.mono.initialize()
        self.assertFalse(report["initialization_sent"])
        self.assertEqual(self.motions(), [])

    def test_move_waits_for_idle_and_confirms_by_reading(self):
        self.fake.move_busy_polls = 3
        result = self.mono.move_to(640)
        self.assertEqual(result["wavelength_nm"], 640)
        names = self.fake.names()
        after_move = names[names.index("mono_moveToPosition") + 1:]
        self.assertGreaterEqual(after_move.count("mono_isBusy"), 4)
        self.assertIn("mono_getPosition", after_move)
        self.assertNotIn("mono_setPosition", names)

    def test_reading_outside_tolerance_is_an_error(self):
        self.fake.offset = .05
        with self.assertRaisesRegex(HoribaError, "tolerancia"):
            self.mono.move_to(640)

    def test_out_of_limits_target_sends_nothing(self):
        with self.assertRaises(ValueError):
            self.mono.move_to(1600)
        self.assertEqual(self.fake.commands, [])

    def test_cancel_abandons_wait_without_resending(self):
        cancel = threading.Event()
        self.fake.move_busy_polls = 1000

        def on_command(command):
            if command["command"] == "mono_moveToPosition":
                cancel.set()
        self.fake.on_command = on_command
        with self.assertRaises(HoribaCancelled):
            self.mono.move_to(640, cancel)
        self.assertEqual(self.motions(), ["mono_moveToPosition"])

    def test_icl_error_drops_the_session(self):
        self.mono.open_session()
        self.fake.error = "0;-1;sin parser"
        with self.assertRaisesRegex(HoribaError, "icl_settings.ini"):
            self.mono.snapshot()
        self.assertFalse(self.mono.opened)

    def test_missing_websocket_client_is_explained(self):
        mono = ICLMonochromator()
        with mock.patch.dict(sys.modules, {"websocket": None}):
            with self.assertRaisesRegex(HoribaError, "websocket-client"):
                mono.diagnose()


class HoribaAdapterTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeICL()
        self.mono = HoribaMonochromator(controller_factory=fake_factory(self.fake))

    def tearDown(self):
        self.mono.CerrarPuerto()

    def test_legacy_indices_map_to_icl_index(self):
        self.assertEqual(parse_icl_index("Mono1"), 0)
        self.assertEqual(parse_icl_index("COM5"), 0)
        self.assertEqual(parse_icl_index(""), 0)
        self.assertEqual(parse_icl_index("2"), 2)

    def test_connect_never_homes_and_reports_missing_initialization(self):
        self.fake.initialized = False
        state = self.mono.Conectar(0)
        self.assertTrue(state["conectado"])
        self.assertFalse(state["inicializado"])
        self.assertNotIn("mono_init", self.fake.names())
        with self.assertRaisesRegex(HoribaError, "sin inicializar"):
            self.mono.Mover(640)
        self.assertNotIn("mono_moveToPosition", self.fake.names())

    def test_connect_reads_slits_grating_and_output(self):
        self.fake.slits = {1: .25, 4: .5}
        state = self.mono.Conectar(0)
        self.assertTrue(state["inicializado"])
        self.assertEqual((state["rendija_entrada_mm"], state["rendija_salida_mm"]), (.25, .5))
        self.assertEqual(state["red"], "G1")
        self.assertEqual(state["red_lineas_mm"], 1200)
        self.assertEqual(state["salida_optica"], "Lateral")
        self.assertEqual(state["serie"], "TEST-IHR320")
        self.assertEqual(self.mono.posicion, 532)

    def test_move_keeps_requested_and_read_wavelength(self):
        self.mono.Conectar(0)
        self.fake.offset = -.004
        read = self.mono.Mover(640.0)
        self.assertEqual(self.mono.posicion, 640.0)
        self.assertAlmostEqual(read, 639.996)
        self.assertAlmostEqual(self.mono.posicion_leida, 639.996)
        self.assertEqual(self.mono.CalcularTiempoSleep(650), 0.0)

    def test_slits_send_only_what_changes_and_confirm(self):
        self.mono.Conectar(0)
        report = self.mono.AjustarRendijas(.1, .3)
        self.assertEqual(report["confirmed_moves"], ["slit_out_mm"])
        moves = [c["parameters"] for c in self.fake.commands if c["command"] == "mono_moveSlitMM"]
        self.assertEqual(moves, [dict(index=0, locationId=4, position=.3)])
        # La relectura float32 de ICL no provoca un segundo movimiento.
        self.fake.slits[4] = 0.30000001192092896
        self.fake.commands.clear()
        report = self.mono.AjustarRendijas(.1, .3)
        self.assertEqual(report["state"], "unchanged")
        self.assertNotIn("mono_moveSlitMM", self.fake.names())

    def test_invalid_slit_requests_send_nothing(self):
        self.mono.Conectar(0)
        self.fake.commands.clear()
        for value in (-.1, 7.5, "texto", float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.mono.AjustarRendijas(value, None)
        self.assertEqual(self.fake.commands, [])

    def test_failure_requires_reconnecting(self):
        self.mono.Conectar(0)
        self.fake.error = "falla"
        with self.assertRaises(HoribaError):
            self.mono.Mover(640)
        self.assertFalse(self.mono.connected)
        self.fake.error = None
        with self.assertRaisesRegex(HoribaError, "Conectar HORIBA"):
            self.mono.Mover(640)

    def test_status_is_cached_and_json_serializable(self):
        self.mono.Conectar(0)
        count = len(self.fake.commands)
        state = self.mono.estado()
        description = self.mono.describe()
        self.assertEqual(len(self.fake.commands), count)
        json.dumps(dict(state=state, description=description), sort_keys=True)


class FakeHoribaHardware(BaseHardwareAdapter):
    """SR830 y BBD simulados con el driver HORIBA real sobre el doble de ICL."""

    def __init__(self, fake):
        BaseHardwareAdapter.__init__(self, True)

        class Bundle:
            pass
        self.bundle = Bundle()
        self.bundle.bbd = SimulatedBBD301()
        self.bundle.bbd.Conectar()
        self.bundle.bbd.Home()
        self.bundle.mono = HoribaMonochromator(controller_factory=fake_factory(fake))
        self.bundle.lockin = SimulatedLockIn(self.bundle.bbd, self.bundle.mono)
        self.bundle.lockin.Configurar()
        self.bundle.close = lambda: None
        self.refresh_lockin_filter()


class HoribaMeasurementTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeICL()
        self.fake.offset = -.004
        self.hardware = FakeHoribaHardware(self.fake)
        self.hardware.connect_mono(0)
        self.fake.commands.clear()

    def tearDown(self):
        self.hardware.close()

    def config(self, mode):
        config = MeasurementConfig()
        config.measurement_type = mode
        config.simulation_mode = True
        config.simulation_delay_scale = 0.0
        config.integration_time_override = 0.0
        config.average_aux = False
        config.auto_gain_enabled = False
        config.bbd_sections = [(219.0, 219.5, 0.25)]
        config.lambda_sections = [(640.0, 644.0, 2.0)]
        config.slit_entrance_mm = .2
        config.slit_exit_mm = .4
        return config

    def test_lambda_sweep_applies_slits_first_and_records_both_wavelengths(self):
        result = AcquisitionRunner(self.hardware, self.config(MEASUREMENT_POSITION_FIXED)).run()
        self.assertEqual(result.error_message, "")
        rows = result.runs[0]["rows"]
        self.assertEqual([row[7] for row in rows], [640.0, 642.0, 644.0])
        for row in rows:
            self.assertAlmostEqual(row[MONO_READ_INDEX], row[7] - .004)
        names = self.fake.names()
        self.assertLess(max(i for i, n in enumerate(names) if n == "mono_moveSlitMM"),
                        names.index("mono_moveToPosition"))
        self.assertEqual(names.count("mono_moveToPosition"), 3)
        self.assertNotIn("mono_init", names)
        self.assertNotIn("mono_setPosition", names)
        horiba = result.metadata["horiba"]
        self.assertEqual(horiba["rendijas"]["state"], "confirmed")
        self.assertEqual(horiba["estado_final"]["rendija_entrada_mm"], .2)
        self.assertEqual(horiba["estado_final"]["rendija_salida_mm"], .4)
        self.assertEqual(result.metadata["config"]["horiba_rendija_salida_mm"], .4)
        json.dumps(result.metadata, sort_keys=True)

    def test_double_sweep_moves_wavelength_once_per_lambda(self):
        result = AcquisitionRunner(self.hardware, self.config(MEASUREMENT_DOUBLE)).run()
        self.assertEqual(result.error_message, "")
        self.assertEqual(len(result.runs[0]["rows"]), 9)
        self.assertEqual(self.fake.names().count("mono_moveToPosition"), 3)

    def test_lambda_fixed_moves_once_and_can_skip_slits(self):
        config = self.config(MEASUREMENT_LAMBDA_FIXED)
        config.longitud_onda_fija_nm = 650.0
        config.apply_slits = False
        result = AcquisitionRunner(self.hardware, config).run()
        self.assertEqual(result.error_message, "")
        self.assertEqual(len(result.runs[0]["rows"]), 3)
        self.assertEqual(self.fake.names().count("mono_moveToPosition"), 1)
        self.assertNotIn("mono_moveSlitMM", self.fake.names())
        self.assertTrue(all(row[7] == 650.0 for row in result.runs[0]["rows"]))

    def test_lambda_fixed_without_horiba_does_not_touch_it(self):
        config = self.config(MEASUREMENT_LAMBDA_FIXED)
        config.use_monochromator = False
        result = AcquisitionRunner(self.hardware, config).run()
        self.assertEqual(result.error_message, "")
        self.assertEqual(self.fake.commands, [])
        self.assertTrue(all(math.isnan(row[MONO_READ_INDEX]) for row in result.runs[0]["rows"]))

    def test_slit_failure_stops_before_any_wavelength_move(self):
        self.fake.ports[1]["slitType"] = 99
        result = AcquisitionRunner(self.hardware, self.config(MEASUREMENT_POSITION_FIXED)).run()
        self.assertIn("tipo de rendija", result.error_message)
        self.assertEqual(result.acquired_points, 0)
        self.assertNotIn("mono_moveToPosition", self.fake.names())

    def test_cancel_during_move_stops_without_error(self):
        self.fake.move_busy_polls = 1000
        runner = AcquisitionRunner(self.hardware, self.config(MEASUREMENT_POSITION_FIXED))

        def on_command(command):
            if command["command"] == "mono_moveToPosition":
                runner.cancel()
        self.fake.on_command = on_command
        result = runner.run()
        self.assertTrue(result.cancelled)
        self.assertEqual(result.error_message, "")
        self.assertEqual(result.acquired_points, 0)
        self.assertEqual(self.fake.names().count("mono_moveToPosition"), 1)
        # Equipo ocupado al terminar: queda registrado, no se reintenta.
        self.assertIn("estado_final_error", result.horiba)
        # La siguiente medicion no hereda la cancelacion.
        self.fake.move_busy_polls = 0
        self.fake.busy = False
        self.fake.move_pending = None
        self.fake.on_command = None
        self.hardware.connect_mono(0)
        result = AcquisitionRunner(self.hardware, self.config(MEASUREMENT_POSITION_FIXED)).run()
        self.assertEqual(result.error_message, "")
        self.assertFalse(result.cancelled)


class HoribaValidationTest(unittest.TestCase):
    def config(self):
        config = MeasurementConfig()
        config.measurement_type = MEASUREMENT_POSITION_FIXED
        config.lambda_sections = [(640.0, 644.0, 2.0)]
        config.simulation_mode = False
        return config

    def status(self, **changes):
        status = dict(bbd_connected=True, bbd_homed=True, lockin_connected=True, mono_connected=True,
                      mono_initialized=True, mono_limits_nm=[1.0, 1500.0])
        status.update(changes)
        return status

    def test_ready_configuration_passes(self):
        self.assertEqual(validate_measurement_config(self.config(), self.status()), [])

    def test_uninitialized_horiba_is_rejected(self):
        errors = validate_measurement_config(self.config(), self.status(mono_initialized=False))
        self.assertTrue(any("Inicializar HORIBA" in error for error in errors))

    def test_slits_outside_range_are_rejected(self):
        config = self.config()
        config.slit_exit_mm = 7.5
        errors = validate_measurement_config(config, self.status())
        self.assertTrue(any("salida" in error for error in errors))
        config.apply_slits = False
        self.assertEqual(validate_measurement_config(config, self.status()), [])

    def test_wavelengths_outside_horiba_limits_are_rejected(self):
        config = self.config()
        config.lambda_sections = [(1490.0, 1510.0, 10.0)]
        errors = validate_measurement_config(config, self.status())
        self.assertTrue(any("limites del HORIBA" in error for error in errors))


class SimulatedHoribaTest(unittest.TestCase):
    def test_simulator_follows_the_same_contract(self):
        hardware = SimulatedHardwareAdapter()
        state = hardware.read_mono_state()
        self.assertTrue(state["inicializado"])
        report = hardware.apply_mono_slits(.5, .6)
        self.assertEqual(report["actual_mm"], {"slit_in_mm": .5, "slit_out_mm": .6})
        self.assertEqual(hardware.status()["mono_slit_exit_mm"], .6)
        hardware.cancel_mono_wait()
        with self.assertRaises(HoribaCancelled):
            hardware.move_mono(600)
        hardware.reset_mono_cancel()
        hardware.move_mono(600)
        self.assertEqual(hardware.status()["mono_read_nm"], 600)


if __name__ == "__main__":
    unittest.main()
