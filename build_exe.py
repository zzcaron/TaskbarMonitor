# -*- coding: utf-8 -*-
"""
打包脚本：使用 PyInstaller 将任务栏监控工具打包为单文件绿色版可执行文件
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

# 输出目录
dist_dir = os.path.join(current_dir, "dist")
build_dir = os.path.join(cache_dir, "pyinstaller_build")
spec_dir = os.path.join(cache_dir, "pyinstaller_spec")

main_py = os.path.join(current_dir, "main.py")

cmd = [
    sys.executable,
    "-m", "PyInstaller",
    "--noconsole",
    "--onedir",
    "--name=TaskbarMonitor",
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

print("开始打包程序...")
result = subprocess.run(cmd)
if result.returncode == 0:
    print("\n✅ 打包成功！生成目录:", os.path.join(dist_dir, "TaskbarMonitor"))
else:
    print("\n❌ 打包失败，退出码:", result.returncode)
