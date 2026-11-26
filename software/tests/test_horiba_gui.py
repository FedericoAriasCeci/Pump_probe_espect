"""Controles del HORIBA en la GUI PyQt: tareas en segundo plano, sin equipo."""
import os
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import gui_pyqt
from acquisition_service import validate_measurement_config
from tests.fake_icl import FakeICL
from tests.test_horiba_adapter import FakeHoribaHardware


@unittest.skipIf(gui_pyqt.QT_IMPORT_ERROR is not None, "PyQt5 unavailable")
class HoribaGuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = gui_pyqt.QApplication.instance() or gui_pyqt.QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.settings = gui_pyqt.QSettings(os.path.join(self.folder.name, "settings.ini"),
                                           gui_pyqt.QSettings.IniFormat)
        self.window = gui_pyqt.PumpProbeWindow(settings=self.settings)
        self.messages = []
        self.window.show_message = lambda title, text, icon: self.messages.append(text)

    def tearDown(self):
        self.wait_task()
        self.window.close()
        self.app.processEvents()
        self.folder.cleanup()

    def wait_task(self, timeout=10.0):
        end = time.monotonic() + timeout
        while self.window.task_thread is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()
        self.assertIsNone(self.window.task_thread, "la tarea del HORIBA no termino")

    def use_fake_icl(self, fake):
        self.window.hardware.close()
        self.window.hardware = FakeHoribaHardware(fake)

    def test_slits_are_persisted_collected_and_applied_in_background(self):
        self.window.slit_entrance_spin.setValue(.25)
        self.window.slit_exit_spin.setValue(.5)
        self.window.apply_slits_check.setChecked(False)
        config = self.window.collect_config()[0]
        self.assertEqual((config.slit_entrance_mm, config.slit_exit_mm, config.apply_slits), (.25, .5, False))
        self.assertEqual(float(self.settings.value("horiba/slit_exit_mm")), .5)
        self.assertFalse(self.settings.value("horiba/apply_slits_on_start", type=bool))
        self.window.apply_slits_now()
        self.assertFalse(self.window.apply_slits_button.isEnabled())
        self.wait_task()
        self.assertTrue(self.window.apply_slits_button.isEnabled())
        self.assertEqual(self.window.status_labels["mono_slits"].text(), "0.25 / 0.5")
        self.assertTrue(any("Rendijas confirmadas por simulador" in line for line in self.window.log_lines))

    def test_connect_without_initialization_asks_before_homing(self):
        fake = FakeICL()
        fake.initialized = False
        self.use_fake_icl(fake)
        with mock.patch.object(gui_pyqt.QMessageBox, "question", return_value=gui_pyqt.QMessageBox.No) as question:
            self.window.connect_mono()
            self.wait_task()
        question.assert_called_once()
        self.assertNotIn("mono_init", fake.names())
        self.assertEqual(self.window.status_labels["mono_connected"].text(), "Sin inicializar")
        config = self.window.collect_config()[0]
        config.simulation_mode = False
        errors = validate_measurement_config(config, self.window.hardware_status())
        self.assertTrue(any("Inicializar HORIBA" in error for error in errors))

        with mock.patch.object(gui_pyqt.QMessageBox, "question", return_value=gui_pyqt.QMessageBox.Yes):
            self.window.initialize_mono()
            self.wait_task()
        self.assertEqual(fake.names().count("mono_init"), 1)
        self.assertEqual(self.window.status_labels["mono_connected"].text(), "OK")
        self.assertEqual(self.window.status_labels["mono_grating"].text(), "G1 (1200 l/mm) / Lateral")
        self.assertEqual(self.messages, [])

    def test_tolerance_is_editable_persisted_and_applies_without_reconnecting(self):
        fake = FakeICL()
        fake.offset = .02  # Lectura sistematicamente 0.02 nm por encima de lo pedido.
        self.use_fake_icl(fake)
        with mock.patch.object(gui_pyqt.QMessageBox, "question", return_value=gui_pyqt.QMessageBox.No):
            self.window.connect_mono()
            self.wait_task()
        self.assertEqual(self.window.horiba_tolerance_spin.value(), .01)
        with self.assertRaisesRegex(Exception, "Tolerancia lambda"):
            self.window.hardware.move_mono(640)
        self.window.connect_mono()
        self.wait_task()
        self.window.horiba_tolerance_spin.setValue(.03)
        self.assertEqual(float(self.settings.value("horiba/tolerance_nm")), .03)
        self.window.hardware.move_mono(640)
        self.assertAlmostEqual(self.window.hardware.status()["mono_read_nm"], 640.02)
        self.assertEqual(self.window.horiba_settings().tolerance_nm, .03)
        self.assertEqual(self.window.hardware.mono_state()["tolerancia_nm"], .03)
        self.window.set_controls_busy(True)
        self.assertFalse(self.window.horiba_tolerance_spin.isEnabled())
        self.window.set_controls_busy(False)
        config, preview, errors = self.window.prepare_preview(False)
        self.assertIn("Tolerancia lambda pedida/leida: 0.03 nm", self.window.preview_to_text(preview, config))

    def test_cancel_abandons_the_initialization_wait(self):
        fake = FakeICL()
        fake.initialized = False
        fake.init_busy_polls = 100000
        self.use_fake_icl(fake)
        with mock.patch.object(gui_pyqt.QMessageBox, "question", return_value=gui_pyqt.QMessageBox.Yes):
            self.window.initialize_mono()
        self.assertTrue(self.window.cancel_button.isEnabled())
        end = time.monotonic() + 5
        while "mono_init" not in fake.names() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.005)
        self.window.cancel_measurement()
        self.wait_task()
        self.assertEqual(fake.names().count("mono_init"), 1)
        self.assertTrue(any("homing puede continuar" in message for message in self.messages))
        self.assertEqual(self.window.status_labels["mono_connected"].text(), "No")


if __name__ == "__main__":
    unittest.main()
