"""Pruebas del controlador y CLI sin conectar ni mover instrumentos reales."""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
from enum import Enum
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from horiba_ezspec import HoribaError, HoribaEzSpec, HoribaTimeoutError
import probar_horiba_ezspec as cli


class FakeMono:
    Grating = Enum("Grating", {"FIRST": 0, "SECOND": 1, "THIRD": 2})
    Slit = Enum("Slit", {"A": 1, "B": 2, "C": 3, "D": 4})
    Mirror = Enum("Mirror", {"ENTRANCE": 0, "EXIT": 1})
    MirrorPosition = Enum("MirrorPosition", {"AXIAL": 0, "LATERAL": 1})
    ShutterPosition = Enum("ShutterPosition", {"CLOSED": 0, "OPENED": 1})

    def __init__(self, device_id=7, model="iHR320", initialized=True):
        self.device_id, self.model = device_id, model
        self.initialized, self.opened = initialized, False
        self.value = 500.0
        self.target = None
        self.busy_reads = 0
        self.stuck_busy = False
        self.hanging_ack = False
        self.wrong_readback = False
        self.fail_on_move = None
        self.moves = []
        self.events = []
        self.loops, self.threads = set(), set()
        self.grating = self.Grating.FIRST
        self.slits = {slit: 0.1 for slit in self.Slit}
        self.mirrors = {mirror: self.MirrorPosition.AXIAL for mirror in self.Mirror}
        self.shutter = self.ShutterPosition.CLOSED

    def id(self):
        return self.device_id

    def record(self, event):
        self.events.append(event)
        self.loops.add(asyncio.get_running_loop())
        self.threads.add(threading.get_ident())

    async def open(self):
        self.record("open")
        self.opened = True

    async def close(self):
        self.record("close")
        self.opened = False

    async def configuration(self):
        self.record("configuration")
        return {"monoModel": self.model, "serialNumber": "TEST-7",
                "gratings": [{"positionIndex": n} for n in range(3)]}

    async def is_open(self):
        self.record("is_open")
        return self.opened

    async def is_busy(self):
        self.record("is_busy")
        if self.stuck_busy:
            return True
        if self.busy_reads:
            self.busy_reads -= 1
            return True
        if self.target is not None:
            self.value, self.target = self.target, None
        return False

    async def is_initialized(self):
        self.record("is_initialized")
        return self.initialized

    async def initialize(self):
        self.record("initialize")
        self.initialized = True
        self.busy_reads = 2

    async def get_current_wavelength(self):
        self.record("read_wavelength")
        return self.value

    async def move_to_target_wavelength(self, wavelength):
        self.record("move")
        self.moves.append(wavelength)
        if self.fail_on_move == len(self.moves):
            raise RuntimeError("Fallo de comunicacion simulado")
        if self.hanging_ack:
            await asyncio.sleep(5)
        self.target = wavelength + (1.0 if self.wrong_readback else 0.0)
        self.busy_reads = 2

    async def get_turret_grating(self):
        return self.grating

    async def set_turret_grating(self, grating):
        self.grating = grating
        self.busy_reads = 1

    async def get_slit_position_in_mm(self, slit):
        return self.slits[slit]

    async def set_slit_position(self, slit, position_in_mm):
        self.slits[slit] = position_in_mm
        self.busy_reads = 1

    async def get_mirror_position(self, mirror):
        return self.mirrors[mirror]

    async def set_mirror_position(self, mirror, position):
        self.mirrors[mirror] = position
        self.busy_reads = 1

    async def open_shutter(self):
        self.shutter = self.ShutterPosition.OPENED

    async def close_shutter(self):
        self.shutter = self.ShutterPosition.CLOSED

    async def get_current_shutter_position(self):
        return self.shutter


class FakeManager:
    def __init__(self, monos):
        self.monochromators = monos
        self.started = self.stopped = False
        self.start_error = self.stop_error = None
        self.kwargs = None

    def factory(self, **kwargs):
        self.kwargs = kwargs
        return self

    async def start(self):
        self.started = True
        if self.start_error:
            raise self.start_error

    async def stop(self):
        self.stopped = True
        if self.stop_error:
            raise self.stop_error


