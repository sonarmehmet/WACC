@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0desktop"
if exist "..\.venv\Scripts\python.exe" ( "..\.venv\Scripts\python.exe" -m wacc_desktop ) else ( python -m wacc_desktop )
endlocal
