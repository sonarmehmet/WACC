@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [WACC] Once start_wacc.bat ile sistemi acin, sonra bu testi calistirin.
".venv\Scripts\python.exe" scripts\smoke_test.py
pause
