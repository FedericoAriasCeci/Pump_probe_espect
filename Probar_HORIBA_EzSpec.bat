@echo off
setlocal
set "HORIBA_PYTHON=%USERPROFILE%\.conda\envs\EzSpecSdk\python.exe"
if not exist "%HORIBA_PYTHON%" (
    echo No se encontro el entorno EzSpecSdk. Consulte HORIBA_EZSPEC.md.
    exit /b 2
)
"%HORIBA_PYTHON%" -B "%~dp0probar_horiba_ezspec.py" %*
set "HORIBA_TEST_EXIT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %HORIBA_TEST_EXIT%
