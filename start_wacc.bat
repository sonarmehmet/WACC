@echo off
setlocal
chcp 65001 >nul
title WACC Launcher
cd /d "%~dp0"

echo [WACC] Checking Python...
where python >nul 2>nul
if errorlevel 1 (
    echo [HATA] Python bulunamadi. Python 3.11+ kurun: https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [WACC] Sanal ortam olusturuluyor...
    python -m venv .venv
    if errorlevel 1 ( echo [HATA] venv olusturulamadi & pause & exit /b 1 )
)

echo [WACC] Bagimliliklar kontrol ediliyor...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r hub\requirements.txt
if errorlevel 1 ( echo [HATA] Bagimliliklar yuklenemedi & pause & exit /b 1 )

set PYTHONPATH=%~dp0hub
echo [WACC] Communication Hub hazirlaniyor...
".venv\Scripts\python.exe" -m wacc_hub init
".venv\Scripts\python.exe" -m wacc_hub seed >nul

echo [WACC] Backend ayri pencerede baslatiliyor...
start "WACC Backend" "%~dp0scripts\run_backend.bat"

echo [WACC] Hub baslatiliyor: http://127.0.0.1:8765  (yalnizca bu bilgisayar)
echo [WACC] Durdurmak icin bu pencereyi kapatin veya Ctrl+C.
".venv\Scripts\python.exe" -m wacc_hub serve --host 127.0.0.1 --port 8765
endlocal
