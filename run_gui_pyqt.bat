@echo off
setlocal

cd /d "%~dp0"
"C:\ProgramData\Anaconda3\condabin\conda.bat" run -n pump_probe_gui python -X faulthandler gui_pyqt.py

endlocal
