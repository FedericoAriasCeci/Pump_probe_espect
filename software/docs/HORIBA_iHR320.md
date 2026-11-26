# HORIBA iHR320 en el programa pump-probe

El espectrómetro del montaje es el HORIBA iHR320 y se controla por **ICL de
EzSpec-SDK**, el mismo servicio y el mismo protocolo que usa el software de
calibración (`Software_calibracióniHR320`), donde ese control fue validado con
el equipo. El SMS LambdaScan y el puente COM `HoribaBridge.exe` ya no se usan.

## Preparación (una vez)

1. Instalar EzSpec-SDK con su licencia y los controladores USB del iHR320.
2. Instalar `websocket-client` en el entorno del programa (Python 3.7). Hay
   que **activar** el entorno antes de llamar a pip: sin activarlo, Python no
   encuentra las DLL de OpenSSL y pip falla con "the ssl module in Python is
   not available". En `cmd`, desde la carpeta `software`:

   ```bat
   call "C:\ProgramData\Anaconda3\Scripts\activate.bat" "%USERPROFILE%\.conda\envs\pump_probe_gui"
   python -m pip install -r requirements-horiba.txt
   python -c "import websocket; print(websocket.__version__)"
   ```

   Sin acceso a internet, el mismo paquete (puro Python, 1.6.1) ya está en el
   entorno del software de calibración y basta copiarlo:

   ```bat
   set "SRC=C:\Users\LEC\Desktop\Fede\Software_calibracióniHR320\spectral_calibration\.venv\Lib\site-packages"
   set "DST=%USERPROFILE%\.conda\envs\pump_probe_gui\Lib\site-packages"
   xcopy /E /I "%SRC%\websocket" "%DST%\websocket"
   xcopy /E /I "%SRC%\websocket_client-1.6.1.dist-info" "%DST%\websocket_client-1.6.1.dist-info"
   ```

   Sin ese paquete el modo simulación funciona; `Iniciar_mediciones.bat` y el
   botón Conectar avisan si falta.

## Antes de cada sesión

- Encender el iHR320 y abrir **ICL** (`icl.exe`). El programa se conecta a
  `ws://127.0.0.1:25010`; no inicia ni cierra ICL.
- No usar a la vez SynerJY ni el software de calibración. Para cambiar de red o
  de salida óptica con el software de calibración, pulse antes **Liberar
  hardware** aquí.

## Uso en la interfaz (Iniciar_mediciones.bat)

Desactive **Modo simulacion**. El grupo **Espectrometro HORIBA iHR320 (ICL)**
reúne todo lo del monocromador:

| Control | Qué hace |
| --- | --- |
| Indice ICL | Posición del equipo en `mono_list` (0 con un solo iHR320). |
| Conectar | Abre la sesión ICL y, si el equipo está inicializado, lee λ, red, salida óptica y rendijas. **Nunca** hace homing. Si falta inicializar, pregunta si hacerlo. |
| Inicializar | Envía `mono_init` (sin forzar) sólo si ICL informa que falta, y espera la confirmación. Mueve red y rendijas; puede tardar minutos. |
| Leer estado | Sólo consultas: λ, red (G1/G2/G3 y líneas/mm), salida (Axial/Lateral), rendijas. |
| Rendija entrada / salida (mm) | Aperturas pedidas, 0 a 7 mm (ICL cuantiza en pasos de 6.25 µm). Se guardan para la próxima sesión. |
| Tolerancia lambda (nm) | Diferencia máxima aceptada entre la λ pedida y la que informa ICL (0.001–1 nm, defecto 0.01). Rige desde el próximo movimiento, sin reconectar; queda en `metadata.json`. |
| Ajustar rendijas al iniciar la medicion | Antes del primer punto aplica esas aperturas y las confirma por relectura. Desactivado: se mide con las rendijas actuales, que igual quedan registradas. |
| Aplicar rendijas ahora | Mueve las rendijas ya, por ejemplo para alinear. |

**Conectar todo** conecta BBD, Home, Lock-in y después el HORIBA (en segundo
plano). Las operaciones del HORIBA corren fuera del hilo de la interfaz: la
ventana sigue respondiendo y el panel **Estado** muestra λ leída, rendijas,
red y salida. Mientras dura una operación los demás controles quedan
bloqueados; **Cancelar** abandona la espera de homing o rendijas.

La medición exige el HORIBA conectado e inicializado (salvo lambda fija con
**Usar HORIBA en lambda fija** desactivado) y λ dentro de los límites del
equipo (1–1500 nm por defecto). La vista previa indica qué rendijas se aplicarán.

## Métodos de medición

Son los mismos tres barridos del programa con el SMS:

- **Lambda fija – barrer BBD**: mueve el iHR320 una vez a la λ fija y barre las
  secciones de la plataforma.
- **Posición fija – barrer λ**: fija la plataforma y recorre las secciones de λ.
- **Doble barrido**: para cada λ recorre todas las posiciones de la plataforma.

