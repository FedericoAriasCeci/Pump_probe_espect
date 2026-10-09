import datetime
import os
import sys
import traceback

import numpy as np

from acquisition_service import (
    CHANNELS,
    MEASUREMENT_DOUBLE,
    MEASUREMENT_LAMBDA_FIXED,
    MEASUREMENT_POSITION_FIXED,
    PLOT_SCALE_LINEAR,
    PLOT_SCALE_LOG,
    PLOT_SCALE_SYMLOG,
    MeasurementConfig,
    AcquisitionRunner,
    build_preview,
    channel_label,
    format_seconds,
    heatmap_display_matrix,
    heatmap_extent,
    heatmap_norm,
    nearest_index,
    points_for_config,
    save_measurement_result,
    validate_measurement_config,
    value_for_channel,
    value_for_channel_with_aux_map,
    x_value_from_position,
    x_label_for_config,
    x_value_for_row,
)
from hardware_adapter import create_hardware_adapter, guess_sms_port, list_serial_ports, normalize_sms_port
from session_manager import SessionManager


QT_IMPORT_ERROR = None

try:
    from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
    from PyQt5.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QProgressBar,
        QScrollArea,
        QSpinBox,
        QSplitter,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
    from matplotlib.figure import Figure
except Exception as exc:
    QT_IMPORT_ERROR = exc


APP_STYLE = """
QMainWindow, QWidget {
    background: #edf7f4;
    color: #263331;
    font-family: Segoe UI, Arial;
    font-size: 10pt;
}
QGroupBox {
    background: #fffefa;
    border: 1px solid #c6ddd8;
    border-radius: 8px;
    margin-top: 16px;
    padding: 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0px 5px;
    color: #0d6f66;
    font-weight: 600;
}
QLabel {
    background: transparent;
}
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTableWidget {
    background: #ffffff;
    border: 1px solid #bfd5d0;
    border-radius: 6px;
    padding: 5px;
    selection-background-color: #0c8d7d;
}
QTableWidget {
    gridline-color: #d7e5e1;
}
QHeaderView::section {
    background: #dcefe9;
    color: #253331;
    border: 0px;
    padding: 5px;
    font-weight: 600;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #9fbeb7;
    border-radius: 7px;
    padding: 8px 11px;
    color: #21302d;
}
QPushButton:hover {
    background: #f0fbf8;
    border-color: #0c8d7d;
}
QPushButton:pressed {
    background: #d6efe8;
}
QPushButton:disabled {
    color: #8fa09c;
    background: #edf2f0;
    border-color: #d1ddda;
}
QPushButton#primaryButton {
    background: #0c8d7d;
    border: 1px solid #087769;
    color: white;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background: #10a18f;
}
QPushButton#dangerButton {
    background: #c84c3d;
    border: 1px solid #a83f33;
    color: white;
    font-weight: 600;
}
QPushButton#dangerButton:hover {
    background: #db5b4a;
}
QPushButton#saveButton {
    background: #243a5e;
    border: 1px solid #1b2c48;
    color: white;
    font-weight: 600;
}
QPushButton#saveButton:hover {
    background: #2e4975;
}
QCheckBox {
    background: transparent;
    spacing: 7px;
}
QTabWidget::pane {
    border: 1px solid #c6ddd8;
    border-radius: 8px;
    background: #fffefa;
}
QTabBar::tab {
    background: #dcefe9;
    border: 1px solid #c6ddd8;
    padding: 7px 12px;
    margin-right: 3px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #fffefa;
    color: #0d6f66;
    font-weight: 600;
}
QProgressBar {
    border: 1px solid #bfd5d0;
    border-radius: 6px;
    background: #ffffff;
    text-align: center;
    height: 18px;
}
QProgressBar::chunk {
    background: #0c8d7d;
    border-radius: 5px;
}
QSplitter::handle {
    background: #cfe5df;
}
QTextEdit#logView {
    background: #172522;
    color: #d7fff4;
    border-color: #172522;
    font-family: Consolas, Courier New;
    font-size: 9pt;
}
"""


