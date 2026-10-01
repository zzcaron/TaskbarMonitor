@echo off
:: 静默启动任务栏硬件监控程序（无黑框）
cd /d "%~dp0"
start "" "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\pythonw.exe" "main.py"
