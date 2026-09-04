import datetime
import math
import os
import time

import numpy as np
from matplotlib.colors import LogNorm, Normalize, SymLogNorm
from matplotlib.figure import Figure

from acquisition_utils import AcquisitionDataManager
from session_manager import SessionManager


MEASUREMENT_LAMBDA_FIXED = "lambda_fixed"
MEASUREMENT_POSITION_FIXED = "position_fixed"
MEASUREMENT_DOUBLE = "double"
PLOT_SCALE_LINEAR = "Lineal"
PLOT_SCALE_LOG = "Log"
PLOT_SCALE_SYMLOG = "SimLog"

CHANNELS = [
    ("X", 0),
    ("Y", 1),
    ("R", 2),
    ("theta", 3),
    ("X/AUX", 4),
    ("R/AUX", 5),
]

RAW_CHANNEL_NAMES = ["X", "Y", "R", "theta", "AUX", "frecuencia"]


class MeasurementConfig:
    def __init__(self):
        self.measurement_type = MEASUREMENT_LAMBDA_FIXED
        self.bbd_sections = list()
        self.lambda_sections = list()
        self.channels = [1, 0, 1, 0, 0, 0]
        self.plot_channels = [1, 0, 1, 0, 0, 0]
        self.x_axis = "Distancia"
        self.plot_scale = PLOT_SCALE_LINEAR
        self.repetitions = 1
        self.average_repetitions = False
        self.auto_gain_enabled = True
        self.average_aux = False
        self.average_aux_seconds = 0
        self.notes = ""
        self.simulation_mode = True
        self.use_monochromator = True
        self.simulation_delay_scale = 0.05
        self.integration_time_override = None
        self.longitud_onda_fija_nm = 650.0
        self.posicion_fija_bbd_mm = 220.0
        self.session_path_preview = ""

    def selected_channel_indices(self):
        indices = list()
        for index in range(0, len(self.channels)):
            if self.channels[index]:
                indices.append(index)
        return indices

    def selected_plot_channel_indices(self):
        indices = list()
        for index in range(0, len(self.plot_channels)):
            if self.plot_channels[index]:
                indices.append(index)
        return indices

    def to_dict(self):
        return {
            "measurement_type": self.measurement_type,
            "bbd_sections": self.bbd_sections,
            "lambda_sections": self.lambda_sections,
            "channels": self.channels,
            "plot_channels": self.plot_channels,
            "x_axis": self.x_axis,
            "plot_scale": self.plot_scale,
            "repetitions": self.repetitions,
            "average_repetitions": self.average_repetitions,
            "auto_gain_enabled": self.auto_gain_enabled,
            "auto_gain_mode": "manual_sens_only",
            "average_aux": self.average_aux,
            "average_aux_seconds": self.average_aux_seconds,
            "simulation_mode": self.simulation_mode,
            "use_monochromator": self.use_monochromator,
            "simulation_delay_scale": self.simulation_delay_scale,
            "integration_time_override": self.integration_time_override,
            "longitud_onda_fija_nm": self.longitud_onda_fija_nm,
            "posicion_fija_bbd_mm": self.posicion_fija_bbd_mm,
        }


class MeasurementResult:
    def __init__(self, config):
        self.config = config
        self.runs = list()
        self.average_result = None
        self.cancelled = False
        self.error_message = ""
        self.metadata = dict()
        self.started_at = None
        self.finished_at = None
        self.total_points = 0
        self.acquired_points = 0
        self.average_aux_value = 0
        self.average_aux_by_lambda = dict()

    def has_data(self):
        for run in self.runs:
            if len(run.get("rows", [])) > 0:
                return True
        return False


def channel_label(index):
    if index >= 0 and index < len(CHANNELS):
        return CHANNELS[index][0]
    return "canal"


def safe_channel_name(index):
    names = ["X", "Y", "R", "theta", "X_AUX", "R_AUX"]
    if index >= 0 and index < len(names):
        return names[index]
    return "canal"


