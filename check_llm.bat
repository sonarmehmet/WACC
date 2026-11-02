@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" ( echo [HATA] Once start_wacc.bat calistirin. & if not defined WACC_NO_PAUSE pause & exit /b 1 )
".venv\Scripts\python.exe" scripts\check_llm.py
if not defined WACC_NO_PAUSE pause
endlocal
