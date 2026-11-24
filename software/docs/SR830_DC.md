# Adquisicion DC y normalizacion en PyQt

El programa adquiere AUX IN 1 en el mismo comando que X, Y, R y theta:
`SNAP?1,2,3,4,5,9`. El parametro 5 es AUX IN 1, expresado en voltios.
Los antiguos canales X/AUX y R/AUX ahora se llaman X/DC y R/DC.
Desde el 20 de octubre de 2026, por defecto se toman SNAP repetidos durante
la espera de estabilizacion N por tau para obtener una DC media por punto.
Se conserva X/Y/R/theta del SNAP final, posterior a la estabilizacion.

## Conexion necesaria

Conectar la senal DC del detector o de la salida DC/monitor del preamplificador
a **AUX IN 1**, en el panel posterior del SR830. Es una entrada distinta de
A/B: el SR830 no entrega por SNAP la componente DC original de A/B como
otro canal. Cambiar A/B a acoplamiento DC no reemplaza esta conexion.

Segun el [manual oficial](https://www.thinksrs.com/downloads/PDFs/Manuals/SR830m.pdf),
secciones 4-27 y 5-15, AUX IN tiene rango de -10.5 a +10.5 V, impedancia de
1 Mohm y resolucion aproximada de 1/3 mV. Confirmar que la salida que hoy
se mide con el osciloscopio es una tension compatible antes de conectarla.
No conectar una salida de alta tension ni la alimentacion de un detector.
Si se deriva la misma fuente hacia A/B y AUX, comprobar que la carga y la
puesta a tierra sean compatibles con el detector/preamplificador.

La DC debe provenir de la componente continua que se quiere usar como
referencia. Una senal modulada sin filtrar leida por AUX da una muestra
instantanea; no se debe interpretar automaticamente como su media DC.
En ese caso hace falta una salida DC apropiada o un filtrado/promediado
acorde a la frecuencia de modulacion. El promedio durante N por tau no
esta sincronizado con el modulador y no garantiza eliminar aliasing.

## Uso

En **Canales** se pueden visualizar y guardar PNG de X, Y, R, theta,
**X/DC**, **R/DC** y **DC (AUX IN 1, V)**. X, R, DC y los dos cocientes
estan seleccionados inicialmente. El grafico DC y el estado muestran la DC
usada para normalizar: la media con el promedio activado, o la lectura final
si esta desactivado. La lectura instantanea final se conserva en los CSV.

**Promediar DC por punto durante N x tau** esta activado por defecto.
Despues del movimiento y su margen mecanico se toman SNAP durante la espera
N por tau, con un intervalo objetivo de 50 ms entre inicios de consultas.
La frecuencia real depende de la latencia VISA; no se agrega una pausa fija
de 50 ms al tiempo de cada consulta. Al terminar la espera se verifica otra
vez el filtro y se toma el SNAP final. Los valores X/Y/R/theta intermedios
no se promedian, porque incluyen el transitorio desde el punto anterior.

Se calcula `X_final / DC_media_durante_Ntau`, analogamente para Y y R.
Cada punto y repeticion tiene su propia media; se reemplazo el promedio por
lambda que se reutilizaba para varias posiciones. No se agrega otra ventana
de promedio ni un tiempo de promedio independiente. Una consulta iniciada
antes del vencimiento puede terminar despues: `DC_duracion_s` guarda el
tiempo real de la ventana, incluida esa latencia. El SNAP final queda fuera
del promedio y su DC se conserva como `DC_instantanea_V`.

Si cambia tau o la pendiente al verificar el filtro, se descarta la media
previa y se repite la espera completa. Movimientos y cambios de sensibilidad
tambien invalidan el promedio. Una espera ya completada para auto rango
puede reutilizarse en el mismo punto si no hubo cambios ni movimiento.
Una media ya usada por un punto no se reutiliza en el siguiente.

Al desactivar la casilla se vuelve a `X_final / DC_del_SNAP_final`, con una
sola lectura de datos despues de la espera. No se modifican tau ni pendiente.

Promediar uniformemente durante N por tau no reproduce la ponderacion del
filtro interno del lock-in. Se supone que la DC del punto ya esta estable
despues del margen mecanico. Un transitorio del detector o deriva apreciable
durante la ventana requiere revisar esa suposicion en el montaje real.

## Archivos

- `raw.csv`: conserva las primeras columnas anteriores. `AUX` es la DC usada
  como denominador (lectura final o media por punto durante N por tau).
  Al final se guardan `DC_instantanea_V`, `DC_muestras`, `DC_desvio_V`,
  `DC_duracion_s` y `DC_muestras_invalidas`.
- `normalizado.csv`: una fila por punto y repeticion con X/Y/R, posicion,
  longitud de onda, DC instantanea, DC usada, X/DC, Y/DC, R/DC, `DC_valida`
  y las cuatro columnas de calidad del promedio.
- `metadata.json`: identifica AUX IN 1 como fuente, las unidades y el modo
  de normalizacion. Los cocientes son divisiones directas, sin factores
  opticos, de ganancia externa o de calibracion adicionales.

`DC_muestras` cuenta las lecturas durante la ventana; no incluye el SNAP
final. `DC_desvio_V` es el desvio estandar muestral (ddof=1), no el error
de la media. Es NaN con menos de dos muestras; se informa en el log cuando
hay cero o una muestra, sin prolongar la ventana. Con cero muestras la media
y los cocientes son NaN; no se usa una DC vieja ni la final como sustituto.
Con el promedio desactivado, cantidad y duracion son cero y desvio es NaN.

Una DC nula, no finita o en/fuera del limite de ±10.5 V produce `NaN` en
los cocientes y `DC_valida=False`; se conservan las lecturas crudas y se
registra el problema en el log. La polaridad del denominador se conserva.
Una DC muy pequena respecto del ruido o de la resolucion puede producir
cocientes inestables: se debe evaluar su calidad en el montaje real.

Cualquier muestra no finita o con valor absoluto de al menos 10.5 V durante
la ventana invalida toda la media y su desvio; se cuenta en
`DC_muestras_invalidas`. Los ceros individuales se incluyen en la media.
Un error de comunicacion interrumpe la medicion conservando solo los puntos
completos; nunca se utiliza silenciosamente un promedio parcial. La
cancelacion se comprueba entre consultas y durante las pausas; una consulta
en curso conserva los timeouts y reintentos del adaptador.

La exportacion normalizada guarda cocientes y calidad de cada punto de cada
repeticion por separado. El mecanismo previo de promedio entre repeticiones sigue
promediando las lecturas de los canales antes de formar sus cocientes
en el grafico de promedio; no debe confundirse con promediar cocientes.

Las interfaces Tkinter conservan su formato de adquisicion de ocho campos.
Los campos adicionales se habilitan solo en el flujo PyQt.

## Prueba real del 16 de octubre de 2026

Se probo el montaje fotodiodo/osciloscopio/entrada A/AUX IN 1, conectado
con derivaciones T. La referencia indicada en el osciloscopio fue V average
de 9.9 mV. Las medias de AUX durante 3 s dieron 10.333 y 10.440 mV en
dos momentos diferentes. Las muestras individuales variaron varios mV:
para este montaje se debe activar el promedio temporal al normalizar.
La diferencia respecto del osciloscopio no se corrigio con un factor
arbitrario; requiere evaluar simultaneidad, estabilidad y calibracion.

Se adquirieron y guardaron puntos reales en 150, 160 y 170 mm, sin
monocromador. El informe y los datos se encuentran en
`Validacion_hardware/INFORME_2026-10-16.md`.
Esa prueba uso el anterior promedio por lambda; no valida experimentalmente
el nuevo promedio durante N por tau.

## Pruebas sin hardware

    python -B -m unittest -v test_dc_settling test_dc_normalization test_sr830_settling test_pyqt_v1_core test_horiba_adapter test_bbd_state

Se verifican los tres modos de barrido, repeticiones, X final frente a X
transitoria, duracion y calidad de DC, cambios de filtro y sensibilidad,
latencia, cancelacion, errores, exportacion CSV y graficos/estado de PyQt.
