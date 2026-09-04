import csv
import datetime
import os

import numpy as np


CHANNEL_COLUMNS = ["X", "Y", "R", "theta", "AUX", "frecuencia"]
POSITION_COLUMNS = ["posicion_smc_mm", "longitud_onda_nm"]
DATA_COLUMNS = CHANNEL_COLUMNS + POSITION_COLUMNS
RAW_COLUMNS = ["repeticion", "indice_punto"] + DATA_COLUMNS
AVERAGE_COLUMNS = (
    ["indice_punto", "posicion_smc_mm", "longitud_onda_nm"]
    + [name + "_promedio" for name in CHANNEL_COLUMNS]
    + ["n_repeticiones"]
)


def ensure_csv_extension(nombre_archivo):
    base, extension = os.path.splitext(nombre_archivo)
    if extension == "":
        return nombre_archivo + ".csv"
    return nombre_archivo


def add_suffix_to_filename(nombre_archivo, suffix):
    nombre_archivo = ensure_csv_extension(nombre_archivo)
    base, extension = os.path.splitext(nombre_archivo)
    return base + "_" + str(suffix) + extension


class AcquisitionDataManager:
    def __init__(self, carpeta_csv="CSVs"):
        self.carpeta_csv = carpeta_csv
        self._archivo_actual = None
        self._writer_actual = None
        self._filas_actuales = list()
        self._indice_punto_actual = 0
        self._repeticion_actual = 1
        self._ruta_actual = None
        self._metadata_actual = dict()

    def ruta_para(self, nombre_archivo):
        nombre_archivo = ensure_csv_extension(nombre_archivo)
        if os.path.isabs(nombre_archivo) or os.path.dirname(nombre_archivo):
            return nombre_archivo
        return os.path.join(self.carpeta_csv, nombre_archivo)

    def begin_run(self, nombre_archivo, metadata=None, repeticion=1):
        self.close_current()
        self._ruta_actual = self.ruta_para(nombre_archivo)
        carpeta = os.path.dirname(self._ruta_actual)
        if carpeta and not os.path.isdir(carpeta):
            os.makedirs(carpeta)
        self._archivo_actual = open(self._ruta_actual, "w", newline="", encoding="utf-8")
        self._writer_actual = csv.writer(self._archivo_actual)
        self._filas_actuales = list()
        self._indice_punto_actual = 0
        self._repeticion_actual = repeticion
        self._metadata_actual = dict(metadata or {})
        self._write_metadata(self._metadata_actual)
        self._writer_actual.writerow(RAW_COLUMNS)
        self._archivo_actual.flush()

    def begin_memory_run(self, nombre_archivo, metadata=None, repeticion=1):
        self.close_current()
        self._ruta_actual = self.ruta_para(nombre_archivo)
        self._archivo_actual = None
        self._writer_actual = None
        self._filas_actuales = list()
        self._indice_punto_actual = 0
        self._repeticion_actual = repeticion
        self._metadata_actual = dict(metadata or {})

    def append_row(self, vector_de_datos):
        if self._writer_actual is None and self._ruta_actual is None:
            self.begin_memory_run("medicion_sin_nombre.csv")
        fila = self._normalizar_fila(vector_de_datos)
        self._indice_punto_actual += 1
        if self._writer_actual is not None:
            self._writer_actual.writerow(
                [self._repeticion_actual, self._indice_punto_actual] + fila
            )
            self._archivo_actual.flush()
        self._filas_actuales.append([self._to_float(valor) for valor in fila])

    def finish_run(self):
        resultado = {
            "path": self._ruta_actual,
            "rows": list(self._filas_actuales),
            "repeticion": self._repeticion_actual,
            "metadata": dict(self._metadata_actual),
        }
        self.close_current()
        return resultado

    def close_current(self):
        if self._archivo_actual is not None:
            self._archivo_actual.close()
        self._archivo_actual = None
        self._writer_actual = None
        self._ruta_actual = None
        self._metadata_actual = dict()

    def save_run(self, run):
        ruta = run.get("path")
        if ruta is None:
            ruta = self.ruta_para("medicion_sin_nombre.csv")
        carpeta = os.path.dirname(ruta)
        if carpeta and not os.path.isdir(carpeta):
            os.makedirs(carpeta)
        metadata = dict(run.get("metadata") or {})
        metadata["tipo_archivo"] = "crudo"
        metadata["repeticion"] = run.get("repeticion", "")
        with open(ruta, "w", newline="", encoding="utf-8") as archivo:
            writer = csv.writer(archivo)
            self._write_metadata_to_writer(writer, metadata)
            writer.writerow(RAW_COLUMNS)
            indice = 1
            for fila in run.get("rows", []):
                writer.writerow([run.get("repeticion", ""), indice] + list(fila))
                indice = indice + 1
        return ruta

    def save_runs(self, runs, nombre_archivo=None, metadata=None):
        if nombre_archivo is not None:
            return [self.save_runs_combined(nombre_archivo, runs, metadata)]
        rutas = list()
        for run in runs:
            rutas.append(self.save_run(run))
        return rutas

    def save_runs_combined(self, nombre_archivo, runs, metadata=None):
        ruta = self.ruta_para(nombre_archivo)
        carpeta = os.path.dirname(ruta)
        if carpeta and not os.path.isdir(carpeta):
            os.makedirs(carpeta)
        metadata_crudo = dict(metadata or {})
        metadata_crudo["tipo_archivo"] = "crudo_repeticiones"
        metadata_crudo["n_repeticiones_guardadas"] = len(runs)

        with open(ruta, "w", newline="", encoding="utf-8") as archivo:
            writer = csv.writer(archivo)
            self._write_metadata_to_writer(writer, metadata_crudo)
            writer.writerow(RAW_COLUMNS)
            for run in runs:
                indice = 1
                repeticion = run.get("repeticion", "")
                for fila in run.get("rows", []):
                    writer.writerow([repeticion, indice] + list(fila))
                    indice = indice + 1
        return ruta

    def calculate_average(self, runs):
        validacion_ok, mensaje = self.validate_same_axis(runs)
        if not validacion_ok:
            return {"ok": False, "message": mensaje, "rows": list(), "path": None}
        matriz = np.array([run["rows"] for run in runs], dtype=float)
        promedio = np.mean(matriz, axis=0)
        return {
            "ok": True,
            "message": "Promedio calculado",
            "rows": promedio.tolist(),
            "path": None,
        }

    def save_average(self, nombre_archivo, runs, metadata=None):
        resultado_promedio = self.calculate_average(runs)
        if not resultado_promedio["ok"]:
            return resultado_promedio

        promedio = resultado_promedio["rows"]
        ruta = self.ruta_para(nombre_archivo)
        carpeta = os.path.dirname(ruta)
        if carpeta and not os.path.isdir(carpeta):
            os.makedirs(carpeta)

        metadata_promedio = dict(metadata or {})
        metadata_promedio["tipo_archivo"] = "promedio"
        metadata_promedio["n_repeticiones_promediadas"] = len(runs)

        with open(ruta, "w", newline="", encoding="utf-8") as archivo:
            writer = csv.writer(archivo)
            self._write_metadata_to_writer(writer, metadata_promedio)
            writer.writerow(AVERAGE_COLUMNS)
            for indice, fila in enumerate(promedio, start=1):
                writer.writerow(
                    [indice, fila[6], fila[7]]
                    + [fila[i] for i in range(0, len(CHANNEL_COLUMNS))]
                    + [len(runs)]
                )

        return {
            "ok": True,
            "message": "Promedio guardado",
            "rows": promedio,
            "path": ruta,
        }

    def validate_same_axis(self, runs, tolerancia=1e-9):
        if len(runs) < 2:
            return False, "Se necesita mas de una repeticion para calcular promedio."
        if any(len(run["rows"]) == 0 for run in runs):
            return False, "Una repeticion no tiene datos guardados."

        eje_referencia = np.array(
            [[fila[6], fila[7]] for fila in runs[0]["rows"]], dtype=float
        )
        for run in runs[1:]:
            eje = np.array([[fila[6], fila[7]] for fila in run["rows"]], dtype=float)
            if eje.shape != eje_referencia.shape:
                return (
                    False,
                    "Las repeticiones no tienen la misma cantidad de puntos.",
                )
            if not np.allclose(eje, eje_referencia, rtol=0, atol=tolerancia):
                return (
                    False,
                    "Las repeticiones no tienen exactamente el mismo eje de barrido.",
                )
        return True, "Ejes compatibles."

    def _write_metadata(self, metadata):
        self._write_metadata_to_writer(self._writer_actual, metadata)

    def _write_metadata_to_writer(self, writer, metadata):
        writer.writerow(["# metadata"])
        writer.writerow(["# fecha_hora", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        for clave, valor in metadata.items():
            writer.writerow(["# " + str(clave), self._format_metadata_value(valor)])
        writer.writerow([])

    def _normalizar_fila(self, vector_de_datos):
        fila = [str(valor) for valor in vector_de_datos]
        if len(fila) < len(DATA_COLUMNS):
            fila = fila + [""] * (len(DATA_COLUMNS) - len(fila))
        return fila[: len(DATA_COLUMNS)]

    def _format_metadata_value(self, valor):
        if isinstance(valor, (list, tuple)):
            return ";".join(str(item) for item in valor)
        return str(valor)

    def _to_float(self, valor):
        try:
            return float(valor)
        except (TypeError, ValueError):
            return float("nan")
