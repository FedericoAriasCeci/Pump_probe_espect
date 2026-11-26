@echo off
setlocal
cd /d "%~dp0"

call "C:\ProgramData\Anaconda3\Scripts\activate.bat" "%USERPROFILE%\.conda\envs\pump_probe_gui"
if errorlevel 1 goto error_entorno

"%USERPROFILE%\.conda\envs\pump_probe_gui\python.exe" -c "import websocket" >nul 2>&1
if errorlevel 1 (
    echo Aviso: falta websocket-client; el HORIBA iHR320 real no podra conectarse por ICL.
    echo Instalar una vez, en una consola nueva:
    echo   call "C:\ProgramData\Anaconda3\Scripts\activate.bat" "%USERPROFILE%\.conda\envs\pump_probe_gui"
    echo   python -m pip install -r "%~dp0requirements-horiba.txt"
    echo Ver docs\HORIBA_iHR320.md si pip no tiene acceso a internet.
)

"%USERPROFILE%\.conda\envs\pump_probe_gui\python.exe" -B "%~dp0gui_pyqt.py"
if errorlevel 1 goto error_aplicacion
exit /b 0

:error_entorno
echo No se pudo activar el entorno pump_probe_gui.
pause
exit /b 1

:error_aplicacion
echo La aplicacion termino con un error. Revise el mensaje de arriba.
pause
exit /b 1
