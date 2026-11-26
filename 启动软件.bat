@echo off
chcp 65001 >nul
title 启动任务栏硬件监控
cd /d "%~dp0"

set "EXE_SINGLE=%~dp0dist\TaskbarMonitor.exe"
set "EXE_DIR=%~dp0dist\TaskbarMonitor\TaskbarMonitor.exe"
set "VENV_PYW=%~dp0.venv\Scripts\pythonw.exe"

if exist "%EXE_SINGLE%" (
    start "" "%EXE_SINGLE%"
    exit /b 0
)

if exist "%EXE_DIR%" (
    start "" "%EXE_DIR%"
    exit /b 0
)

if exist "%VENV_PYW%" (
    start "" "%VENV_PYW%" "%~dp0main.py"
    exit /b 0
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0main.py"
    exit /b 0
)

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw "%~dp0main.py"
    exit /b 0
)

echo 未找到 TaskbarMonitor.exe 或可用的 Python 环境，请先安装 Python 或运行 pip install -r requirements.txt
pause
exit /b 1
