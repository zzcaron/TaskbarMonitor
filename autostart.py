# -*- coding: utf-8 -*-
"""
开机自启动管理模块
基于 Windows 注册表 HKCU Run 键实现静默开机自启，并校验注册路径与当前程序路径一致性。
"""

import os
import sys

from logger import get_logger

try:
    import winreg
except ImportError:  # 非 Windows 环境静态检查兼容
    winreg = None

log = get_logger("autostart")

APP_NAME = "TaskbarMonitor"
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def get_launch_command() -> str:
    """获取当前程序精确启动命令（支持打包后的 exe 与开发环境 pythonw.exe）。"""
    if getattr(sys, "frozen", False):
        return f'"{os.path.abspath(sys.executable)}"'

    python_exe = os.path.abspath(sys.executable)
    dirname = os.path.dirname(python_exe)
    pythonw_exe = os.path.join(dirname, "pythonw.exe")
    if not os.path.exists(pythonw_exe):
        pythonw_exe = python_exe

    main_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
    return f'"{pythonw_exe}" "{main_script}"'


def _normalize_cmd(cmd: str) -> str:
    return os.path.normcase(cmd.strip())


def is_autostart_enabled() -> bool:
    """检查当前是否已启用开机自启，且注册表命令指向当前可执行路径。"""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
        if not val or not isinstance(val, str):
            return False
        return _normalize_cmd(val) == _normalize_cmd(get_launch_command())
    except FileNotFoundError:
        return False
    except Exception as e:
        log.warning("检查自启状态出错: %s", e)
        return False


def set_autostart(enable: bool) -> bool:
    """设置或取消开机自启动（启用时自动更新为当前最新路径）。"""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                cmd = get_launch_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                log.info("已启用开机自启: %s", cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    log.info("已关闭开机自启")
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        log.error("设置自启失败: %s", e)
        return False
