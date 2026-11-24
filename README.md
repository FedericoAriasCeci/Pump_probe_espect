# Pump-probe con espectrómetro HORIBA iHR320

Software de adquisición pump-probe (lock-in SR830, plataforma de retardo
Thorlabs BBD301 y monocromador HORIBA iHR320).

## Estructura

```
Pump_probe_espect_iHR320/
├── software/            Código del programa (versionado en git)
│   ├── Iniciar_mediciones.bat   Lanzador de la interfaz PyQt
│   ├── gui_pyqt.py              Interfaz principal
│   ├── acquisition_service.py, hardware_adapter.py, hardware_tier.py, ...
│   ├── settling_settings.ini, data*.txt   Configuración que usa el programa
│   ├── docs/            Notas técnicas (SR830, HORIBA EzSpec, iHR320)
│   └── tests/           Pruebas automáticas
└── mediciones/          Resultados de cada medición y sus plots (no se versiona)
```

## Uso

- Medir: doble clic en `software\Iniciar_mediciones.bat` (entorno conda `pump_probe_gui`).
- Cada medición crea `mediciones\AAAA-MM-DD_NNN\` con los CSV, metadatos y `plots\`.
- Probar el driver HORIBA EzSpec: `software\Probar_HORIBA_EzSpec.bat` (ver `software\docs\HORIBA_EZSPEC.md`).
- Pruebas automáticas, desde `software\`: `python -m unittest discover`

## Notas

- `horiba_monochromator.py` usa el puente `HoribaBridge`, que ya no forma parte
  de este repositorio. Los barridos en longitud de onda desde la GUI necesitan
  ese puente o la integración del driver nuevo `horiba_ezspec.py`.
- Las mediciones anteriores a octubre de 2026 quedaron en el historial de git
  (rama `LEC` del repositorio remoto).
