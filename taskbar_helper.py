# -*- coding: utf-8 -*-
"""
Windows 任务栏与系统托盘定位辅助模块
用于精确定位任务栏托盘折叠按钮左侧区域，并管理窗口贴合属性
"""

import ctypes
from ctypes import wintypes
import win32gui
import win32con

user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def get_taskbar_info():
    """获取任务栏与系统托盘区域的屏幕矩形坐标"""
    # 查找任务栏主窗口 Shell_TrayWnd
    h_tray = user32.FindWindowW("Shell_TrayWnd", None)
    if not h_tray:
        return None, None

    rect_tray = RECT()
    user32.GetWindowRect(h_tray, ctypes.byref(rect_tray))

    # 查找通知区域 TrayNotifyWnd
    h_notify = user32.FindWindowExW(h_tray, 0, "TrayNotifyWnd", None)
    rect_notify = None
    if h_notify:
        rect_notify = RECT()
        user32.GetWindowRect(h_notify, ctypes.byref(rect_notify))

    return (
        (rect_tray.left, rect_tray.top, rect_tray.right, rect_tray.bottom),
        (rect_notify.left, rect_notify.top, rect_notify.right, rect_notify.bottom) if rect_notify else None
    )


def calculate_window_rect(widget_width, offset_x=-4):
    """
    计算监控条应该放置的目标坐标 (x, y, w, h)
    精确吸附在系统托盘区展开按钮的左侧
    """
    tray_rect, notify_rect = get_taskbar_info()
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
    为窗口配置贴合任务栏的高级样式：
    1. WS_EX_TOOLWINDOW: 工具窗口，不出现在任务栏与 Alt+Tab 中
    2. WS_EX_NOACTIVATE: 鼠标交互不抢占当前前台窗口焦点（打字/全屏/游戏无干扰）
    """
    try:
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex_style |= win32con.WS_EX_TOOLWINDOW
        ex_style |= win32con.WS_EX_NOACTIVATE
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
    except Exception as e:
        print(f"[任务栏辅助] 设置窗口样式失败: {e}")
