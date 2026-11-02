@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONPATH=%~dp0hub
if not exist ".venv\Scripts\python.exe" ( echo [HATA] Once start_wacc.bat calistirin. & if not defined WACC_NO_PAUSE pause & exit /b 1 )
".venv\Scripts\python.exe" -m wacc_hub backup
echo [WACC] Yedek backups\ klasorune alindi.
if not defined WACC_NO_PAUSE pause
endlocal