def validate_sections(sections, label):
    errors = list()
    if sections is None or len(sections) == 0:
        errors.append(label + ": falta definir al menos una seccion.")
        return errors
    for index in range(0, len(sections)):
        section = sections[index]
        if len(section) != 3:
            errors.append(label + ": seccion " + str(index + 1) + " incompleta.")
            continue
        start_value = section[0]
        end_value = section[1]
        step_value = section[2]
        if step_value == 0:
            errors.append(label + ": el paso de la seccion " + str(index + 1) + " es cero.")
            continue
        delta = end_value - start_value
        if delta == 0:
            errors.append(label + ": la seccion " + str(index + 1) + " tiene rango vacio.")
            continue
        if delta * step_value < 0:
            errors.append(label + ": el signo del paso no lleva del inicio al final en la seccion " + str(index + 1) + ".")
    return errors


def generate_points(sections, decimals):
    points = list()
    for section in sections:
        start_value = section[0]
        end_value = section[1]
        step_value = section[2]
        count = int(abs(round((end_value - start_value) / step_value, 6)))
        section_points = list()
        for index in range(0, count + 1):
            section_points.append(round(start_value + index * step_value, decimals))
        if len(points) > 0 and len(section_points) > 0:
            if abs(points[-1] - section_points[0]) < 1e-9:
                points.extend(section_points[1:])
            else:
                points.extend(section_points)
        else:
            points.extend(section_points)
    return points


def validate_measurement_config(config, hardware_status):
    errors = list()
    if len(config.selected_channel_indices()) == 0:
        errors.append("Seleccionar al menos un canal para graficar.")
    if config.repetitions < 1:
        errors.append("La cantidad de repeticiones debe ser mayor o igual a 1.")
    if config.average_aux and config.average_aux_seconds <= 0:
        errors.append("Promediar AUX requiere un tiempo mayor a cero.")

    if config.measurement_type == MEASUREMENT_LAMBDA_FIXED:
        errors.extend(validate_sections(config.bbd_sections, "BBD"))
    elif config.measurement_type == MEASUREMENT_POSITION_FIXED:
        errors.extend(validate_sections(config.lambda_sections, "Lambda"))
    elif config.measurement_type == MEASUREMENT_DOUBLE:
        errors.extend(validate_sections(config.bbd_sections, "BBD"))
        errors.extend(validate_sections(config.lambda_sections, "Lambda"))
    else:
        errors.append("Tipo de medicion desconocido.")

    if not config.simulation_mode:
        if not hardware_status.get("bbd_connected", False):
            errors.append("La plataforma BBD no esta conectada.")
        mono_required = True
        if config.measurement_type == MEASUREMENT_LAMBDA_FIXED and not config.use_monochromator:
            mono_required = False
        if mono_required and not hardware_status.get("mono_connected", False):
            errors.append("El monocromador no esta conectado.")
        if not hardware_status.get("lockin_connected", False):
            errors.append("El Lock-in no esta conectado.")
    return errors


def points_for_config(config):
    bbd_points = list()
    lambda_points = list()
    if config.measurement_type in (MEASUREMENT_LAMBDA_FIXED, MEASUREMENT_DOUBLE):
        bbd_points = generate_points(config.bbd_sections, 6)
    if config.measurement_type in (MEASUREMENT_POSITION_FIXED, MEASUREMENT_DOUBLE):
        lambda_points = generate_points(config.lambda_sections, 4)
    if config.measurement_type == MEASUREMENT_LAMBDA_FIXED:
        return bbd_points, [config.longitud_onda_fija_nm], len(bbd_points)
    if config.measurement_type == MEASUREMENT_POSITION_FIXED:
        return [config.posicion_fija_bbd_mm], lambda_points, len(lambda_points)
    return bbd_points, lambda_points, len(bbd_points) * len(lambda_points)


