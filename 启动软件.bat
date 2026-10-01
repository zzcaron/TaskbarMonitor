@echo off
chcp 65001 >nul
title 启动任务栏硬件监控

set "EXE_PATH=%~dp0dist\TaskbarMonitor\TaskbarMonitor.exe"

if exist "%EXE_PATH%" (
    start "" "%EXE_PATH%"
) else (
    start "" "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\pythonw.exe" "%~dp0main.py"
)
