# -*- coding: utf-8 -*-
"""
Windows 任务栏与系统托盘定位辅助模块
用于精确定位任务栏托盘折叠按钮左侧区域，并管理窗口贴合与绝对防覆盖属性
"""

import ctypes
from ctypes import wintypes
import win32gui
import win32con

user32 = ctypes.windll.user32

# 64位系统兼容的 SetWindowLongPtr 函数
SetWindowLongPtr = getattr(user32, 'SetWindowLongPtrW', user32.SetWindowLongW)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def get_taskbar_info():
    """获取任务栏主窗口句柄、任务栏屏幕矩形与系统托盘区域矩形"""
    h_tray = user32.FindWindowW("Shell_TrayWnd", None)
    if not h_tray:
        return None, None, None

    rect_tray = RECT()
    user32.GetWindowRect(h_tray, ctypes.byref(rect_tray))

    # 查找通知区域 TrayNotifyWnd
    h_notify = user32.FindWindowExW(h_tray, 0, "TrayNotifyWnd", None)
    rect_notify = None
    if h_notify:
        rect_notify = RECT()
        user32.GetWindowRect(h_notify, ctypes.byref(rect_notify))

    return (
        h_tray,
        (rect_tray.left, rect_tray.top, rect_tray.right, rect_tray.bottom),
        (rect_notify.left, rect_notify.top, rect_notify.right, rect_notify.bottom) if rect_notify else None
    )


def calculate_window_rect(widget_width, offset_x=-4):
    """
    计算监控条应该放置的目标坐标 (x, y, w, h)
    精确吸附在系统托盘区展开按钮的左侧
    """
    h_tray, tray_rect, notify_rect = get_taskbar_info()
    if not tray_rect:
        # 若未找到任务栏，返回屏幕右下角默认位置
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        return screen_w - widget_width - 320, screen_h - 48, widget_width, 48

    t_left, t_top, t_right, t_bottom = tray_rect
    taskbar_height = t_bottom - t_top
    if taskbar_height <= 0:
        taskbar_height = 48

    if notify_rect:
        n_left, n_top, n_right, n_bottom = notify_rect
        target_x = n_left - widget_width + offset_x
    else:
        # 降级：若未能检测到 TrayNotifyWnd，预留托盘大约 260px 宽度
        target_x = t_right - widget_width - 260 + offset_x

    target_y = t_top
    return target_x, target_y, widget_width, taskbar_height


def setup_taskbar_window_style(hwnd):
    """
    为监控窗口配置永不被任务栏或其他程序覆盖的核心样式：
    1. WS_EX_TOOLWINDOW: 工具窗口，不产生任务栏按钮，不入 Alt+Tab
    2. WS_EX_NOACTIVATE: 鼠标交互不抢占前台焦点（打字/全屏/游戏无干扰）
    3. WS_EX_TOPMOST: 强力置顶
    4. GWL_HWNDPARENT: 绑定 Shell_TrayWnd 为所有者（Owner），使 Windows 窗口管理器
       保证小部件永远渲染在任务栏的上层，点击任务栏图标绝不消失
    """
    try:
        # 1. 设置扩展样式
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex_style |= win32con.WS_EX_TOOLWINDOW
        ex_style |= win32con.WS_EX_NOACTIVATE
        ex_style |= win32con.WS_EX_TOPMOST
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)

        # 2. 绑定任务栏作为 Owner Window
        h_tray = user32.FindWindowW("Shell_TrayWnd", None)
        if h_tray:
            SetWindowLongPtr(hwnd, win32con.GWL_HWNDPARENT, h_tray)

        # 3. 初始置顶与展现
        HWND_TOPMOST = -1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        user32.SetWindowPos(
            hwnd, HWND_TOPMOST,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
    except Exception as e:
        print(f"[任务栏辅助] 配置防覆盖样式失败: {e}")
