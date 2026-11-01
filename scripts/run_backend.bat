@echo off
chcp 65001 >nul
title WACC Backend
cd /d "%~dp0.."
set PYTHONPATH=%CD%\backend
echo [WACC] Backend: http://127.0.0.1:8800  (yalnizca bu bilgisayar)
".venv\Scripts\python.exe" -m wacc_backend
pause