def estimate_seconds(config, hardware_status):
    bbd_points, lambda_points, point_count = points_for_config(config)
    integration_time = config.integration_time_override
    if integration_time is None:
        integration_time = hardware_status.get("integration_time", 0.0)
    try:
        integration_time = float(integration_time)
    except Exception:
        integration_time = 0.0
    seconds = point_count * integration_time * config.repetitions
    if config.average_aux:
        seconds = seconds + len(lambda_points) * config.average_aux_seconds * config.repetitions
    if getattr(config, "auto_gain_enabled", False):
        seconds = seconds + len(lambda_points) * 1.0 * config.repetitions
    if config.measurement_type in (MEASUREMENT_LAMBDA_FIXED, MEASUREMENT_DOUBLE):
        seconds = seconds + max(0, len(bbd_points) - 1) * 0.1 * config.repetitions
    if config.measurement_type in (MEASUREMENT_POSITION_FIXED, MEASUREMENT_DOUBLE):
        seconds = seconds + max(0, len(lambda_points) - 1) * 0.1 * config.repetitions
    if config.simulation_mode:
        seconds = seconds * max(0.0, float(config.simulation_delay_scale))
    return seconds


def format_seconds(seconds):
    seconds = int(round(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    rest = seconds % 60
    return str(hours) + " h " + str(minutes) + " m " + str(rest) + " s"


def build_preview(config, hardware_status, session_manager=None):
    if session_manager is None:
        session_manager = SessionManager()
    bbd_points, lambda_points, point_count = points_for_config(config)
    estimated = estimate_seconds(config, hardware_status)
    session_path = session_manager.next_session_path()
    return {
        "tipo": config.measurement_type,
        "puntos_por_repeticion": point_count,
        "repeticiones": config.repetitions,
        "puntos_totales": point_count * config.repetitions,
        "tiempo_estimado_s": estimated,
        "tiempo_estimado_texto": format_seconds(estimated),
        "bbd_puntos": len(bbd_points),
        "lambda_puntos": len(lambda_points),
        "carpeta_sesion": session_path,
        "archivos": "raw.csv, metadata.json, notes.txt, log.txt, plots/*.png",
    }


def value_for_channel(row, channel_index, average_aux_enabled, average_aux_value):
    if channel_index < 4:
        return float(row[channel_index])
    aux = aux_for_row(row, average_aux_enabled, average_aux_value, None)
    if aux == 0:
        return float("nan")
    if channel_index == 4:
        return float(row[0]) / aux
    return float(row[2]) / aux


def lambda_key(value):
    return str(round(float(value), 6))


def aux_for_row(row, average_aux_enabled, average_aux_value, average_aux_by_lambda=None):
    if average_aux_enabled:
        try:
            row_aux = float(row[4])
            if np.isfinite(row_aux) and row_aux != 0:
                return row_aux
        except Exception:
            pass
        if average_aux_by_lambda is not None and len(row) >= 8:
            key = lambda_key(row[7])
            if key in average_aux_by_lambda:
                return float(average_aux_by_lambda[key])
        return float(average_aux_value)
    return float(row[4])


def value_for_channel_with_aux_map(row, channel_index, config, average_aux_value, average_aux_by_lambda):
    if channel_index < 4:
        return float(row[channel_index])
    aux = aux_for_row(row, config.average_aux, average_aux_value, average_aux_by_lambda)
    if aux == 0:
        return float("nan")
    if channel_index == 4:
        return float(row[0]) / aux
    return float(row[2]) / aux


def x_value_for_row(row, config):
    if config.measurement_type == MEASUREMENT_POSITION_FIXED:
        return float(row[7])
    if config.x_axis == "Tiempo":
        return x_value_from_position(float(row[6]), config)
    return x_value_from_position(float(row[6]), config)


def x_label_for_config(config):
    if config.measurement_type == MEASUREMENT_POSITION_FIXED:
        return "Longitud de onda (nm)"
    if config.x_axis == "Tiempo":
        return "Retardo (ps)"
    return "Retardo (mm)"


def x_value_from_position(position, config):
    if config.x_axis == "Tiempo":
        return float(position) * (2.0 / 3.0) * 10.0
    return float(position)


def nearest_index(values, value):
    if values is None or len(values) == 0:
        return None
    best_index = 0
    best_distance = abs(float(values[0]) - float(value))
    for index in range(1, len(values)):
        distance = abs(float(values[index]) - float(value))
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def axis_edges(values):
    if values is None or len(values) == 0:
        return [0.0, 1.0]
    if len(values) == 1:
        center = float(values[0])
        return [center - 0.5, center + 0.5]
    edges = list()
    first_delta = float(values[1]) - float(values[0])
    edges.append(float(values[0]) - first_delta / 2.0)
    for index in range(0, len(values) - 1):
        edges.append((float(values[index]) + float(values[index + 1])) / 2.0)
    last_delta = float(values[-1]) - float(values[-2])
    edges.append(float(values[-1]) + last_delta / 2.0)
    return edges


def heatmap_display_matrix(matrix, scale):
    display_matrix = np.array(matrix, dtype=float)
    if scale == PLOT_SCALE_LOG:
        display_matrix[display_matrix <= 0] = np.nan
    return display_matrix


def heatmap_norm(matrix, scale):
    display_matrix = heatmap_display_matrix(matrix, scale)
    finite = display_matrix[np.isfinite(display_matrix)]
    if finite.size == 0:
        if scale == PLOT_SCALE_LOG:
            return LogNorm(vmin=1e-12, vmax=1.0)
        if scale == PLOT_SCALE_SYMLOG:
            return SymLogNorm(linthresh=1e-9, vmin=-1.0, vmax=1.0)
        return Normalize(vmin=0.0, vmax=1.0)
    if scale == PLOT_SCALE_LOG:
        positive = finite[finite > 0]
        if positive.size == 0:
            return LogNorm(vmin=1e-12, vmax=1.0)
        vmin = float(np.nanmin(positive))
        vmax = float(np.nanmax(positive))
        if vmin <= 0:
            vmin = 1e-12
        if vmax <= vmin:
            vmax = vmin * 10.0
        return LogNorm(vmin=vmin, vmax=vmax)
    if scale == PLOT_SCALE_SYMLOG:
        max_abs = float(np.nanmax(np.abs(finite)))
        if max_abs <= 0:
            max_abs = 1.0
        linthresh = max(max_abs * 1e-3, 1e-12)
        return SymLogNorm(linthresh=linthresh, vmin=-max_abs, vmax=max_abs)
    vmin = float(np.nanmin(finite))
    vmax = float(np.nanmax(finite))
    if vmax == vmin:
        vmax = vmin + 1.0
    return Normalize(vmin=vmin, vmax=vmax)


def heatmap_grid_from_rows(rows, config, channel_index, average_aux_value=0, average_aux_by_lambda=None):
    bbd_points, lambda_points, point_count = points_for_config(config)
    x_points = [x_value_from_position(position, config) for position in bbd_points]
    matrix_sum = np.zeros((len(lambda_points), len(bbd_points)), dtype=float)
    matrix_count = np.zeros((len(lambda_points), len(bbd_points)), dtype=float)
    matrix = np.full((len(lambda_points), len(bbd_points)), np.nan, dtype=float)

    for row in rows:
        if len(row) < 8:
            continue
        bbd_index = nearest_index(bbd_points, float(row[6]))
        lambda_index = nearest_index(lambda_points, float(row[7]))
        if bbd_index is None or lambda_index is None:
            continue
        value = value_for_channel_with_aux_map(row, channel_index, config, average_aux_value, average_aux_by_lambda)
        if not np.isfinite(value):
            continue
        matrix_sum[lambda_index, bbd_index] = matrix_sum[lambda_index, bbd_index] + float(value)
        matrix_count[lambda_index, bbd_index] = matrix_count[lambda_index, bbd_index] + 1.0

    valid = matrix_count > 0
    matrix[valid] = matrix_sum[valid] / matrix_count[valid]
    return x_points, lambda_points, matrix


def heatmap_extent(x_points, y_points):
    x_edges = axis_edges(x_points)
    y_edges = axis_edges(y_points)
    return [x_edges[0], x_edges[-1], y_edges[0], y_edges[-1]]


class AcquisitionRunner:
    def __init__(self, hardware, config, callbacks=None):
        self.hardware = hardware
        self.config = config
        self.callbacks = callbacks or {}
        self.cancel_requested = False
        self.data_manager = AcquisitionDataManager(".")

    def cancel(self):
        self.cancel_requested = True
        try:
            self.hardware.stop_all()
        except Exception:
            pass

    def emit(self, name, *args):
        callback = self.callbacks.get(name)
        if callback is not None:
            callback(*args)

    def sleep_cancellable(self, seconds):
        if seconds is None:
            seconds = 0
        seconds = max(0.0, float(seconds))
        if self.config.simulation_mode:
            seconds = seconds * max(0.0, float(self.config.simulation_delay_scale))
        end_time = time.time() + seconds
        while time.time() < end_time:
            if self.cancel_requested:
                return False
            remaining = end_time - time.time()
            if remaining > 0.05:
                time.sleep(0.05)
            elif remaining > 0:
                time.sleep(remaining)
        return not self.cancel_requested

    def move_bbd(self, position):
        if self.cancel_requested:
            return False
        delay = self.hardware.calculate_bbd_sleep(position)
        self.hardware.move_bbd(position)
        self.emit("status", "BBD -> " + str(round(float(position), 6)) + " mm")
        return self.sleep_cancellable(delay)

    def move_mono(self, wavelength):
        if self.cancel_requested:
            return False
        delay = self.hardware.calculate_mono_sleep(wavelength)
        self.hardware.move_mono(wavelength)
        self.emit("status", "Lambda -> " + str(round(float(wavelength), 4)) + " nm")
        return self.sleep_cancellable(delay)

    def acquire_point(self, result, repetition, point_index, total_points):
        if self.cancel_requested:
            return False
        integration_time = self.config.integration_time_override
        if integration_time is None:
            integration_time = self.hardware.integration_time()
        if not self.sleep_cancellable(integration_time):
            return False
        if self.cancel_requested:
            return False
        row = self.hardware.acquire_row()
        if self.config.measurement_type == MEASUREMENT_LAMBDA_FIXED and not self.config.use_monochromator:
            if len(row) < 8:
                row = list(row) + [0.0] * (8 - len(row))
            row[7] = float(self.config.longitud_onda_fija_nm)
        if self.config.average_aux:
            row = list(row)
            row[4] = float(result.average_aux_value)
        self.data_manager.append_row(row)
        result.acquired_points = result.acquired_points + 1
        self.emit("point", row, repetition, result.acquired_points, total_points)
        self.emit("progress", result.acquired_points, total_points)
        self.emit("log", "Punto " + str(result.acquired_points) + "/" + str(total_points) + " adquirido")
        return True

    def calculate_average_aux(self, wavelength=None):
        if not self.config.average_aux:
            return 0
        duration = float(self.config.average_aux_seconds)
        if duration <= 0:
            return 0
        measured = 0
        accum = 0.0
        if wavelength is None:
            self.emit("log", "Promediando AUX")
        else:
            self.emit("log", "Promediando AUX para lambda " + str(round(float(wavelength), 4)) + " nm")
        end_time = time.time() + duration
        while time.time() < end_time:
            if self.cancel_requested:
                break
            try:
                row = self.hardware.acquire_row()
                accum = accum + float(row[4])
                measured = measured + 1
            except Exception as exc:
                self.emit("log", "Lectura AUX fallida durante promedio: " + str(exc))
            if not self.sleep_cancellable(1.0 / 20.0):
                break
        if measured == 0:
            return 0
        return round(accum / measured, 6)

    def update_average_aux_for_lambda(self, result, wavelength):
        if not self.config.average_aux:
            return True
        if self.cancel_requested:
            return False
        average = self.calculate_average_aux(wavelength)
        if self.cancel_requested:
            return False
        result.average_aux_value = average
        result.average_aux_by_lambda[lambda_key(wavelength)] = average
        self.emit("aux_average", average)
        self.emit("log", "AUX promedio lambda " + str(round(float(wavelength), 4)) + " nm = " + str(average))
        return True

    def maybe_auto_gain_for_lambda(self, wavelength):
        if not getattr(self.config, "auto_gain_enabled", False):
            return True
        if self.cancel_requested:
            return False
        integration_time = self.hardware.integration_time()
        try:
            integration_time = float(integration_time)
        except Exception:
            integration_time = 0.0
        try:
            self.emit("log", "Auto rango sensibilidad para lambda " + str(round(float(wavelength), 4)) + " nm")
            result = self.hardware.autorange_lockin_sensitivity()
            if result.get("changed", False):
                self.emit(
                    "log",
                    "Sensibilidad Lock-in: "
                    + str(result.get("old_index"))
                    + " -> "
                    + str(result.get("new_index"))
                    + " (R="
                    + str(round(float(result.get("r", 0.0)), 9))
                    + ")",
                )
                wait_time = max(0.2, min(2.0, 2.0 * integration_time))
                return self.sleep_cancellable(wait_time)
            self.emit("log", "Sensibilidad Lock-in sin cambios")
            return True
        except Exception as exc:
            self.emit("log", "Auto rango sensibilidad fallo y se continua: " + str(exc))
            return True

    def run(self):
        result = MeasurementResult(self.config)
        result.started_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            bbd_points, lambda_points, point_count = points_for_config(self.config)
            result.total_points = point_count * self.config.repetitions
            result.average_aux_value = 0
            self.emit("aux_average", result.average_aux_value)
            if self.cancel_requested:
                result.cancelled = True
            else:
                metadata_base = self.build_metadata(result)
                self.emit("log", "Inicio de medicion")
                self.emit("progress", 0, result.total_points)

                for repetition in range(1, self.config.repetitions + 1):
                    if self.cancel_requested:
                        result.cancelled = True
                        break
                    metadata_run = dict(metadata_base)
                    metadata_run["repeticion"] = repetition
                    self.data_manager.begin_memory_run("raw.csv", metadata_run, repetition)
                    self.emit("status", "Repeticion " + str(repetition) + " de " + str(self.config.repetitions))
                    self.run_repetition(result, repetition, bbd_points, lambda_points)
                    run = self.data_manager.finish_run()
                    if len(run.get("rows", [])) > 0:
                        result.runs.append(run)
                    if self.cancel_requested:
                        result.cancelled = True
                        break
                if (not result.cancelled) and self.config.average_repetitions and len(result.runs) > 1:
                    result.average_result = self.data_manager.calculate_average(result.runs)
                    if result.average_result.get("ok", False):
                        self.emit("log", "Promedio calculado")
                    else:
                        self.emit("log", "Promedio no calculado: " + result.average_result.get("message", ""))
        except Exception as exc:
            try:
                partial_run = self.data_manager.finish_run()
                if len(partial_run.get("rows", [])) > 0:
                    result.runs.append(partial_run)
            except Exception:
                pass
            result.error_message = str(exc)
            self.emit("error", str(exc))
        result.finished_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result.metadata = self.build_metadata(result)
        if result.cancelled:
            self.emit("log", "Medicion cancelada")
        elif result.error_message:
            self.emit("log", "Medicion con error")
        else:
            self.emit("log", "Medicion finalizada")
        return result

    def run_repetition(self, result, repetition, bbd_points, lambda_points):
        if self.config.measurement_type == MEASUREMENT_LAMBDA_FIXED:
            if self.config.use_monochromator:
                if not self.move_mono(self.config.longitud_onda_fija_nm):
                    self.cancel()
                    return
            else:
                self.emit("log", "SMS desactivado: se usa lambda fija manual " + str(self.config.longitud_onda_fija_nm) + " nm")
            if not self.maybe_auto_gain_for_lambda(self.config.longitud_onda_fija_nm):
                self.cancel()
                return
            if not self.update_average_aux_for_lambda(result, self.config.longitud_onda_fija_nm):
                self.cancel()
                return
            for position in bbd_points:
                if not self.move_bbd(position):
                    self.cancel()
                    return
                if not self.acquire_point(result, repetition, 0, result.total_points):
                    self.cancel()
                    return
        elif self.config.measurement_type == MEASUREMENT_POSITION_FIXED:
            if not self.move_bbd(self.config.posicion_fija_bbd_mm):
                self.cancel()
                return
            for wavelength in lambda_points:
                if not self.move_mono(wavelength):
                    self.cancel()
                    return
                if not self.maybe_auto_gain_for_lambda(wavelength):
                    self.cancel()
                    return
                if not self.update_average_aux_for_lambda(result, wavelength):
                    self.cancel()
                    return
                if not self.acquire_point(result, repetition, 0, result.total_points):
                    self.cancel()
                    return
        elif self.config.measurement_type == MEASUREMENT_DOUBLE:
            for wavelength in lambda_points:
                if not self.move_mono(wavelength):
                    self.cancel()
                    return
                if not self.maybe_auto_gain_for_lambda(wavelength):
                    self.cancel()
                    return
                if not self.update_average_aux_for_lambda(result, wavelength):
                    self.cancel()
                    return
                for position in bbd_points:
                    if not self.move_bbd(position):
                        self.cancel()
                        return
                    if not self.acquire_point(result, repetition, 0, result.total_points):
                        self.cancel()
                        return

    def build_metadata(self, result):
        status = self.hardware.status()
        metadata = {
            "version_gui": "pyqt_v1",
            "config": self.config.to_dict(),
            "hardware_status": status,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "cancelled": result.cancelled,
            "error_message": result.error_message,
            "total_points": result.total_points,
            "acquired_points": result.acquired_points,
            "average_aux_value": result.average_aux_value,
            "average_aux_by_lambda": result.average_aux_by_lambda,
            "aux_column_meaning": "AUX promedio usado para normalizacion" if self.config.average_aux else "AUX instantaneo leido en cada punto",
        }
        return metadata


def save_measurement_result(result, notes, log_lines, selected_plot_channels=None, session_manager=None, preferred_path=None):
    if session_manager is None:
        session_manager = SessionManager()
    paths = session_manager.create_session(preferred_path)
    data_manager = AcquisitionDataManager(paths.root_path)
    metadata = dict(result.metadata)
    metadata["saved_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata["session_path"] = paths.root_path
    raw_paths = data_manager.save_runs(result.runs, "raw.csv", metadata)
    average_path = None
    average_rows = None
    if result.average_result is not None and result.average_result.get("ok", False):
        saved_average = data_manager.save_average("promedio.csv", result.runs, metadata)
        if saved_average.get("ok", False):
            average_path = saved_average.get("path")
            average_rows = saved_average.get("rows")
    if selected_plot_channels is None:
        selected_plot_channels = result.config.selected_plot_channel_indices()
    plot_paths = save_result_plots(result, paths.plots_path, selected_plot_channels, average_rows)
    session_manager.write_session_files(paths, metadata, notes, log_lines)
    return {
        "session_path": paths.root_path,
        "raw_paths": raw_paths,
        "average_path": average_path,
        "plot_paths": plot_paths,
        "metadata_path": paths.metadata_json,
        "notes_path": paths.notes_txt,
        "log_path": paths.log_txt,
    }


def save_result_plots(result, plots_path, selected_plot_channels, average_rows=None):
    if not os.path.isdir(plots_path):
        os.makedirs(plots_path)
    paths = list()
    for channel_index in selected_plot_channels:
        if result.config.measurement_type == MEASUREMENT_DOUBLE:
            path = save_double_plot(result, plots_path, channel_index, average_rows)
        else:
            path = save_curve_plot(result, plots_path, channel_index, average_rows)
        paths.append(path)
    return paths


def save_curve_plot(result, plots_path, channel_index, average_rows=None):
    name = safe_channel_name(channel_index)
    if average_rows is not None:
        filename = "promedio_" + name + ".png"
    else:
        filename = name + ".png"
    path = os.path.join(plots_path, filename)
    fig = Figure(figsize=(7.5, 5.0))
    ax = fig.add_subplot(111)
    gray = "#c9d0d4"
    for run in result.runs:
        xs = list()
        ys = list()
        for row in run.get("rows", []):
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
        if len(result.runs) == 1 and average_rows is None:
            ax.plot(xs, ys, marker="o", markersize=3.0, linewidth=1.8, color="#008f7a", label="Medicion")
        else:
            ax.plot(xs, ys, marker="o", markersize=2.2, linewidth=1.0, color=gray, alpha=0.75)
    if average_rows is not None:
        xs = list()
        ys = list()
        for row in average_rows:
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
        ax.plot(xs, ys, "k-", linewidth=2.8, label="Promedio")
        ax.legend(loc="best", fontsize=9)
    elif len(result.runs) > 1:
        ax.plot([], [], color=gray, linewidth=1.5, label="Repeticiones")
        ax.legend(loc="best", fontsize=9)
    ax.set_xlabel(x_label_for_config(result.config))
    ax.set_ylabel(channel_label(channel_index))
    ax.grid(True, color="#d5dde3", alpha=0.65)
    fig.tight_layout()
    fig.savefig(path, dpi=220)
    return path


def save_double_plot(result, plots_path, channel_index, average_rows=None):
    name = safe_channel_name(channel_index)
    if average_rows is not None:
        filename = "promedio_" + name + ".png"
        rows = average_rows
    else:
        filename = name + ".png"
        rows = list()
        for run in result.runs:
            rows.extend(run.get("rows", []))
    path = os.path.join(plots_path, filename)
    x_points, y_points, matrix = heatmap_grid_from_rows(
        rows,
        result.config,
        channel_index,
        result.average_aux_value,
        result.average_aux_by_lambda,
    )
    scale = getattr(result.config, "plot_scale", PLOT_SCALE_LINEAR)
    display_matrix = heatmap_display_matrix(matrix, scale)
    norm = heatmap_norm(matrix, scale)
    fig = Figure(figsize=(7.5, 5.0))
    ax = fig.add_subplot(111)
    if len(x_points) > 0 and len(y_points) > 0:
        image = ax.imshow(
            display_matrix,
            origin="lower",
            aspect="auto",
            extent=heatmap_extent(x_points, y_points),
            cmap="viridis",
            norm=norm,
            interpolation="nearest",
        )
        colorbar = fig.colorbar(image, ax=ax)
        colorbar.set_label(channel_label(channel_index) + " (" + scale + ")")
    ax.set_xlabel(x_label_for_config(result.config))
    ax.set_ylabel("Longitud de onda (nm)")
    ax.set_title(channel_label(channel_index))
    ax.grid(True, color="#d5dde3", alpha=0.65)
    fig.tight_layout()
    fig.savefig(path, dpi=220)
    return path