Diferencia con el SMS: en vez de dormir un tiempo estimado por velocidad, cada
`Mover` envía `mono_moveToPosition`, espera `mono_isBusy = false` y relee la
posición; si la λ informada difiere de la pedida en más de la tolerancia
(**Tolerancia lambda**, 0.01 nm por defecto) la medición se detiene con
error. Si la diferencia es sistemática (por ejemplo, con otra red), conviene
fijar la tolerancia apenas por encima de la diferencia que informa el
mensaje de error, no mucho más: el control también detecta un movimiento
que no llegó a destino. Después de cada movimiento se
repite la espera N × τ del SR830 y, si está activo, el auto rango de
sensibilidad por λ, como antes. Nunca se redefine el origen de λ
(`mono_setPosition`) ni se reintenta una orden tras un error.

Al comenzar se lee el estado del iHR320 (y se ajustan las rendijas si se
pidió); al terminar, con éxito, error o cancelación, se vuelve a leer.

## Datos guardados

- `raw.csv`: `longitud_onda_nm` es la λ pedida y confirmada (la grilla del
  barrido, como con el SMS; así se promedian repeticiones y se arma el mapa 2D).
  La nueva última columna `longitud_onda_leida_nm` es la λ que informó ICL
  después de cada movimiento (`NaN` si el HORIBA no se usa).
- `metadata.json`, bloque `horiba`: `estado_inicial`, `rendijas` (pedido,
  lectura antes y después, movimientos confirmados), `estado_final` y
  `configuracion` (versión de ICL, serie, puertos de rendija, redes instaladas,
  tiempos de espera y tolerancia). `config` incluye las aperturas pedidas.

## Cancelación y errores

Cancelar detiene la plataforma BBD y abandona la espera del iHR320, pero un
motor que ya recibió la orden termina su recorrido (la API ICL usada no tiene
una parada). Tras un error o una cancelación durante un movimiento la sesión
puede quedar cerrada: espere a que el equipo termine y pulse **Conectar** antes
de volver a medir.

## Ajustes avanzados

Se guardan en `settling_settings.ini`, sección `[horiba]`; los valores por
defecto son los validados en el software de calibración:

| Clave | Defecto | Uso |
| --- | --- | --- |
| `index` | 0 | Índice ICL (también desde la interfaz). |
| `slit_entrance_mm`, `slit_exit_mm`, `apply_slits_on_start` | 1, 1, true | Desde la interfaz. |
| `tolerance_nm` | 0.01 | Diferencia máxima entre λ pedida y leída (también desde la interfaz). |
| `minimum_nm`, `maximum_nm` | 1, 1500 | Filtro de software para λ; ajústelo a la red instalada. |
| `move_timeout_s`, `initialize_timeout_s`, `slit_timeout_s` | 180, 180, 30 | Tiempos máximos de espera. |
| `slit_in`, `slit_out` | 0, 0 | Puertos de rendija; 0 = detectar (en este equipo: entrada axial 1, salida lateral 4). |

Los cambios del `.ini` se aplican al pasar a hardware real o al pulsar
**Liberar hardware**.

## Fuera de este programa

El cambio de red (torreta) y del espejo de salida no se ofrecen aquí: se
hacen con el software de calibración, que confirma red y λ juntas. Este
programa muestra la red y la salida actuales y las guarda en los metadatos.

## Archivos

- `horiba_icl.py`: cliente ICL (WebSocket JSON, API 300), portado de
  `spectral_calibration/horiba.py`.
- `horiba_monochromator.py`: contrato de medición (`Mover`, `posicion`,
  `AjustarRendijas`, `Inicializar`, `LeerEstado`, `estado`).
- `simulated_hardware.py`: iHR320 simulado con el mismo contrato.
- Pruebas sin equipo: `tests/test_horiba_adapter.py`, `tests/test_horiba_gui.py`
  y el doble de ICL `tests/fake_icl.py`:

  ```powershell
  & "$env:USERPROFILE\.conda\envs\pump_probe_gui\python.exe" -B -m unittest discover -s tests -t .
  ```

Quedan sin uso y pueden borrarse: `horiba_ezspec.py`, `probar_horiba_ezspec.py`,
`Probar_HORIBA_EzSpec.bat`, `requirements-horiba-ezspec.txt`,
`docs/HORIBA_EZSPEC.md` y `tests/test_horiba_ezspec.py` (control con el SDK
Python oficial, que exige Python ≥ 3.9 y nunca se conectó a la medición), y la
carpeta `HoribaBridge`.

## Qué está validado

El protocolo, los comandos y los criterios de confirmación son los del
software de calibración, ensayados con este iHR320. En este programa se
verificaron con un doble de ICL (también a través de `websocket-client` real)
y en simulación: los tres barridos, el ajuste de rendijas, la cancelación y la
interfaz. Falta la primera medición con el equipo real.
