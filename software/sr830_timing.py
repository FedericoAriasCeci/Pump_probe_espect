"""SR830 low-pass timing, in seconds (SRS manual, sections 3-25 and 5-6).

https://www.thinksrs.com/downloads/PDFs/Manuals/SR830m.pdf
N is the TOTAL number of time constants, independent of filter order.
"""

import math


TIME_CONSTANT_SECONDS = (
    10e-6, 30e-6, 100e-6, 300e-6, 1e-3, 3e-3, 10e-3, 30e-3,
    100e-3, 300e-3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0,
    1000.0, 3000.0, 10000.0, 30000.0,
)
FILTER_SLOPES = (6, 12, 18, 24)
RECOMMENDED_FACTORS = (5.0, 7.0, 9.0, 10.0)


def parameter_index(value, count, command):
    try:
        index = int(str(value).strip())
    except (ValueError, TypeError) as exc:
        raise ValueError("Respuesta SR830 invalida para " + command + ": " + str(value)) from exc
    if not 0 <= index < count:
        raise ValueError("Indice SR830 fuera de rango para " + command + ": " + str(value))
    return index


def time_constant_seconds(index):
    return TIME_CONSTANT_SECONDS[parameter_index(index, 20, "OFLT?")]


def filter_settings(time_constant_index, slope_index):
    oflt = parameter_index(time_constant_index, 20, "OFLT?")
    ofsl = parameter_index(slope_index, 4, "OFSL?")
    return {
        "time_constant_index": oflt,
        "time_constant_seconds": time_constant_seconds(oflt),
        "slope_index": ofsl,
        "slope_db_oct": FILTER_SLOPES[ofsl],
        "recommended_settling_factor": RECOMMENDED_FACTORS[ofsl],
    }


def query_filter_settings(address):
    return filter_settings(address.query("OFLT?"), address.query("OFSL?"))


def settling_seconds(factor, tau_seconds):
    factor = float(factor)
    tau_seconds = float(tau_seconds)
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError("N debe ser finito y mayor a cero.")
    if not math.isfinite(tau_seconds) or tau_seconds <= 0:
        raise ValueError("La constante de tiempo debe ser finita y mayor a cero (s).")
    seconds = factor * tau_seconds
    if not math.isfinite(seconds):
        raise ValueError("El tiempo de estabilizacion excede el rango permitido.")
    return seconds
