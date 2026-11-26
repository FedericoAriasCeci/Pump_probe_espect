> **Reemplazado.** La medición usa el HORIBA por ICL directo (WebSocket, Python 3.7), como el software de calibración: ver [HORIBA_iHR320.md](HORIBA_iHR320.md). Este documento y los archivos que describe quedan sólo como referencia.

# Control independiente HORIBA iHR320 con EzSpec-SDK

Los archivos de esta entrega se agregan junto al proyecto CodigoV4. El controlador anterior basado en HoribaBridge, la GUI, hardware_adapter.py y las rutinas pump-probe conservan su contenido original. La conexión de este controlador a la medición queda para una etapa posterior.

## Archivos

- horiba_ezspec.py: clase HoribaEzSpec, independiente de GUI, COM, Kinesis y lock-in.
- probar_horiba_ezspec.py: prueba de comunicación y control desde consola.
- Probar_HORIBA_EzSpec.bat: ejecuta esa prueba con el entorno local EzSpecSdk.
- requirements-horiba-ezspec.txt: versión del paquete usada para validar la API.
- test_horiba_ezspec.py: pruebas automáticas sin instrumento ni ICL.

## Preparación

1. Instalar y activar la licencia de HORIBA EzSpec-SDK, con ICL y los controladores USB correspondientes. El paquete Python por sí solo no reemplaza ICL.
2. Encender y conectar el iHR320. Iniciar ICL de EzSpec y comprobar su dirección y puerto. El valor predeterminado del SDK es ws://127.0.0.1:25010.
3. Ejecutar la prueba desde un entorno Python >= 3.9. En esta PC existe EzSpecSdk, con Python 3.10 y horiba-sdk 1.0.4. El lanzador BAT ya utiliza ese entorno.

Para preparar otro entorno, ejecutar desde esta carpeta:

```powershell
python -m pip install -r requirements-horiba-ezspec.txt
```

El entorno que usa actualmente Iniciar_mediciones.bat, pump_probe_gui, tiene Python 3.7. Su actualización o un proceso separado deberán resolverse al integrar este driver. Esta entrega no modifica esos entornos ni el lanzador de medición.

El controlador se conecta a un ICL ya iniciado. No inicia ni apaga el servicio, por lo que también puede dirigirse a un ICL remoto mediante --host y --port. Los identificadores de EzSpec son números obtenidos por descubrimiento; no equivalen a los nombres Mono1 del puente COM ni a puertos COM.

## Primera prueba con el instrumento

Abrir PowerShell en esta carpeta. Los comandos siguientes usan el lanzador local. También puede reemplazarse .\Probar_HORIBA_EzSpec.bat por python .\probar_horiba_ezspec.py desde un entorno compatible. Las opciones comunes van antes del subcomando.

```powershell
.\Probar_HORIBA_EzSpec.bat discover
.\Probar_HORIBA_EzSpec.bat --device-id 0 status
.\Probar_HORIBA_EzSpec.bat --device-id 0 config
```

Reemplazar 0 por el ID descubierto. Sin argumentos, el script consulta status. Estas consultas no envían comandos de homing ni de movimiento. Si hay un único iHR320, puede omitirse --device-id; si hay varios, el controlador exige una selección explícita y verifica el modelo de la configuración.

Una vez revisada la configuración, estos comandos sí accionan el equipo:

```powershell
.\Probar_HORIBA_EzSpec.bat --device-id 0 init
.\Probar_HORIBA_EzSpec.bat --device-id 0 move 532
.\Probar_HORIBA_EzSpec.bat --device-id 0 --limits-nm 500 600 --report prueba_horiba.json scan 500 510 2 --output-csv posiciones_horiba.csv
```

init espera hasta que termine la inicialización; no repite el homing si ICL ya informa que está inicializado. init --force permite repetirlo expresamente. Para inicializar antes de una acción puede usarse --initialize, por ejemplo:

```powershell
.\Probar_HORIBA_EzSpec.bat --device-id 0 --initialize move 532
```

El barrido acepta pasos positivos o negativos según la dirección. Incluye el extremo final solamente cuando pertenece a la grilla del paso; nunca lo sobrepasa. --settle-s agrega una espera por punto. El CSV contiene commanded_nm, reported_nm, elapsed_s y utc. No adquiere intensidad ni accede al SR830. Al terminar queda en la última longitud alcanzada.

--report guarda un diagnóstico JSON tanto en éxito como en error. Los archivos de informe y CSV deben ser nuevos. Los puntos completados se guardan y vacían a disco en cada paso. Códigos de salida: 0 éxito, 1 fallo de comunicación/control o archivo, 2 argumentos inválidos, 130 interrupción por Ctrl+C.

## Redes y accesorios

Consultar config y el montaje real antes de seleccionar accesorios. Las siguientes acciones requieren inicialización y disponibilidad del accesorio motorizado:

