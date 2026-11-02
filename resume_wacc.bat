@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONPATH=%~dp0hub
".venv\Scripts\python.exe" -m wacc_hub resume
if not defined WACC_NO_PAUSE pause
endlocal
