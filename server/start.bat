@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Не найден Python сервера. Установите зависимости по README.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -u run.py
set "launcher_exit=%errorlevel%"
if not "%launcher_exit%"=="0" pause
exit /b %launcher_exit%
