"""DC from SR830 AUX IN 1 and voltage ratios; no instrument configuration."""

import csv
import math


DC_INPUT = "SR830 AUX IN 1"
DC_INSTANTANEOUS_COLUMN = "DC_instantanea_V"
DC_CHANNEL_INDEX = 6
DC_SAMPLE_INTERVAL_SECONDS = 0.05
DC_EXTRA_COLUMNS = [
    DC_INSTANTANEOUS_COLUMN, "DC_muestras", "DC_desvio_V",
    "DC_duracion_s", "DC_muestras_invalidas",
]


class DCStatistics:
    """Online sample statistics; an invalid input invalidates the whole mean.

    Zero is a legitimate sample (but a zero mean cannot normalize a signal).
    The standard deviation is a sample deviation, not a standard error.
    """

    def __init__(self):
        self.count = 0
        self.invalid_count = 0
        self.mean = 0.0
        self.m2 = 0.0

    def add(self, value):
        self.count += 1
        value = float(value)
        if not math.isfinite(value) or abs(value) >= 10.5:
            self.invalid_count += 1
            return
        valid_count = self.count - self.invalid_count
        delta = value - self.mean
        self.mean += delta / valid_count
        self.m2 += delta * (value - self.mean)

    def summary(self, duration):
        usable = self.count > 0 and self.invalid_count == 0
        return {
            "mean": self.mean if usable else float("nan"),
            "count": self.count,
            "std": math.sqrt(max(0.0, self.m2) / (self.count - 1))
            if usable and self.count > 1 else float("nan"),
            "duration": duration,
            "invalid_count": self.invalid_count,
        }


def measured_dc(row):
    # New PyQt rows preserve the instantaneous AUX value after the old 8 fields.
    return float(row[8] if len(row) > 8 else row[4])


def valid_dc(value):
    try:
        value = float(value)
        return math.isfinite(value) and 0 < abs(value) < 10.5
    except (TypeError, ValueError, OverflowError):
        return False


def normalize_by_dc(signal, dc):
    if not valid_dc(dc):
        return float("nan")
    try:
        value = float(signal) / float(dc)
        return value if math.isfinite(value) else float("nan")
    except (TypeError, ValueError, OverflowError):
        return float("nan")


def save_normalized_csv(path, runs):
    """Save each point's ratios and both measured and used DC voltages."""
    columns = [
        "repeticion", "indice_punto", "posicion_smc_mm", "longitud_onda_nm",
        "X_V", "Y_V", "R_V", DC_INSTANTANEOUS_COLUMN, "DC_normalizacion_V",
        "X_DC", "Y_DC", "R_DC", "DC_valida",
    ] + DC_EXTRA_COLUMNS[1:]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for run in runs:
            for index, row in enumerate(run.get("rows", []), start=1):
                dc = float(row[4])
                statistics = list(row[9:13]) if len(row) > 9 else [""] * 4
                writer.writerow([
                    run.get("repeticion", ""), index, row[6], row[7],
                    row[0], row[1], row[2], measured_dc(row), dc,
                    normalize_by_dc(row[0], dc), normalize_by_dc(row[1], dc),
                    normalize_by_dc(row[2], dc), valid_dc(dc),
                ] + statistics)
    return path