```powershell
.\Probar_HORIBA_EzSpec.bat --device-id 0 grating 1
.\Probar_HORIBA_EzSpec.bat --device-id 0 slit A 0.1
.\Probar_HORIBA_EzSpec.bat --device-id 0 mirror exit lateral
.\Probar_HORIBA_EzSpec.bat --device-id 0 shutter closed
```

Las redes se numeran 1 a 3 en este controlador y se convierten a los índices 0 a 2 del SDK. La densidad de líneas y el blaze se consultan en config; no se infieren por el número. Las rendijas A/B/C/D son los nombres del SDK, su ancho se expresa en milímetros y su correspondencia física debe verificarse en el montaje. Los espejos aceptan entrance/exit y axial/lateral. shutter acepta open/closed. Si un accesorio no está instalado, el error de ICL se propaga.

## API para la integración posterior

| Operación | API | Equivalente del contrato existente |
| --- | --- | --- |
| Descubrimiento | HoribaEzSpec.discover() | — |
| Conexión | connect(device_id) | AsignarPuerto(device_id) |
| Inicialización | initialize(force=False) | Configurar() |
| Posición en nm | get_wavelength() | LeerPosicion() |
| Mover y verificar | move_to(wavelength_nm) | Mover(wavelength_nm) |
| Estado | get_status(), get_configuration() | Identificar() comprueba apertura |
| Selección de red | get_grating(), set_grating(number) | CambiarRed(number) |
| Rendija en mm | get_slit_width(slit), set_slit_width(slit, width_mm) | — |
| Espejos | get_mirror(mirror), set_mirror(mirror, position) | — |
| Obturador | get_shutter(), set_shutter(opened) | — |
| Espera de reposo | wait_until_idle(timeout_s=None) | — |
| Desconexión | close() | CerrarPuerto() |

El atributo posicion se actualiza con las lecturas del instrumento y permanece en None hasta la primera lectura válida. puerto contiene el ID numérico como texto para los metadatos heredados. CalcularTiempoSleep(lambda_nm) devuelve 0 porque Mover ya espera y verifica el movimiento. Los tiempos ópticos, electrónicos y de integración del lock-in pertenecen a la capa de adquisición. Calibrar y CambiarVelocidad lanzan NotImplementedError: no modifican la calibración espectral ni inventan una equivalencia con el SMS.

Ejemplo para usar posteriormente desde el hilo de adquisición, sin modificar ahora el software:

```python
from horiba_ezspec import HoribaEzSpec

with HoribaEzSpec(device_id=0, wavelength_limits_nm=(500, 600)) as mono:
    mono.Configurar()
    for objetivo_nm in (500, 502, 504):
        lectura_nm = mono.Mover(objetivo_nm)
        print(objetivo_nm, lectura_nm)
        # Aqui podra conectarse la adquisicion existente.
```

Las llamadas son síncronas y se serializan entre hilos; el websocket del SDK permanece en un único bucle asyncio durante toda la sesión. El hilo de la GUI debe delegarlas al hilo de trabajo para conservar la respuesta de la interfaz.

Cada movimiento comprueba is_busy y verifica la longitud leída contra el objetivo. --tolerance-nm configura la tolerancia de lectura (predeterminada: 0.05 nm); esto no constituye una medición de exactitud óptica. El rango admisible depende de la red y la configuración: --limits-nm permite acotar el experimento sin imponer un rango universal supuesto.

--connection-timeout y --motion-timeout acotan las operaciones completas, incluidas las respuestas de comandos. Un timeout o una posición incorrecta impiden continuar la medición con esa sesión. Un timeout o Ctrl+C no abortan físicamente los motores: este SDK no expone una parada del monocromador en la API usada. Consultar status, esperar reposo y reconectar antes de continuar. El cierre libera dispositivo, websocket e hilo aunque se propague un error.

## Verificación realizada

```powershell
& "$env:USERPROFILE\.conda\envs\EzSpecSdk\python.exe" -B -m unittest -v test_horiba_ezspec
```

Se verifican conexión, homing condicional, finalización y lectura de movimientos, timeouts, hilos, selección inequívoca, unidades de accesorios, cierre y archivos parciales del CLI. Una prueba utiliza la clase Monochromator real de horiba-sdk 1.0.4 y sus mensajes con un transporte en memoria. Si el paquete no está instalado, esa prueba se omite; las demás no requieren hardware.

La consulta real de status ejecutada durante esta entrega fue rechazada por el servicio en 127.0.0.1:25010. No se enviaron movimientos al equipo físico; queda pendiente ejecutar la secuencia anterior con ICL instalado, licenciado y en ejecución.

Fuentes de la API y prerrequisitos: [repositorio oficial de HORIBA](https://github.com/HORIBAEzSpecSDK/python-sdk), [clase Monochromator](https://github.com/HORIBAEzSpecSDK/python-sdk/blob/main/horiba_sdk/devices/single_devices/monochromator.py) y [EzSpec-SDK](https://www.horiba.com/gbr/scientific/products/detail/action/show/Product/ezspec-sdk-6853/).
