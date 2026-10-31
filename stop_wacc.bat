@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONPATH=%~dp0hub
".venv\Scripts\python.exe" -m wacc_hub stop --as user --reason "Kullanici acil durdurma"
echo [WACC] ACIL DURDURMA aktif. Devam icin: resume_wacc.bat
pause
endlocal
