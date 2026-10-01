# -*- coding: utf-8 -*-
"""
开机自启动管理模块
基于 Windows 注册表 Run 键实现静默开机自启
"""

import os
import sys
import winreg

APP_NAME = "TaskbarMonitor"
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def get_launch_command():
    """获取程序启动命令（支持打包后的 exe 与开发环境 pythonw.exe）"""
    if getattr(sys, 'frozen', False):
        # 打包后的独立可执行文件
        return f'"{sys.executable}"'
    else:
        # Python 脚本开发环境，优先使用 pythonw.exe 避免弹出命令行窗口
        python_exe = sys.executable
        dirname = os.path.dirname(python_exe)
        pythonw_exe = os.path.join(dirname, "pythonw.exe")
        if not os.path.exists(pythonw_exe):
            pythonw_exe = python_exe

        main_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
        return f'"{pythonw_exe}" "{main_script}"'


def is_autostart_enabled():
    """检查当前是否已启用开机自启"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return bool(val)
    except FileNotFoundError:
        return False
    except Exception as e:
        print(f"[自启模块] 检查自启状态出错: {e}")
        return False


def set_autostart(enable: bool):
    """设置或取消开机自启动"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        if enable:
            cmd = get_launch_command()
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"[自启模块] 设置自启失败: {e}")
        return False
