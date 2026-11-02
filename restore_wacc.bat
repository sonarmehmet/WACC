@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONPATH=%~dp0hub
if not exist ".venv\Scripts\python.exe" ( echo [HATA] Once start_wacc.bat calistirin. & if not defined WACC_NO_PAUSE pause & exit /b 1 )
set "NAME=%~1"
if "%NAME%"=="" (
    echo [WACC] Mevcut yedekler:
    dir /b backups\hub_*.db backups\backend_*.db 2>nul
    echo.
    set /p NAME=Geri yuklenecek yedegin dosya adi: 
)
echo [WACC] DIKKAT: once tum WACC pencerelerini kapatin. Mevcut veritabani data\pre-restore-... olarak saklanir.
".venv\Scripts\python.exe" -m wacc_hub restore "%NAME%"
if not defined WACC_NO_PAUSE pause
endlocal
