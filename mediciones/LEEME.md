# Mediciones

Acá se guardan los resultados de cada medición, una carpeta por sesión
(`AAAA-MM-DD_NNN/`) con `raw.csv`, `normalizado.csv`, `promedio.csv`,
`metadata.json`, `notes.txt`, `log.txt` y la subcarpeta `plots/` con los PNG.

El software escribe aquí automáticamente (`software/session_manager.py`).
La interfaz Tkinter antigua (`gui_tomas.py`) usa las subcarpetas `CSVs/` y `Plots/`.

El contenido de esta carpeta **no se versiona en git** (ver `.gitignore`):
hacé copias de respaldo por otro medio.
