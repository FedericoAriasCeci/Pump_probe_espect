# Estabilizacion del SR830 en la interfaz PyQt

## Auditoria del flujo previo

El punto de entrada vigente es `gui_pyqt.py`. La adquisicion usa
`acquisition_service.py`, `hardware_adapter.py` y la clase `LockIn` de
`hardware_tier.py`. `Codigo.py` y `gui_tomas.py` contienen interfaces Tkinter
anteriores y no son importados por ese flujo; no se eliminaron ni modificaron.

La comunicacion con el SR830 usa PyVISA/GPIB. `OFLT?` ya se convertia a
segundos correctamente para indices validos, pero sin validar el rango. La
lectura de datos usa `SNAP?1,2,3,4,5,9` (X, Y, R, theta, AUX1 y frecuencia).
No se consultaba `OFSL?`; la configuracion inicial forzaba 6 dB/oct.

Antes de cada punto existia una espera cancelable `TiempoDeIntegracionTotal`
= N por tau, calculada al conectar. La interfaz permitia N entero entre 1 y
100, inicialmente 1. Editarlo despues de conectar no actualizaba la espera.
Los cambios posteriores en tau tampoco se detectaban. Por ello no estaba
garantizado el establecimiento aproximado del 99 %.

Los tres modos vigentes (lambda fija, posicion fija y doble barrido) son
punto por punto. Se movia el instrumento, se esperaba su retardo mecanico,
luego la espera del lock-in y finalmente se leia un SNAP. No hay barrido
continuo en este flujo. La adquisicion corre en un `QThread`; la espera se
interrumpe comprobando la cancelacion cada 50 ms.

Tambien existian promedio entre repeticiones, promedio temporal de AUX por
lambda (para normalizar) y auto rango de sensibilidad SENS por lambda. Estos
promedios no reemplazan el establecimiento del filtro. El auto rango tenia
otro retardo de 0.2 a 2 s, independiente del orden, y tomaba su lectura de
decision sin garantizar estabilizacion previa.

## Comportamiento actual

`sr830_timing.py` centraliza los 20 valores de OFLT (10 microsegundos a
30000 segundos), las cuatro pendientes y los N recomendados 5/7/9/10 para
6/12/18/24 dB/oct, respectivamente. La referencia es el
[manual oficial SRS](https://www.thinksrs.com/downloads/PDFs/Manuals/SR830m.pdf),
secciones 3-25 y 5-6. La unica formula de espera es:

    t_wait_seconds = N * time_constant_seconds

N es el numero TOTAL de constantes de tiempo. No se multiplica por el orden.
Un N manual menor al recomendado permite adquirir mas rapido; en ese caso
el usuario elige no esperar el establecimiento aproximado del 99 %.

La espera previa existente se reutiliza. Despues del movimiento completo y
de su margen mecanico, el trabajador consulta OFLT?/OFSL?, espera N por tau
y vuelve a consultar el filtro. Si cambio, espera de nuevo con los valores
nuevos. Tambien se consulta antes de cada punto siguiente. Una falla o una
respuesta invalida interrumpe la medicion y conserva los puntos completos;
no se usa un valor anterior como sustituto.

El auto rango ahora espera antes de su lectura de decision. Si cambia SENS,
invalida la estabilizacion; la siguiente lectura espera con el filtro real.
Se elimino su retardo adicional limitado a 2 s. Desde el 20 de octubre de
2026, AUX se promedia durante la propia espera N por tau, por punto. No se
agrega una segunda ventana. El auto rango y el punto pueden reutilizar una
espera ya completada y sus muestras de DC si no hubo otro movimiento,
cambio de sensibilidad o cambio detectado del filtro. Los promedios de DC
se descartan al cambiar el filtro y despues de usarse en un punto.
Los detalles y columnas de calidad se describen en `SR830_DC.md`.

El HORIBA espera hasta que el SDK informa que termino el movimiento y no
agrega otro tiempo mecanico. En BBD, `MoveTo(..., 60000)` ya espera a que
termine: se retiro el tiempo de viaje que se sumaba otra vez y se conserva
el margen mecanico existente de 1 s cuando cambia la posicion. Ese margen
precede a la espera del lock-in; no se descuenta de N por tau.

Se conserva la configuracion previa de entradas/referencia al conectar el
SR830 y el auto rango opcional de SENS. La configuracion ya no escribe OFSL;
no se escribe OFLT. La consulta del filtro es de solo lectura.

## Uso y persistencia

En **Conexion**, `Settling time (N x tau)` acepta N de 0.001 a 1000000 con
tres decimales. Inicialmente esta activado **Usar N recomendado por
pendiente**. Editar N activa el modo manual; una pendiente diferente no
sobrescribe ese valor. Volver a activar la casilla selecciona los valores
recomendados segun la pendiente real.

El panel **Estado** muestra tau en segundos, pendiente y espera resultante.
Son las ultimas lecturas del instrumento, actualizadas al conectar y durante
la adquisicion; no hay consultas VISA desde las actualizaciones de etiquetas.
Los cambios del panel fisico durante una espera se detectan al terminarla;
durante el reposo, se vuelven a leer al conectar o comenzar a adquirir.

N y el modo se conservan entre ejecuciones en `settling_settings.ini`, junto
a la interfaz. Ademas se guardan en la configuracion de la sesion. Los
metadatos incluyen un historial de tau, pendiente, N y espera, indicando
cuantos puntos se habian adquirido antes de cada cambio detectado.

Los controles se deshabilitan durante la medicion. La espera sigue en el
trabajador, usa reloj monotonico y permite cancelar en intervalos de hasta
50 ms durante las pausas. Con promedio DC hay consultas SNAP durante la
espera; las transacciones VISA en curso conservan sus timeouts y reintentos
del adaptador. Una consulta iniciada antes de terminar la ventana puede
finalizar despues. La escala temporal y el override de pruebas solo reducen esperas
en simulacion; el override no se permite para hardware real.

## Validacion sin hardware

`test_sr830_settling.py` prueba conversiones completas, indices invalidos,
factores decimales, consultas sin escritura, secuencia en los tres modos,
cambios de filtro entre puntos y durante la espera, relacion con SENS/AUX,
cancelacion, fallas de comunicacion, metadatos y estimacion. Tambien prueba
la interfaz PyQt sin pantalla: persistencia, N manual/automatico y cancelacion
de un trabajador mientras el bucle de eventos sigue respondiendo.

Ejecutar con el entorno Python del proyecto:

    python -B -m unittest -v test_dc_settling test_dc_normalization test_sr830_settling test_pyqt_v1_core test_horiba_adapter test_bbd_state

Las pruebas no requieren conectar ni mover instrumentos. La respuesta
fisica y la finalizacion mecanica deben verificarse en el montaje real.

El 16 de octubre de 2026 se realizo una prueba real con BBD y SR830,
sin monocromador: se confirmaron homing, posiciones 150/160/170 mm,
esperas de al menos 9 s despues del movimiento y cancelacion durante
la espera. El detalle esta en `Validacion_hardware/INFORME_2026-10-16.md`.
La conexion BBD ahora actualiza posicion y estado de homing reales;
la interfaz exige referencia antes de barrer con hardware real.
