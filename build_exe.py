# -*- coding: utf-8 -*-
"""
打包脚本：使用 PyInstaller 将任务栏监控工具打包为单个独立可执行文件 TaskbarMonitor.exe
别人拿到一个单文件 exe，双击就能直接运行，无需解压任何文件夹，零配置开箱即用。
中间生成文件与缓存自动存储在根目录 cache 文件夹下。
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

# 应用图标路径
icon_path = os.path.join(current_dir, "app_icon.ico")

# 输出目录与名称
dist_dir = os.path.join(current_dir, "dist")
build_dir = os.path.join(cache_dir, "pyinstaller_build_single")
spec_dir = os.path.join(cache_dir, "pyinstaller_spec_single")

main_py = os.path.join(current_dir, "main.py")

cmd = [
    sys.executable,
    "-m", "PyInstaller",
    "-y",
    "--clean",
    "--noconsole",
    "--onefile",
    "--name=TaskbarMonitor",
    f"--distpath={dist_dir}",
    f"--workpath={build_dir}",
    f"--specpath={spec_dir}",
    f"--icon={icon_path}",
    f"--add-data={icon_path};.",
    f"--add-data={dll_dir};PyLibreHardwareMonitorLib/dll",
    "--collect-all=PyLibreHardwareMonitor",
    "--collect-all=PyLibreHardwareMonitorLib",
    "--collect-all=clr_loader",
    "--collect-all=pythonnet",
    main_py
]

print("开始构建单文件独立版 TaskbarMonitor.exe (支持直接发送好友双击即用)...")
result = subprocess.run(cmd)
if result.returncode == 0:
    target_exe = os.path.join(dist_dir, "TaskbarMonitor.exe")
    size_mb = os.path.getsize(target_exe) / (1024 * 1024)
    print(f"\n[打包成功] 生成独立单文件: {target_exe}")
    print(f"文件大小: {size_mb:.1f} MB (单文件免解压，双击直接运行)")
else:
    print(f"\n[打包失败] 退出码: {result.returncode}")