if QT_IMPORT_ERROR is None:

    class AcquisitionWorker(QObject):
        point_acquired = pyqtSignal(object, int, int, int)
        status_changed = pyqtSignal(str)
        log_message = pyqtSignal(str)
        progress_changed = pyqtSignal(int, int)
        aux_average_changed = pyqtSignal(float)
        measurement_finished = pyqtSignal(object)
        measurement_cancelled = pyqtSignal(object)
        error_raised = pyqtSignal(str)
        finished = pyqtSignal()

        def __init__(self, hardware, config):
            QObject.__init__(self)
            self.hardware = hardware
            self.config = config
            self.runner = None
            self.cancel_requested = False

        def run(self):
            try:
                callbacks = {
                    "point": self.point_acquired.emit,
                    "status": self.status_changed.emit,
                    "log": self.log_message.emit,
                    "progress": self.progress_changed.emit,
                    "error": self.error_raised.emit,
                    "aux_average": self.aux_average_changed.emit,
                }
                self.runner = AcquisitionRunner(self.hardware, self.config, callbacks)
                if self.cancel_requested:
                    self.runner.cancel()
                result = self.runner.run()
                if result.cancelled:
                    self.measurement_cancelled.emit(result)
                else:
                    self.measurement_finished.emit(result)
            except Exception:
                self.error_raised.emit(traceback.format_exc())
            self.finished.emit()

        def cancel(self):
            self.cancel_requested = True
            if self.runner is not None:
                self.runner.cancel()
            else:
                try:
                    self.hardware.stop_all()
                except Exception:
                    pass


    class PumpProbeWindow(QMainWindow):
        def __init__(self):
            QMainWindow.__init__(self)
            self.setWindowTitle("Pump-Probe PyQt V1")
            self.resize(1380, 860)
            self.session_manager = SessionManager()
            self.hardware = create_hardware_adapter(True)
            self.active_config = None
            self.current_result = None
            self.current_average_aux_value = 0.0
            self.current_average_aux_by_lambda = dict()
            self.worker = None
            self.thread = None
            self.closing = False
            self.log_lines = list()
            self.plot_views = dict()
            self.saved_paths = None
            self.default_mono_port, self.default_lockin_port = self.read_default_ports()
            self.build_ui()
            self.setStyleSheet(APP_STYLE)
            self.refresh_serial_ports(False)
            self.update_measurement_mode()
            self.update_hardware_visibility()
            self.update_status_labels()
            self.log("Aplicacion iniciada en modo simulacion")

        def read_default_ports(self):
            mono_port = "COM3"
            lockin_port = "8"
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataPuertos.txt")
            if not os.path.isfile(path):
                return mono_port, lockin_port
            try:
                with open(path, "r") as handle:
                    line = handle.readline().strip()
                parts = [part.strip() for part in line.split(",") if part.strip()]
                if len(parts) >= 3:
                    mono_port = parts[1]
                    lockin_port = parts[2]
                elif len(parts) >= 2:
                    mono_port = parts[0]
                    lockin_port = parts[1]
                elif len(parts) == 1:
                    mono_port = parts[0]
            except Exception:
                pass
            return normalize_sms_port(mono_port), lockin_port

        def build_ui(self):
            central = QWidget()
            main_layout = QHBoxLayout(central)
            main_layout.setContentsMargins(10, 10, 10, 10)
            main_layout.setSpacing(10)

            splitter = QSplitter(Qt.Horizontal)
            splitter.addWidget(self.build_left_panel())
            splitter.addWidget(self.build_center_panel())
            splitter.addWidget(self.build_right_panel())
            splitter.setSizes([390, 640, 330])
            main_layout.addWidget(splitter)
            self.setCentralWidget(central)

        def build_left_panel(self):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setMinimumWidth(360)
            scroll.setMaximumWidth(460)
            content = QWidget()
            layout = QVBoxLayout(content)
            layout.setContentsMargins(6, 6, 6, 6)
            layout.setSpacing(8)

            layout.addWidget(self.build_hardware_group())
            layout.addWidget(self.build_sweep_group())
            layout.addWidget(self.build_channels_group())
            layout.addWidget(self.build_actions_group())
            layout.addStretch(1)

            scroll.setWidget(content)
            return scroll

        def build_hardware_group(self):
            group = QGroupBox("Conexion")
            layout = QGridLayout(group)
            layout.setColumnStretch(1, 1)

            self.simulation_check = QCheckBox("Modo simulacion")
            self.simulation_check.setChecked(True)
            self.simulation_check.toggled.connect(self.on_simulation_changed)
            layout.addWidget(self.simulation_check, 0, 0, 1, 2)

            self.use_mono_check = QCheckBox("Usar SMS en lambda fija")
            self.use_mono_check.setChecked(True)
            self.use_mono_check.setToolTip("Si esta desactivado, en lambda fija no se exige ni se mueve el monocromador")
            layout.addWidget(self.use_mono_check, 1, 0, 1, 3)

            layout.addWidget(QLabel("Puerto SMS"), 2, 0)
            self.mono_port_edit = QComboBox()
            self.mono_port_edit.setEditable(True)
            layout.addWidget(self.mono_port_edit, 2, 1)

            self.refresh_ports_button = QPushButton("Refrescar")
            self.refresh_ports_button.clicked.connect(self.refresh_serial_ports)
            layout.addWidget(self.refresh_ports_button, 2, 2)

            layout.addWidget(QLabel("Puerto Lock-in"), 3, 0)
            self.lockin_port_edit = QLineEdit(self.default_lockin_port)
            layout.addWidget(self.lockin_port_edit, 3, 1, 1, 2)

            layout.addWidget(QLabel("Constantes Lock-in"), 4, 0)
            self.lockin_constants_spin = QSpinBox()
            self.lockin_constants_spin.setRange(1, 100)
            self.lockin_constants_spin.setValue(1)
            layout.addWidget(self.lockin_constants_spin, 4, 1, 1, 2)

            self.auto_gain_check = QCheckBox("Auto rango sensibilidad")
            self.auto_gain_check.setChecked(True)
            self.auto_gain_check.setToolTip("Ajusta solo SENS del SR830 al cambiar de lambda. No ejecuta Auto Phase.")
            layout.addWidget(self.auto_gain_check, 5, 0, 1, 3)

            self.connect_bbd_button = QPushButton("Conectar BBD")
            self.connect_bbd_button.clicked.connect(self.connect_bbd)
            layout.addWidget(self.connect_bbd_button, 6, 0)

            self.home_bbd_button = QPushButton("Home BBD")
            self.home_bbd_button.clicked.connect(self.home_bbd)
            layout.addWidget(self.home_bbd_button, 6, 1)

            self.connect_mono_button = QPushButton("Conectar SMS")
            self.connect_mono_button.clicked.connect(self.connect_mono)
            layout.addWidget(self.connect_mono_button, 7, 0)

            self.connect_lockin_button = QPushButton("Conectar Lock-in")
            self.connect_lockin_button.clicked.connect(self.connect_lockin)
            layout.addWidget(self.connect_lockin_button, 7, 1)

            self.connect_all_button = QPushButton("Conectar todo")
            self.connect_all_button.clicked.connect(self.connect_all_hardware)
            layout.addWidget(self.connect_all_button, 8, 0, 1, 3)

            self.release_hardware_button = QPushButton("Liberar hardware")
            self.release_hardware_button.clicked.connect(self.release_hardware)
            layout.addWidget(self.release_hardware_button, 9, 0, 1, 3)

            return group

        def build_sweep_group(self):
            group = QGroupBox("Barrido")
            layout = QVBoxLayout(group)

            form = QGridLayout()
            form.setColumnStretch(1, 1)

            form.addWidget(QLabel("Tipo"), 0, 0)
            self.measurement_type_combo = QComboBox()
            self.measurement_type_combo.addItem("Lambda fija - barrer BBD", MEASUREMENT_LAMBDA_FIXED)
            self.measurement_type_combo.addItem("Posicion fija - barrer lambda", MEASUREMENT_POSITION_FIXED)
            self.measurement_type_combo.addItem("Doble barrido", MEASUREMENT_DOUBLE)
            self.measurement_type_combo.currentIndexChanged.connect(self.update_measurement_mode)
            form.addWidget(self.measurement_type_combo, 0, 1)

            form.addWidget(QLabel("Eje X"), 1, 0)
            self.x_axis_combo = QComboBox()
            self.x_axis_combo.addItem("Distancia")
            self.x_axis_combo.addItem("Tiempo")
            form.addWidget(self.x_axis_combo, 1, 1)

            form.addWidget(QLabel("Escala mapa 2D"), 2, 0)
            self.plot_scale_combo = QComboBox()
            self.plot_scale_combo.addItem(PLOT_SCALE_LINEAR)
            self.plot_scale_combo.addItem(PLOT_SCALE_LOG)
            self.plot_scale_combo.addItem(PLOT_SCALE_SYMLOG)
            self.plot_scale_combo.setToolTip("Normalizacion del color para barridos 2D")
            self.plot_scale_combo.currentIndexChanged.connect(self.on_plot_scale_changed)
            form.addWidget(self.plot_scale_combo, 2, 1)

            form.addWidget(QLabel("Lambda fija (nm)"), 3, 0)
            self.fixed_lambda_spin = QDoubleSpinBox()
            self.fixed_lambda_spin.setRange(200.0, 2000.0)
            self.fixed_lambda_spin.setDecimals(4)
            self.fixed_lambda_spin.setValue(650.0)
            form.addWidget(self.fixed_lambda_spin, 3, 1)

            form.addWidget(QLabel("BBD fija (mm)"), 4, 0)
            self.fixed_position_spin = QDoubleSpinBox()
            self.fixed_position_spin.setRange(-1000.0, 1000.0)
            self.fixed_position_spin.setDecimals(6)
            self.fixed_position_spin.setValue(220.0)
            form.addWidget(self.fixed_position_spin, 4, 1)

            form.addWidget(QLabel("Repeticiones"), 5, 0)
            self.repetitions_spin = QSpinBox()
            self.repetitions_spin.setRange(1, 999)
            self.repetitions_spin.setValue(1)
            form.addWidget(self.repetitions_spin, 5, 1)

            form.addWidget(QLabel("Escala simulacion"), 6, 0)
            self.simulation_scale_spin = QDoubleSpinBox()
            self.simulation_scale_spin.setRange(0.0, 5.0)
            self.simulation_scale_spin.setDecimals(3)
            self.simulation_scale_spin.setSingleStep(0.05)
            self.simulation_scale_spin.setValue(0.05)
            form.addWidget(self.simulation_scale_spin, 6, 1)

            layout.addLayout(form)

            self.average_repetitions_check = QCheckBox("Calcular promedio entre repeticiones")
            self.average_repetitions_check.setChecked(False)
            layout.addWidget(self.average_repetitions_check)

            aux_row = QHBoxLayout()
            self.average_aux_check = QCheckBox("Promediar AUX por lambda")
            self.average_aux_check.setToolTip("Cada vez que cambia lambda mide AUX durante este tiempo y usa ese valor para X/AUX o R/AUX")
            self.average_aux_seconds_spin = QDoubleSpinBox()
            self.average_aux_seconds_spin.setRange(0.0, 9999.0)
            self.average_aux_seconds_spin.setDecimals(2)
            self.average_aux_seconds_spin.setValue(1.0)
            aux_row.addWidget(self.average_aux_check)
            aux_row.addWidget(self.average_aux_seconds_spin)
            aux_row.addWidget(QLabel("s"))
            layout.addLayout(aux_row)

            layout.addWidget(QLabel("Secciones BBD (mm)"))
            self.bbd_table = self.create_sections_table([(219.0, 221.0, 0.25)])
            layout.addWidget(self.bbd_table)

            layout.addWidget(QLabel("Secciones lambda (nm)"))
            self.lambda_table = self.create_sections_table([(640.0, 660.0, 2.0)])
            layout.addWidget(self.lambda_table)

            return group

        def build_channels_group(self):
            group = QGroupBox("Canales")
            layout = QGridLayout(group)
            layout.addWidget(QLabel("Ver"), 0, 1, Qt.AlignCenter)
            layout.addWidget(QLabel("PNG"), 0, 2, Qt.AlignCenter)

            self.channel_checks = list()
            self.save_channel_checks = list()
            defaults = MeasurementConfig()
            for row in range(0, len(CHANNELS)):
                label = channel_label(row)
                layout.addWidget(QLabel(label), row + 1, 0)
                view_check = QCheckBox()
                view_check.setChecked(bool(defaults.channels[row]))
                view_check.setToolTip("Mostrar este canal en un grafico interactivo")
                save_check = QCheckBox()
                save_check.setChecked(bool(defaults.plot_channels[row]))
                save_check.setToolTip("Guardar un PNG individual para este canal")
                layout.addWidget(view_check, row + 1, 1, Qt.AlignCenter)
                layout.addWidget(save_check, row + 1, 2, Qt.AlignCenter)
                self.channel_checks.append(view_check)
                self.save_channel_checks.append(save_check)
            return group

        def build_actions_group(self):
            group = QGroupBox("Acciones")
            layout = QGridLayout(group)

            self.preview_button = QPushButton("Vista previa")
            self.preview_button.clicked.connect(self.preview_measurement)
            layout.addWidget(self.preview_button, 0, 0)

            self.start_button = QPushButton("Medir")
            self.start_button.setObjectName("primaryButton")
            self.start_button.clicked.connect(self.start_measurement)
            layout.addWidget(self.start_button, 0, 1)

            self.cancel_button = QPushButton("Cancelar")
            self.cancel_button.setObjectName("dangerButton")
            self.cancel_button.setEnabled(False)
            self.cancel_button.clicked.connect(self.cancel_measurement)
            layout.addWidget(self.cancel_button, 1, 0)

            self.save_button = QPushButton("Guardar")
            self.save_button.setObjectName("saveButton")
            self.save_button.setEnabled(False)
            self.save_button.clicked.connect(self.save_current_result)
            layout.addWidget(self.save_button, 1, 1)

            return group

        def build_center_panel(self):
            self.center_tabs = QTabWidget()
            self.graph_tabs = QTabWidget()
            self.preview_text = QTextEdit()
            self.preview_text.setReadOnly(True)
            self.preview_text.setMinimumHeight(160)
            self.preview_text.setText("La vista previa aparece aca antes de medir.")
            self.center_tabs.addTab(self.graph_tabs, "Graficos")
            self.center_tabs.addTab(self.preview_text, "Vista previa")
            self.reset_plots(MeasurementConfig())
            return self.center_tabs

        def build_right_panel(self):
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)

            status_group = QGroupBox("Estado")
            status_layout = QGridLayout(status_group)
            self.status_labels = dict()
            names = [
                ("bbd_connected", "BBD"),
                ("bbd_position", "BBD mm"),
                ("mono_connected", "SMS"),
                ("mono_position", "Lambda nm"),
                ("lockin_connected", "Lock-in"),
                ("integration_time", "Integracion s"),
            ]
            for row in range(0, len(names)):
                key, label = names[row]
                status_layout.addWidget(QLabel(label), row, 0)
                value_label = QLabel("-")
                value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                status_layout.addWidget(value_label, row, 1)
                self.status_labels[key] = value_label
            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            status_layout.addWidget(self.progress_bar, len(names), 0, 1, 2)
            layout.addWidget(status_group)

            notes_group = QGroupBox("Notas")
            notes_layout = QVBoxLayout(notes_group)
            self.notes_text = QTextEdit()
            self.notes_text.setPlaceholderText("Notas de muestra, alineacion, potencia, filtros, observaciones...")
            notes_layout.addWidget(self.notes_text)
            layout.addWidget(notes_group, 1)

            log_group = QGroupBox("Log")
            log_layout = QVBoxLayout(log_group)
            self.log_text = QTextEdit()
            self.log_text.setObjectName("logView")
            self.log_text.setReadOnly(True)
            log_layout.addWidget(self.log_text)
            layout.addWidget(log_group, 2)

            return panel

        def create_sections_table(self, defaults):
            table = QTableWidget(5, 3)
            table.setHorizontalHeaderLabels(["Inicio", "Final", "Paso"])
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            table.setMinimumHeight(155)
            table.setMaximumHeight(170)
            for row in range(0, table.rowCount()):
                for col in range(0, table.columnCount()):
                    table.setItem(row, col, QTableWidgetItem(""))
            for row in range(0, len(defaults)):
                start_value, end_value, step_value = defaults[row]
                table.setItem(row, 0, QTableWidgetItem(str(start_value)))
                table.setItem(row, 1, QTableWidgetItem(str(end_value)))
                table.setItem(row, 2, QTableWidgetItem(str(step_value)))
            return table

        def log(self, message):
            stamp = datetime.datetime.now().strftime("%H:%M:%S")
            line = "[" + stamp + "] " + str(message)
            self.log_lines.append(line)
            if hasattr(self, "log_text"):
                self.log_text.append(line)

        def hardware_status(self):
            try:
                return self.hardware.status()
            except Exception as exc:
                self.log("No se pudo leer estado de hardware: " + str(exc))
                return {
                    "bbd_connected": False,
                    "mono_connected": False,
                    "lockin_connected": False,
                    "integration_time": 0,
                    "simulation_mode": self.simulation_check.isChecked(),
                }

        def update_status_labels(self):
            status = self.hardware_status()
            values = {
                "bbd_connected": self.yes_no(status.get("bbd_connected", False)),
                "bbd_position": self.format_float(status.get("bbd_position", 0.0), 6),
                "mono_connected": self.yes_no(status.get("mono_connected", False)),
                "mono_position": self.format_float(status.get("mono_position", 0.0), 4),
                "lockin_connected": self.yes_no(status.get("lockin_connected", False)),
                "integration_time": self.format_float(status.get("integration_time", 0.0), 4),
            }
            for key in values:
                if key in self.status_labels:
                    self.status_labels[key].setText(values[key])

        def current_mono_port(self):
            data = self.mono_port_edit.currentData()
            if data is not None and str(data).strip() != "":
                return str(data).strip()
            text = self.mono_port_edit.currentText().strip()
            if " - " in text:
                text = text.split(" - ")[0].strip()
            return text

        def refresh_serial_ports(self, show_log=True):
            selected = self.default_mono_port
            if hasattr(self, "mono_port_edit"):
                selected = self.current_mono_port() or self.default_mono_port
            selected = normalize_sms_port(selected)
            guessed = normalize_sms_port(guess_sms_port())
            ports = list_serial_ports()

            self.mono_port_edit.blockSignals(True)
            self.mono_port_edit.clear()
            devices = list()
            for port in ports:
                device = normalize_sms_port(port.get("device", ""))
                description = str(port.get("description", "") or "")
                if device == "":
                    continue
                devices.append(device)
                display = device
                if description:
                    display = display + " - " + description
                self.mono_port_edit.addItem(display, device)

            if selected and selected not in devices:
                self.mono_port_edit.addItem(selected, selected)
                devices.append(selected)

            chosen = guessed or selected
            if chosen:
                index = self.mono_port_edit.findData(chosen)
                if index >= 0:
                    self.mono_port_edit.setCurrentIndex(index)
                else:
                    self.mono_port_edit.setEditText(chosen)
            self.mono_port_edit.blockSignals(False)

            if show_log:
                if len(ports) == 0:
                    self.log("No se detectaron puertos serie con PySerial")
                else:
                    descriptions = list()
                    for port in ports:
                        device = normalize_sms_port(port.get("device", ""))
                        description = str(port.get("description", "") or "")
                        descriptions.append(device + (" (" + description + ")" if description else ""))
                    self.log("Puertos serie detectados: " + ", ".join(descriptions))
                if guessed:
                    self.log("Candidato SMS detectado: " + guessed)

        def yes_no(self, value):
            if value:
                return "OK"
            return "No"

        def format_float(self, value, decimals):
            try:
                return str(round(float(value), decimals))
            except Exception:
                return "-"

        def update_hardware_visibility(self):
            real_mode = not self.simulation_check.isChecked()
            self.mono_port_edit.setEnabled(real_mode)
            self.lockin_port_edit.setEnabled(real_mode)
            self.connect_all_button.setEnabled(True)
            self.connect_bbd_button.setEnabled(True)
            self.home_bbd_button.setEnabled(True)
            self.connect_mono_button.setEnabled(True)
            self.connect_lockin_button.setEnabled(True)
            self.refresh_ports_button.setEnabled(real_mode)
            self.release_hardware_button.setEnabled(True)
            self.auto_gain_check.setEnabled(True)
            self.simulation_scale_spin.setEnabled(not real_mode)

        def set_controls_busy(self, busy):
            enabled = not busy
            self.simulation_check.setEnabled(enabled)
            self.use_mono_check.setEnabled(enabled and self.measurement_type_combo.currentData() == MEASUREMENT_LAMBDA_FIXED)
            self.measurement_type_combo.setEnabled(enabled)
            self.x_axis_combo.setEnabled(enabled and self.measurement_type_combo.currentData() != MEASUREMENT_POSITION_FIXED)
            self.plot_scale_combo.setEnabled(self.measurement_type_combo.currentData() == MEASUREMENT_DOUBLE)
            self.fixed_lambda_spin.setEnabled(enabled and self.measurement_type_combo.currentData() == MEASUREMENT_LAMBDA_FIXED)
            self.fixed_position_spin.setEnabled(enabled and self.measurement_type_combo.currentData() == MEASUREMENT_POSITION_FIXED)
            self.repetitions_spin.setEnabled(enabled)
            self.average_repetitions_check.setEnabled(enabled)
            self.average_aux_check.setEnabled(enabled)
            self.average_aux_seconds_spin.setEnabled(enabled)
            self.bbd_table.setEnabled(enabled and self.measurement_type_combo.currentData() in (MEASUREMENT_LAMBDA_FIXED, MEASUREMENT_DOUBLE))
            self.lambda_table.setEnabled(enabled and self.measurement_type_combo.currentData() in (MEASUREMENT_POSITION_FIXED, MEASUREMENT_DOUBLE))
            self.connect_bbd_button.setEnabled(enabled)
            self.home_bbd_button.setEnabled(enabled)
            self.connect_mono_button.setEnabled(enabled)
            self.connect_lockin_button.setEnabled(enabled)
            self.connect_all_button.setEnabled(enabled)
            self.refresh_ports_button.setEnabled(enabled and not self.simulation_check.isChecked())
            self.release_hardware_button.setEnabled(enabled)
            self.auto_gain_check.setEnabled(enabled)

        def update_measurement_mode(self):
            mode = self.measurement_type_combo.currentData()
            lambda_fixed = mode == MEASUREMENT_LAMBDA_FIXED
            position_fixed = mode == MEASUREMENT_POSITION_FIXED
            double_mode = mode == MEASUREMENT_DOUBLE
            self.bbd_table.setEnabled(lambda_fixed or double_mode)
            self.lambda_table.setEnabled(position_fixed or double_mode)
            self.fixed_lambda_spin.setEnabled(lambda_fixed)
            self.fixed_position_spin.setEnabled(position_fixed)
            self.x_axis_combo.setEnabled(not position_fixed)
            self.plot_scale_combo.setEnabled(double_mode)
            self.use_mono_check.setEnabled(lambda_fixed)
            if not lambda_fixed:
                self.use_mono_check.setChecked(True)

        def mono_required_for_current_ui(self):
            mode = self.measurement_type_combo.currentData()
            if mode == MEASUREMENT_LAMBDA_FIXED and not self.use_mono_check.isChecked():
                return False
            return True

        def on_simulation_changed(self, checked):
            try:
                self.hardware.close()
            except Exception:
                pass
            if checked:
                self.hardware = create_hardware_adapter(True)
                self.log("Modo simulacion activo")
            else:
                try:
                    self.hardware = create_hardware_adapter(False)
                    self.log("Modo hardware real activo")
                except Exception as exc:
                    self.show_message("No pude iniciar hardware real", str(exc), QMessageBox.Warning)
                    self.simulation_check.blockSignals(True)
                    self.simulation_check.setChecked(True)
                    self.simulation_check.blockSignals(False)
                    self.hardware = create_hardware_adapter(True)
                    self.log("Vuelvo a modo simulacion")
            self.update_hardware_visibility()
            self.update_status_labels()

        def connect_bbd(self):
            try:
                self.hardware.connect_bbd()
                self.log("BBD conectado")
            except Exception as exc:
                self.log("Error conectando BBD: " + str(exc))
                self.show_message("Error conectando BBD", str(exc), QMessageBox.Warning)
            self.update_status_labels()

        def home_bbd(self):
            try:
                self.hardware.home_bbd()
                self.log("Home BBD completado")
            except Exception as exc:
                self.log("Error en Home BBD: " + str(exc))
                self.show_message("Error en Home BBD", str(exc), QMessageBox.Warning)
            self.update_status_labels()

        def connect_mono(self):
            self.refresh_serial_ports(False)
            port = self.current_mono_port()
            if self.simulation_check.isChecked():
                port = "SIM"
            try:
                port = self.hardware.connect_mono(port)
                if not self.hardware.identify_mono():
                    try:
                        self.hardware.close_mono()
                    except Exception:
                        pass
                    raise Exception("El puerto " + str(port) + " abrio, pero el SMS no respondio a la identificacion.")
                self.hardware.configure_mono()
                profile = getattr(self.hardware.bundle.mono, "serial_profile", "default")
                self.log("SMS conectado en " + port + " (" + str(profile) + ")")
            except Exception as exc:
                try:
                    if not self.simulation_check.isChecked():
                        self.hardware.close_mono()
                except Exception:
                    pass
                available = list()
                for item in list_serial_ports():
                    device = normalize_sms_port(item.get("device", ""))
                    description = str(item.get("description", "") or "")
                    available.append(device + (" - " + description if description else ""))
                detail = str(exc)
                if len(available) > 0:
                    detail = detail + "\n\nPuertos detectados:\n" + "\n".join(available)
                self.log("Error conectando SMS en " + str(port) + ": " + str(exc))
                self.show_message("Error conectando SMS", detail, QMessageBox.Warning)
            self.update_status_labels()

        def connect_lockin(self):
            port = self.lockin_port_edit.text().strip()
            if self.simulation_check.isChecked():
                port = "SIM"
            try:
                self.log("Lock-in: abriendo recurso " + str(port))
                port = self.hardware.connect_lockin(port)
                self.log("Lock-in: recurso abierto")
                self.log("Lock-in: identificando")
                if not self.hardware.identify_lockin():
                    raise Exception("El recurso abrio, pero no respondio como SR830.")
                self.log("Lock-in: configurando")
                self.hardware.configure_lockin()
                self.log("Lock-in: leyendo constante de tiempo")
                self.hardware.set_lockin_constants(self.lockin_constants_spin.value())
                self.log("Lock-in conectado en " + port)
            except Exception as exc:
                try:
                    if not self.simulation_check.isChecked():
                        self.hardware.close_lockin()
                except Exception:
                    pass
                self.log("Error conectando Lock-in: " + str(exc))
                self.show_message(
                    "Error conectando Lock-in",
                    str(exc)
                    + "\n\nSi la ultima linea fue 'abriendo recurso', el programa todavia no envio comandos al SR830: el problema esta en la apertura VISA/GPIB o en que el instrumento no responde en el bus."
                    + "\n\nSi esto aparece solo cuando AUX1 esta conectado, revise que AUX IN 1 no reciba mas de +/-10 V y que no se este cortocircuitando la salida del PMT/preamp a tierra.",
                    QMessageBox.Warning,
                )
            self.update_status_labels()

        def connect_all_hardware(self):
            self.connect_bbd()
            self.home_bbd()
            if self.mono_required_for_current_ui():
                self.log("SMS omitido para lambda fija manual")
                # self.connect_mono()
            else:
                self.log("SMS omitido para lambda fija manual")
            self.connect_lockin()
            self.log("Chequeo de conexion completo")

        def release_hardware(self):
            if self.worker is not None:
                self.show_message(
                    "Medicion activa",
                    "Primero cancele la medicion antes de liberar hardware.",
                    QMessageBox.Warning,
                )
                return
            try:
                self.hardware.close()
                self.log("Hardware liberado")
            except Exception as exc:
                self.log("Error liberando hardware: " + str(exc))
            try:
                self.hardware = create_hardware_adapter(self.simulation_check.isChecked())
            except Exception as exc:
                self.log("No pude recrear adaptador de hardware: " + str(exc))
            self.update_status_labels()

        def read_sections(self, table, label):
            sections = list()
            errors = list()
            for row in range(0, table.rowCount()):
                texts = list()
                has_value = False
                for col in range(0, table.columnCount()):
                    item = table.item(row, col)
                    text = ""
                    if item is not None:
                        text = item.text().strip()
                    if text:
                        has_value = True
                    texts.append(text)
                if not has_value:
                    continue
                if "" in texts:
                    errors.append(label + ": fila " + str(row + 1) + " incompleta.")
                    continue
                try:
                    sections.append((float(texts[0]), float(texts[1]), float(texts[2])))
                except Exception:
                    errors.append(label + ": fila " + str(row + 1) + " tiene valores no numericos.")
            return sections, errors

        def collect_config(self):
            config = MeasurementConfig()
            errors = list()
            config.measurement_type = self.measurement_type_combo.currentData()
            config.x_axis = self.x_axis_combo.currentText()
            config.plot_scale = self.plot_scale_combo.currentText()
            config.longitud_onda_fija_nm = self.fixed_lambda_spin.value()
            config.posicion_fija_bbd_mm = self.fixed_position_spin.value()
            config.repetitions = self.repetitions_spin.value()
            config.average_repetitions = self.average_repetitions_check.isChecked()
            config.auto_gain_enabled = self.auto_gain_check.isChecked()
            config.average_aux = self.average_aux_check.isChecked()
            config.average_aux_seconds = self.average_aux_seconds_spin.value()
            config.simulation_mode = self.simulation_check.isChecked()
            config.use_monochromator = self.mono_required_for_current_ui()
            config.simulation_delay_scale = self.simulation_scale_spin.value()
            config.notes = self.notes_text.toPlainText()

            config.channels = list()
            config.plot_channels = list()
            for index in range(0, len(self.channel_checks)):
                config.channels.append(1 if self.channel_checks[index].isChecked() else 0)
                config.plot_channels.append(1 if self.save_channel_checks[index].isChecked() else 0)

            bbd_sections, bbd_errors = self.read_sections(self.bbd_table, "BBD")
            lambda_sections, lambda_errors = self.read_sections(self.lambda_table, "Lambda")
            errors.extend(bbd_errors)
            errors.extend(lambda_errors)
            config.bbd_sections = bbd_sections
            config.lambda_sections = lambda_sections
            return config, errors

        def prepare_preview(self, show_dialog):
            config, errors = self.collect_config()
            status = self.hardware_status()
            errors.extend(validate_measurement_config(config, status))
            if len(errors) > 0:
                text = "Hay que corregir:\n\n" + "\n".join("- " + error for error in errors)
                self.preview_text.setText(text)
                self.center_tabs.setCurrentWidget(self.preview_text)
                if show_dialog:
                    self.show_message("Validacion", text, QMessageBox.Warning)
                return config, None, errors

            preview = build_preview(config, status, self.session_manager)
            config.session_path_preview = preview.get("carpeta_sesion", "")
            self.preview_text.setText(self.preview_to_text(preview, config))
            self.center_tabs.setCurrentWidget(self.preview_text)
            return config, preview, errors

        def preview_measurement(self):
            self.prepare_preview(False)

        def preview_to_text(self, preview, config):
            mode_names = {
                MEASUREMENT_LAMBDA_FIXED: "Lambda fija - barrer BBD",
                MEASUREMENT_POSITION_FIXED: "Posicion fija - barrer lambda",
                MEASUREMENT_DOUBLE: "Doble barrido",
            }
            channel_names = [channel_label(index) for index in config.selected_channel_indices()]
            plot_names = [channel_label(index) for index in config.selected_plot_channel_indices()]
            lines = [
                "Vista previa de medicion",
                "",
                "Tipo: " + mode_names.get(preview.get("tipo"), str(preview.get("tipo"))),
                "Puntos por repeticion: " + str(preview.get("puntos_por_repeticion")),
                "Repeticiones: " + str(preview.get("repeticiones")),
                "Puntos totales: " + str(preview.get("puntos_totales")),
                "Tiempo estimado: " + str(preview.get("tiempo_estimado_texto")),
                "Monocromador: " + ("se usa" if config.use_monochromator else "omitido, lambda fija manual"),
                "Auto rango sensibilidad: " + ("activado" if config.auto_gain_enabled else "desactivado"),
                "AUX: " + ("promedio por lambda de " + str(config.average_aux_seconds) + " s" if config.average_aux else "lectura punto a punto"),
                "Escala mapa 2D: " + str(config.plot_scale),
                "Canales visibles: " + ", ".join(channel_names),
                "PNGs a guardar: " + (", ".join(plot_names) if len(plot_names) > 0 else "ninguno"),
                "",
                "Carpeta sugerida:",
                str(preview.get("carpeta_sesion")),
                "",
                "Archivos:",
                str(preview.get("archivos")),
            ]
            if config.average_repetitions:
                lines.append("promedio.csv")
            return "\n".join(lines)

        def start_measurement(self):
            config, preview, errors = self.prepare_preview(True)
            if len(errors) > 0:
                return
            if preview is None:
                return
            if preview.get("tiempo_estimado_s", 0) > 1800:
                reply = QMessageBox.question(
                    self,
                    "Tiempo estimado largo",
                    "El barrido estima " + format_seconds(preview.get("tiempo_estimado_s", 0)) + ".\n\nIniciar de todos modos?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    self.log("Medicion no iniciada por tiempo estimado largo")
                    return

            self.active_config = config
            self.current_result = None
            self.current_average_aux_value = 0.0
            self.current_average_aux_by_lambda = dict()
            self.saved_paths = None
            self.reset_plots(config)
            self.center_tabs.setCurrentWidget(self.graph_tabs)
            self.progress_bar.setValue(0)
            self.start_button.setEnabled(False)
            self.preview_button.setEnabled(False)
            self.save_button.setEnabled(False)
            self.cancel_button.setEnabled(True)
            self.set_controls_busy(True)

            self.thread = QThread()
            self.worker = AcquisitionWorker(self.hardware, config)
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.run)
            self.worker.point_acquired.connect(self.on_point_acquired)
            self.worker.status_changed.connect(self.on_status_changed)
            self.worker.log_message.connect(self.log)
            self.worker.progress_changed.connect(self.on_progress_changed)
            self.worker.aux_average_changed.connect(self.on_aux_average_changed)
            self.worker.error_raised.connect(self.on_worker_error)
            self.worker.measurement_finished.connect(self.on_measurement_finished)
            self.worker.measurement_cancelled.connect(self.on_measurement_cancelled)
            self.worker.finished.connect(self.thread.quit)
            self.worker.finished.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.thread.deleteLater)
            self.thread.finished.connect(self.on_thread_finished)
            self.log("Inicio solicitado")
            self.thread.start()

        def cancel_measurement(self):
            if self.worker is not None:
                self.log("Cancelacion solicitada")
                self.cancel_button.setEnabled(False)
                self.worker.cancel()

        def on_thread_finished(self):
            self.thread = None
            self.worker = None
            self.start_button.setEnabled(True)
            self.preview_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.set_controls_busy(False)
            self.update_measurement_mode()
            self.update_hardware_visibility()
            self.update_status_labels()

        def on_status_changed(self, message):
            self.log(message)
            self.update_status_labels()

        def on_aux_average_changed(self, value):
            self.current_average_aux_value = float(value)
            if self.active_config is not None and self.active_config.average_aux:
                self.log("AUX promedio: " + str(round(float(value), 6)))

        def on_progress_changed(self, acquired, total):
            if total <= 0:
                self.progress_bar.setValue(0)
                return
            self.progress_bar.setValue(int(round(100.0 * float(acquired) / float(total))))

        def on_worker_error(self, message):
            self.log("ERROR: " + str(message))

        def on_measurement_finished(self, result):
            self.current_result = result
            self.current_average_aux_by_lambda = dict(result.average_aux_by_lambda)
            self.add_average_overlay(result)
            self.save_button.setEnabled(result.has_data())
            self.log("Resultado listo en memoria")
            if result.error_message:
                self.show_message("Medicion con error", result.error_message, QMessageBox.Warning)
            self.offer_save_after_run(result, False)

        def on_measurement_cancelled(self, result):
            self.current_result = result
            self.current_average_aux_by_lambda = dict(result.average_aux_by_lambda)
            self.add_average_overlay(result)
            self.save_button.setEnabled(result.has_data())
            self.log("Resultado parcial listo en memoria")
            self.offer_save_after_run(result, True)

        def offer_save_after_run(self, result, cancelled):
            if self.closing:
                return
            if not result.has_data():
                if cancelled:
                    self.show_message("Medicion cancelada", "No hay puntos para guardar.", QMessageBox.Information)
                return
            box = QMessageBox(self)
            if cancelled:
                box.setWindowTitle("Medicion cancelada")
                box.setText("La medicion fue cancelada. Queres guardar los datos parciales?")
            else:
                box.setWindowTitle("Medicion finalizada")
                box.setText("La medicion termino. Queres guardar los datos ahora?")
            save_button = box.addButton("Guardar", QMessageBox.AcceptRole)
            box.addButton("No guardar", QMessageBox.RejectRole)
            box.exec_()
            if box.clickedButton() == save_button:
                self.save_current_result()

        def selected_save_channels(self):
            indices = list()
            for index in range(0, len(self.save_channel_checks)):
                if self.save_channel_checks[index].isChecked():
                    indices.append(index)
            return indices

        def save_current_result(self):
            if self.current_result is None or not self.current_result.has_data():
                self.show_message("Sin datos", "Todavia no hay datos para guardar.", QMessageBox.Information)
                return False
            if self.saved_paths is not None:
                reply = QMessageBox.question(
                    self,
                    "Ya guardado",
                    "Esta medicion ya fue guardada.\n\nGuardar otra copia en una nueva carpeta?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return False
            try:
                selected_channels = self.selected_save_channels()
                self.current_result.metadata["plot_channels_saved"] = [
                    channel_label(index) for index in selected_channels
                ]
                paths = save_measurement_result(
                    self.current_result,
                    self.notes_text.toPlainText(),
                    self.log_lines,
                    selected_channels,
                    self.session_manager,
                    self.current_result.config.session_path_preview,
                )
                self.saved_paths = paths
                self.log("Datos guardados en " + paths.get("session_path", ""))
                for plot_path in paths.get("plot_paths", []):
                    self.log("PNG guardado: " + plot_path)
                self.show_message("Guardado completo", "Datos guardados en:\n" + paths.get("session_path", ""), QMessageBox.Information)
                return True
            except Exception as exc:
                self.log("Error guardando: " + str(exc))
                self.show_message("Error guardando", str(exc), QMessageBox.Warning)
                return False

        def reset_plots(self, config):
            self.graph_tabs.clear()
            self.plot_views = dict()
            selected = config.selected_channel_indices()
            if len(selected) == 0:
                label = QLabel("Selecciona al menos un canal para ver graficos.")
                label.setAlignment(Qt.AlignCenter)
                page = QWidget()
                layout = QVBoxLayout(page)
                layout.addWidget(label)
                self.graph_tabs.addTab(page, "Sin canales")
                return
            for channel_index in selected:
                page = QWidget()
                layout = QVBoxLayout(page)
                layout.setContentsMargins(8, 8, 8, 8)
                figure = Figure(figsize=(5.0, 4.0), facecolor="#fffefa")
                canvas = FigureCanvas(figure)
                toolbar = NavigationToolbar(canvas, page)
                axis = figure.add_subplot(111)
                self.decorate_axis(axis, config, channel_index)
                layout.addWidget(toolbar)
                layout.addWidget(canvas, 1)
                self.graph_tabs.addTab(page, channel_label(channel_index))
                view = {
                    "figure": figure,
                    "canvas": canvas,
                    "axis": axis,
                    "lines": dict(),
                    "average_added": False,
                }
                if config.measurement_type == MEASUREMENT_DOUBLE:
                    bbd_points, lambda_points, point_count = points_for_config(config)
                    x_points = [x_value_from_position(position, config) for position in bbd_points]
                    matrix_sum = np.zeros((len(lambda_points), len(bbd_points)), dtype=float)
                    matrix_count = np.zeros((len(lambda_points), len(bbd_points)), dtype=float)
                    matrix = np.full((len(lambda_points), len(bbd_points)), np.nan, dtype=float)
                    display_matrix = heatmap_display_matrix(matrix, config.plot_scale)
                    norm = heatmap_norm(matrix, config.plot_scale)
                    if len(x_points) > 0 and len(lambda_points) > 0:
                        image = axis.imshow(
                            display_matrix,
                            origin="lower",
                            aspect="auto",
                            extent=heatmap_extent(x_points, lambda_points),
                            cmap="viridis",
                            norm=norm,
                            interpolation="nearest",
                        )
                        colorbar = figure.colorbar(image, ax=axis)
                        colorbar.set_label(channel_label(channel_index) + " (" + config.plot_scale + ")")
                    else:
                        image = None
                        colorbar = None
                    view["bbd_points"] = bbd_points
                    view["lambda_points"] = lambda_points
                    view["x_points"] = x_points
                    view["matrix_sum"] = matrix_sum
                    view["matrix_count"] = matrix_count
                    view["matrix"] = matrix
                    view["image"] = image
                    view["colorbar"] = colorbar
                self.plot_views[channel_index] = view

        def decorate_axis(self, axis, config, channel_index):
            axis.set_title(channel_label(channel_index))
            axis.set_xlabel(x_label_for_config(config))
            if config.measurement_type == MEASUREMENT_DOUBLE:
                axis.set_ylabel("Longitud de onda (nm)")
            else:
                axis.set_ylabel(channel_label(channel_index))
            axis.grid(True, color="#d5e2df", alpha=0.75)

        def on_point_acquired(self, row, repetition, acquired, total):
            if self.active_config is None:
                return
            for channel_index in self.plot_views:
                if self.active_config.measurement_type == MEASUREMENT_DOUBLE:
                    self.update_double_plot(channel_index, row)
                else:
                    self.update_curve_plot(channel_index, row, repetition)
            self.update_status_labels()

        def update_curve_plot(self, channel_index, row, repetition):
            view = self.plot_views[channel_index]
            axis = view["axis"]
            lines = view["lines"]
            if repetition not in lines:
                if self.active_config.repetitions > 1:
                    color = "#9aa8ad"
                    alpha = 0.72
                    label = "Rep " + str(repetition)
                    width = 1.35
                else:
                    color = "#0c8d7d"
                    alpha = 1.0
                    label = "Medicion"
                    width = 1.9
                line, = axis.plot(
                    [],
                    [],
                    marker="o",
                    markersize=3.0,
                    linewidth=width,
                    color=color,
                    alpha=alpha,
                    label=label,
                )
                lines[repetition] = {"line": line, "x": list(), "y": list()}
                if self.active_config.repetitions <= 6:
                    axis.legend(loc="best", fontsize=8)
            data = lines[repetition]
            y_value = value_for_channel_with_aux_map(
                row,
                channel_index,
                self.active_config,
                self.current_average_aux_value,
                self.current_average_aux_by_lambda,
            )
            if not np.isfinite(y_value):
                return
            data["x"].append(x_value_for_row(row, self.active_config))
            data["y"].append(y_value)
            data["line"].set_data(data["x"], data["y"])
            axis.relim()
            axis.autoscale_view()
            view["canvas"].draw_idle()

        def update_double_plot(self, channel_index, row):
            view = self.plot_views[channel_index]
            bbd_index = nearest_index(view.get("bbd_points", []), float(row[6]))
            lambda_index = nearest_index(view.get("lambda_points", []), float(row[7]))
            if bbd_index is None or lambda_index is None:
                return
            value = value_for_channel_with_aux_map(
                row,
                channel_index,
                self.active_config,
                self.current_average_aux_value,
                self.current_average_aux_by_lambda,
            )
            if not np.isfinite(value):
                return
            view["matrix_sum"][lambda_index, bbd_index] = view["matrix_sum"][lambda_index, bbd_index] + float(value)
            view["matrix_count"][lambda_index, bbd_index] = view["matrix_count"][lambda_index, bbd_index] + 1.0
            valid = view["matrix_count"] > 0
            view["matrix"][valid] = view["matrix_sum"][valid] / view["matrix_count"][valid]
            display_matrix = heatmap_display_matrix(view["matrix"], self.active_config.plot_scale)
            norm = heatmap_norm(view["matrix"], self.active_config.plot_scale)
            image = view.get("image")
            if image is None:
                return
            image.set_data(display_matrix)
            image.set_norm(norm)
            colorbar = view.get("colorbar")
            if colorbar is not None:
                colorbar.update_normal(image)
                colorbar.set_label(channel_label(channel_index) + " (" + self.active_config.plot_scale + ")")
            view["canvas"].draw_idle()

        def on_plot_scale_changed(self, *args):
            config = self.active_config
            if config is None:
                return
            if config.measurement_type != MEASUREMENT_DOUBLE:
                return
            config.plot_scale = self.plot_scale_combo.currentText()
            for channel_index in self.plot_views:
                view = self.plot_views[channel_index]
                image = view.get("image")
                if image is None:
                    continue
                display_matrix = heatmap_display_matrix(view["matrix"], config.plot_scale)
                norm = heatmap_norm(view["matrix"], config.plot_scale)
                image.set_data(display_matrix)
                image.set_norm(norm)
                colorbar = view.get("colorbar")
                if colorbar is not None:
                    colorbar.update_normal(image)
                    colorbar.set_label(channel_label(channel_index) + " (" + config.plot_scale + ")")
                view["canvas"].draw_idle()

        def add_average_overlay(self, result):
            if result.average_result is None or not result.average_result.get("ok", False):
                return
            if result.config.measurement_type == MEASUREMENT_DOUBLE:
                return
            rows = result.average_result.get("rows", [])
            for channel_index in self.plot_views:
                view = self.plot_views[channel_index]
                if view.get("average_added", False):
                    continue
                xs = list()
                ys = list()
                for row in rows:
                    y_value = value_for_channel_with_aux_map(
                        row,
                        channel_index,
                        result.config,
                        result.average_aux_value,
                        result.average_aux_by_lambda,
                    )
                    if not np.isfinite(y_value):
                        continue
                    xs.append(x_value_for_row(row, result.config))
                    ys.append(y_value)
                view["axis"].plot(xs, ys, color="#111111", linewidth=2.8, label="Promedio")
                view["axis"].legend(loc="best", fontsize=8)
                view["average_added"] = True
                view["canvas"].draw_idle()

        def show_message(self, title, text, icon):
            box = QMessageBox(self)
            box.setWindowTitle(title)
            box.setText(text)
            box.setIcon(icon)
            box.exec_()

        def closeEvent(self, event):
            if self.worker is not None:
                reply = QMessageBox.question(
                    self,
                    "Medicion activa",
                    "Hay una medicion activa. Cancelarla y cerrar?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    event.ignore()
                    return
                self.closing = True
                self.log("Cierre solicitado: cancelando medicion y liberando hardware")
                self.worker.cancel()
                if self.thread is not None:
                    finished = self.thread.wait(15000)
                    if not finished:
                        self.log("El hilo de medicion no termino aun; se mantiene la ventana abierta")
                        self.show_message(
                            "Cierre en espera",
                            "La medicion todavia no termino de liberar el hardware.\n\n"
                            "Espere unos segundos y vuelva a cerrar. Si la plataforma esta moviendose, puede tardar hasta que el controlador responda.",
                            QMessageBox.Warning,
                        )
                        self.closing = False
                        event.ignore()
                        return
                    self.thread = None
                    self.worker = None
            try:
                self.hardware.close()
            except Exception:
                pass
            event.accept()


def main():
    if QT_IMPORT_ERROR is not None:
        print("No pude importar PyQt5 o el backend Qt de Matplotlib.")
        print("Instalar PyQt5 en esta PC, por ejemplo: pip install PyQt5")
        print("Detalle: " + str(QT_IMPORT_ERROR))
        return 1
    app = QApplication(sys.argv)
    window = PumpProbeWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
