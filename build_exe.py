# -*- coding: utf-8 -*-
"""
打包脚本：使用 PyInstaller 将 TaskbarMonitor 打包为独立可执行程序。
优化点：
1. 构建缓存放入项目目录内 .cache/，不再污染上级父目录；
2. 支持 --onedir 参数（启动更快、降低杀毒软件误报率），默认生成单文件 --onefile。

用法：
  python build_exe.py           # 生成单文件 dist/TaskbarMonitor.exe
  python build_exe.py --onedir  # 生成绿色文件夹 dist/TaskbarMonitor/TaskbarMonitor.exe
"""

import argparse
import os
import subprocess
import sys

try:
    import PyLibreHardwareMonitorLib
except ImportError:
    PyLibreHardwareMonitorLib = None


def main():
    parser = argparse.ArgumentParser(description="Build TaskbarMonitor executable with PyInstaller")
    parser.add_argument(
        "--onedir",
        action="store_true",
        help="生成目录版（免解压启动更快、更少杀软误报），默认生成单文件 exe",
    )
    args = parser.parse_args()

    current_dir = os.path.dirname(os.path.abspath(__file__))
    cache_dir = os.path.join(current_dir, ".cache")
    os.makedirs(cache_dir, exist_ok=True)

    icon_path = os.path.join(current_dir, "app_icon.ico")
    dist_dir = os.path.join(current_dir, "dist")
    mode_tag = "onedir" if args.onedir else "onefile"
    build_dir = os.path.join(cache_dir, f"pyinstaller_build_{mode_tag}")
    spec_dir = os.path.join(cache_dir, f"pyinstaller_spec_{mode_tag}")
    main_py = os.path.join(current_dir, "main.py")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "-y",
        "--clean",
        "--noconsole",
        "--onedir" if args.onedir else "--onefile",
        "--name=TaskbarMonitor",
        f"--distpath={dist_dir}",
        f"--workpath={build_dir}",
        f"--specpath={spec_dir}",
        f"--icon={icon_path}",
        f"--add-data={icon_path};.",
        "--collect-all=PyLibreHardwareMonitor",
        "--collect-all=PyLibreHardwareMonitorLib",
        "--collect-all=clr_loader",
        "--collect-all=pythonnet",
        "--hidden-import=pythoncom",
        "--hidden-import=win32com.client",
    ]

    if PyLibreHardwareMonitorLib is not None:
        libre_pkg_dir = os.path.dirname(PyLibreHardwareMonitorLib.__file__)
        dll_dir = os.path.join(libre_pkg_dir, "dll")
        if os.path.isdir(dll_dir):
            cmd.append(f"--add-data={dll_dir};PyLibreHardwareMonitorLib/dll")

    cmd.append(main_py)

    mode_label = "目录版 (免解压快速启动)" if args.onedir else "单文件独立版"
    print(f"开始构建 {mode_label} TaskbarMonitor...")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        if args.onedir:
            target_exe = os.path.join(dist_dir, "TaskbarMonitor", "TaskbarMonitor.exe")
        else:
            target_exe = os.path.join(dist_dir, "TaskbarMonitor.exe")
        if os.path.exists(target_exe):
            size_mb = os.path.getsize(target_exe) / (1024 * 1024)
            print(f"\n[打包成功] 输出文件: {target_exe}")
            print(f"主程序大小: {size_mb:.1f} MB")
        else:
            print(f"\n[打包成功] 输出目录: {dist_dir}")
    else:
        print(f"\n[打包失败] 退出码: {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
