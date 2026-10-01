# -*- coding: utf-8 -*-
"""
打包脚本：使用 PyInstaller 将任务栏监控工具打包为 TaskbarMonitor-V1.1.exe
中间生成文件与缓存自动存储在根目录 cache 文件夹下
"""

import os
import sys
import subprocess
import PyLibreHardwareMonitorLib

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
cache_dir = os.path.join(project_root, "cache")
os.makedirs(cache_dir, exist_ok=True)

# LibreHardwareMonitorLib 依赖的 dll 目录
libre_pkg_dir = os.path.dirname(PyLibreHardwareMonitorLib.__file__)
dll_dir = os.path.join(libre_pkg_dir, "dll")

# 输出目录与名称
dist_dir = os.path.join(current_dir, "dist")
build_dir = os.path.join(cache_dir, "pyinstaller_build")
spec_dir = os.path.join(cache_dir, "pyinstaller_spec")

main_py = os.path.join(current_dir, "main.py")

cmd = [
    sys.executable,
    "-m", "PyInstaller",
    "-y",
    "--noconsole",
    "--onedir",
    "--name=TaskbarMonitor-V1.5",
    f"--distpath={dist_dir}",
    f"--workpath={build_dir}",
    f"--specpath={spec_dir}",
    f"--add-data={dll_dir};PyLibreHardwareMonitorLib/dll",
    "--collect-all=PyLibreHardwareMonitor",
    "--collect-all=PyLibreHardwareMonitorLib",
    "--collect-all=clr_loader",
    "--collect-all=pythonnet",
    main_py
]

print("开始打包 TaskbarMonitor-V1.5...")
result = subprocess.run(cmd)
if result.returncode == 0:
    target_exe = os.path.join(dist_dir, "TaskbarMonitor-V1.5", "TaskbarMonitor-V1.5.exe")
    print(f"\n[打包成功] 生成可执行文件: {target_exe}")
else:
    print(f"\n[打包失败] 退出码: {result.returncode}")
