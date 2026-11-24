# Usar el HORIBA iHR320 en CodigoV3

El SMS LambdaScan fue reemplazado por `HoribaBridge.exe` mediante
`horiba_monochromator.py`. La interfaz y las rutinas de barrido siguen usando
los mismos métodos de medición; no hay que editar los rangos de longitud de
onda, los gráficos ni el formato de los CSV.

## Preparación única

Primero compile el bridge desde `C:\Users\LEC\Desktop\Fede\HoribaBridge`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

Mantenga SinerJY instalado y el iHR320 encendido. El ejecutable del bridge y
sus tres DLL `Interop.*.dll` deben permanecer dentro de `HoribaBridge\bin`.

## Interfaz original (Tkinter)

Ejecute `Codigo.py` como antes. En Configuracion, el equipo ahora se llama
**Espectrómetro HORIBA iHR320**. Deje el identificador como `Mono1`, pulse
**Conectar** y luego **Inicializar**. El programa sólo permite comenzar los
barridos después de que el estado sea `Listo`.

Los controles de calibración, velocidad y red que pertenecían al SMS quedan
deshabilitados: no son comandos seguros o equivalentes del iHR320. Seleccione
la torreta/red apropiada con SinerJY antes de medir.

## Interfaz PyQt

La interfaz PyQt usa el mismo adaptador. Desactive *Modo simulacion*, deje el
campo **ID HORIBA** en `Mono1` y pulse **Conectar HORIBA**. Los barridos de
lambda y dobles esperan a que el iHR320 termine cada movimiento antes de leer
el lock-in.

Durante una medición, cancelar detiene la plataforma BBD. El iHR320 termina el
movimiento de longitud de onda que estuviera ya enviado, porque el SDK no tiene
todavía un comando de parada integrado en el bridge.