class DriverTest(unittest.TestCase):
    def driver(self, monos=None, **kwargs):
        fake = FakeMono()
        manager = FakeManager([fake] if monos is None else monos)
        mono = HoribaEzSpec(manager_factory=manager.factory, poll_interval_s=0.001, **kwargs)
        self.addCleanup(mono.close)
        return mono, fake, manager

    def test_constructor_needs_no_sdk_or_running_thread(self):
        with patch("horiba_ezspec._default_manager_factory") as factory:
            mono = HoribaEzSpec()
            self.assertFalse(mono.Identificar())
            self.assertIsNone(mono._thread)
            factory.assert_not_called()
            with self.assertRaises(HoribaError):
                mono.Mover(532)

    def test_legacy_contract_waits_for_motion_before_returning(self):
        mono, fake, manager = self.driver()
        self.assertEqual(mono.AsignarPuerto(), 7)
        self.assertNotIn("initialize", fake.events)
        self.assertTrue(mono.Identificar())
        self.assertEqual(mono.Configurar(), 500)
        self.assertEqual(mono.Mover(532), 532)
        self.assertEqual(mono.posicion, 532)
        self.assertEqual(mono.LeerPosicion(), 532)
        self.assertEqual(mono.CalcularTiempoSleep(600), 0.0)
        self.assertEqual(fake.busy_reads, 0)
        self.assertIsNone(fake.target)
        self.assertFalse(manager.kwargs["start_icl"])
        mono.CerrarPuerto()
        self.assertTrue(manager.stopped)
        self.assertFalse(fake.opened)
        self.assertIsNone(mono._thread)

    def test_initialization_is_explicit_and_only_homes_when_needed(self):
        fake = FakeMono(initialized=False)
        mono, _, _ = self.driver([fake])
        mono.connect()
        self.assertFalse(mono.get_status()["initialized"])
        self.assertIsNone(mono.get_status()["wavelength_nm"])
        with self.assertRaisesRegex(HoribaError, "inicializado"):
            mono.move_to(532)
        self.assertFalse(fake.moves)
        mono.initialize()
        mono.initialize()
        self.assertEqual(fake.events.count("initialize"), 1)
        mono.initialize(force=True)
        self.assertEqual(fake.events.count("initialize"), 2)

    def test_calls_from_different_threads_share_one_sdk_loop(self):
        mono, fake, _ = self.driver()
        mono.connect()
        failures = []
        def worker(target):
            try:
                mono.move_to(target)
            except Exception as exc:
                failures.append(exc)
        threads = [threading.Thread(target=worker, args=(x,)) for x in (510, 520)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertFalse(failures)
        self.assertEqual(len(fake.loops), 1)
        self.assertEqual(len(fake.threads), 1)
        self.assertNotIn(threading.get_ident(), fake.threads)
        self.assertEqual(len(fake.moves), 2)

    def test_ambiguous_devices_require_an_explicit_sdk_id(self):
        mono, _, manager = self.driver([FakeMono(7), FakeMono(23)])
        with self.assertRaisesRegex(HoribaError, "device_id"):
            mono.connect()
        self.assertTrue(manager.stopped)
        self.assertIsNone(mono._loop)
        self.assertEqual(mono.connect(23), 23)  # ID, no indice de lista.

    def test_wrong_model_or_unknown_id_is_rejected(self):
        for devices, selected in [([FakeMono(model="iHR550")], None), ([FakeMono(7)], 0), ([], None)]:
            mono, _, manager = self.driver(devices)
            with self.assertRaises(HoribaError):
                mono.connect(selected)
            self.assertTrue(manager.stopped)

    def test_discovery_does_not_home_or_move(self):
        fake = FakeMono()
        manager = FakeManager([fake])
        rows = HoribaEzSpec.discover(manager_factory=manager.factory)
        self.assertEqual(rows[0]["device_id"], 7)
        self.assertEqual(rows[0]["model"], "iHR320")
        self.assertNotIn("initialize", fake.events)
        self.assertFalse(fake.moves)
        self.assertFalse(fake.opened)
        self.assertTrue(manager.stopped)

    def test_start_failure_is_cleaned_up_and_reports_original_error(self):
        mono, _, manager = self.driver()
        manager.start_error = OSError("ICL no disponible")
        with self.assertRaisesRegex(HoribaError, "ICL no disponible"):
            mono.connect()
        self.assertTrue(manager.stopped)
        self.assertFalse(mono.connected)
        self.assertIsNone(mono._thread)

    def test_stuck_motion_times_out_and_blocks_further_measurement(self):
        mono, fake, _ = self.driver(motion_timeout_s=0.03)
        mono.connect()
        fake.stuck_busy = True
        with self.assertRaises(HoribaTimeoutError):
            mono.move_to(532)
        self.assertTrue(mono.get_status()["faulted"])
        self.assertIsNone(mono.get_status()["initialized"])
        with self.assertRaisesRegex(HoribaError, "sesion fallo"):
            mono.move_to(540)
        self.assertFalse(fake.moves)
        fake.stuck_busy = False
        mono.wait_until_idle()
        mono.close()
        mono.connect()
        mono.motion_timeout_s = 1.0  # Margen para temporizadores de Windows durante la recuperacion.
        self.assertEqual(mono.move_to(532), 532)

    def test_timeout_also_covers_the_move_acknowledgement(self):
        mono, fake, _ = self.driver(motion_timeout_s=0.03)
        mono.connect()
        fake.hanging_ack = True
        with self.assertRaises(HoribaTimeoutError):
            mono.move_to(532)
        self.assertTrue(mono.get_status()["faulted"])

    def test_idle_at_wrong_wavelength_is_not_success(self):
        mono, fake, _ = self.driver()
        mono.connect()
        fake.wrong_readback = True
        with self.assertRaisesRegex(HoribaError, "Posicion incorrecta"):
            mono.move_to(532)
        self.assertEqual(mono.posicion, 533)
        self.assertTrue(mono.get_status()["faulted"])

    def test_invalid_inputs_and_experimental_limits_send_no_motion(self):
        mono, fake, _ = self.driver(wavelength_limits_nm=(400, 800))
        mono.connect()
        for value in (-1, float("nan"), float("inf"), True, 399, 801):
            with self.subTest(value=value), self.assertRaises(ValueError):
                mono.move_to(value)
        for value in (0, 4, 1.5, True):
            with self.assertRaises(ValueError):
                mono.set_grating(value)
        self.assertFalse(fake.moves)
        with self.assertRaises(ValueError):
            HoribaEzSpec(device_id="COM3")
        with self.assertRaises(ValueError):
            HoribaEzSpec(poll_interval_s=0)

    def test_grating_slit_mirror_and_shutter_use_sdk_units_and_enums(self):
        mono, fake, _ = self.driver()
        mono.connect()
        self.assertEqual(mono.CambiarRed(3), 3)
        self.assertEqual(fake.grating.value, 2)
        self.assertEqual(mono.get_grating(), 3)
        self.assertEqual(mono.set_slit_width("A", 0.25), 0.25)
        self.assertEqual(mono.get_slit_width("A"), 0.25)
        self.assertEqual(mono.set_mirror("exit", "lateral"), "lateral")
        self.assertEqual(mono.get_mirror("exit"), "lateral")
        self.assertEqual(mono.set_shutter(True), "opened")
        self.assertEqual(mono.set_shutter(False), "closed")
        self.assertEqual(mono.get_shutter(), "closed")

    def test_configuration_cannot_be_modified_by_the_caller(self):
        mono, _, _ = self.driver()
        mono.connect()
        config = mono.get_configuration()
        config["gratings"].clear()
        self.assertEqual(len(mono.get_configuration()["gratings"]), 3)

    def test_close_releases_thread_even_if_manager_stop_fails(self):
        mono, fake, manager = self.driver()
        mono.connect()
        manager.stop_error = RuntimeError("fallo al cerrar websocket")
        with self.assertRaisesRegex(HoribaError, "websocket"):
            mono.close()
        self.assertIsNone(mono._thread)
        self.assertFalse(mono.connected)
        self.assertFalse(fake.opened)
        mono.close()


class CliTest(unittest.TestCase):
    def invoke(self, args, fake=None):
        fake = fake or FakeMono()
        manager = FakeManager([fake])
        driver_class = HoribaEzSpec
        def create(**kwargs):
            kwargs["poll_interval_s"] = 0.001
            return driver_class(manager_factory=manager.factory, **kwargs)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(cli, "HoribaEzSpec", side_effect=create), redirect_stdout(stdout), redirect_stderr(stderr):
            result = cli.main(args)
        return result, manager, stdout.getvalue(), stderr.getvalue()

    def test_default_status_does_not_initialize_or_move(self):
        fake = FakeMono(initialized=False)
        result, manager, stdout, stderr = self.invoke([], fake)
        self.assertEqual(result, 0, stderr)
        self.assertTrue(json.loads(stdout)["ok"])
        self.assertNotIn("initialize", fake.events)
        self.assertFalse(fake.moves)
        self.assertTrue(manager.stopped)

    def test_successful_scan_records_reported_positions_and_json(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path, report_path = Path(directory) / "scan.csv", Path(directory) / "report.json"
            result, manager, _, stderr = self.invoke([
                "--report", str(report_path), "scan", "500", "500.3", "0.1", "--output-csv", str(csv_path),
            ])
            self.assertEqual(result, 0, stderr)
            import csv
            with csv_path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([float(row["reported_nm"]) for row in rows], [500, 500.1, 500.2, 500.3])
            self.assertNotIn("intensity", rows[0])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["ok"])
            self.assertEqual(report["points_completed"], 4)
            self.assertTrue(manager.stopped)

    def test_partial_scan_preserves_completed_points_and_closes(self):
        fake = FakeMono()
        fake.fail_on_move = 2
        with tempfile.TemporaryDirectory() as directory:
            csv_path, report_path = Path(directory) / "partial.csv", Path(directory) / "error.json"
            result, manager, _, stderr = self.invoke([
                "--report", str(report_path), "scan", "500", "510", "2", "--output-csv", str(csv_path),
            ], fake)
            self.assertEqual(result, 1)
            self.assertIn("Fallo de comunicacion", stderr)
            self.assertEqual(len(csv_path.read_text(encoding="utf-8").splitlines()), 2)
            self.assertFalse(json.loads(report_path.read_text(encoding="utf-8"))["ok"])
            self.assertTrue(manager.stopped)
            self.assertFalse(fake.opened)

    def test_existing_report_is_preserved_without_connecting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.json"
            path.write_text("conservar", encoding="utf-8")
            result, manager, _, _ = self.invoke(["--report", str(path), "move", "532"])
            self.assertEqual(result, 1)
            self.assertFalse(manager.started)
            self.assertEqual(path.read_text(encoding="utf-8"), "conservar")

    def test_scan_points_handle_direction_and_decimal_endpoints(self):
        self.assertEqual(cli.scan_points(510, 500, -2), [510, 508, 506, 504, 502, 500])
        self.assertEqual(cli.scan_points(0.1, 0.3, 0.1), [0.1, 0.2, 0.3])
        self.assertEqual(cli.scan_points(500, 505, 2), [500, 502, 504])
        for args in [(500, 510, -1), (500, 510, 0), (500, 510, float("nan"))]:
            with self.assertRaises(ValueError):
                cli.scan_points(*args)


class InstalledSdkTest(unittest.TestCase):
    def test_real_sdk_monochromator_methods_and_command_parameters(self):
        # Usa la clase real del SDK y un transporte de respuestas en memoria.
        # No abre sockets ni necesita ICL o un espectrometro.
        try:
            from horiba_sdk.communication import Response
            from horiba_sdk.devices.single_devices import Monochromator
            from horiba_sdk.icl_error import FakeErrorDB
            import inspect
        except ImportError:
            self.skipTest("Instale requirements-horiba-ezspec.txt para verificar la API real del SDK.")
        fixtures_path = Path(inspect.getfile(Monochromator)).parents[1] / "fake_responses" / "monochromator.json"
        fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
        fixtures["mono_isInitialized"] = {"results": {"initialized": True}}
        commands = []
        class MemoryTransport:
            def opened(self):
                return True
            async def request_with_response(self, command, timeout=5):
                commands.append((command.command, command.parameters))
                results = dict(fixtures[command.command].get("results", {}))
                if command.command == "mono_moveToPosition":
                    fixtures["mono_getPosition"]["results"]["wavelength"] = command.parameters["wavelength"]
                elif command.command == "mono_moveGrating":
                    fixtures["mono_getGratingPosition"]["results"]["position"] = command.parameters["position"]
                elif command.command == "mono_moveSlitMM":
                    fixtures["mono_getSlitPositionInMM"]["results"]["position"] = command.parameters["position"]
                elif command.command == "mono_moveMirror":
                    fixtures["mono_getMirrorPosition"]["results"]["position"] = command.parameters["position"]
                elif command.command in ("mono_shutterOpen", "mono_shutterClose"):
                    fixtures["mono_getShutterStatus"]["results"]["position"] = int(command.command == "mono_shutterOpen")
                return Response(command.id, command.command, results)
        manager = FakeManager([Monochromator(0, MemoryTransport(), FakeErrorDB())])
        with HoribaEzSpec(manager_factory=manager.factory) as mono:
            self.assertEqual(mono.move_to(532), 532)
            self.assertEqual(mono.set_grating(3), 3)
            self.assertEqual(mono.set_slit_width("A", 0.25), 0.25)
            self.assertEqual(mono.set_mirror("entrance", "lateral"), "lateral")
            self.assertEqual(mono.set_shutter(True), "opened")
        self.assertIn(("mono_moveGrating", {"index": 0, "position": 2}), commands)
        self.assertIn(("mono_moveSlitMM", {"index": 0, "locationId": 1, "position": 0.25}), commands)
        self.assertIn(("mono_moveMirror", {"index": 0, "locationId": 0, "position": 1}), commands)


if __name__ == "__main__":
    unittest.main()
