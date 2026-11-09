@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Не найдено окружение клиента .venv. Установите зависимости по README.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -u run.py
set "client_exit=%errorlevel%"
if not "%client_exit%"=="0" pause
exit /b %client_exit%
