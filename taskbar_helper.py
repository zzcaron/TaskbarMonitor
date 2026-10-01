# -*- coding: utf-8 -*-
"""
Windows 任务栏与系统托盘定位辅助模块
用于精确定位任务栏托盘折叠按钮左侧区域，并管理窗口贴合与绝对防覆盖属性
"""

import ctypes
import ctypes.wintypes as wintypes
import win32gui
import win32con

user32 = ctypes.windll.user32

# 严谨声明 64 位 SetWindowPos 函数原型，杜绝 64 位 HWND 参数截断引发 1400 错误
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_uint
]
user32.SetWindowPos.restype = wintypes.BOOL


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
    精确吸附在系统托盘区展开按钮的左侧，并预留舒适间距，杜绝与托盘按钮或任务栏程序图标重叠
    """
    h_tray, tray_rect, notify_rect = get_taskbar_info()
    if not tray_rect:
        # 若未找到任务栏，返回主屏幕右下角任务栏常规高度
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        return screen_w - widget_width - 320, screen_h - 48, widget_width, 48

    t_left, t_top, t_right, t_bottom = tray_rect
    taskbar_height = t_bottom - t_top
    if taskbar_height <= 0:
        taskbar_height = 48

    if notify_rect:
        n_left, n_top, n_right, n_bottom = notify_rect
        # 预留 10px 舒适间距，确保与系统托盘 ^ 展开按钮绝对不发生重叠粘连
        target_x = n_left - widget_width - 10 + offset_x
    else:
        # 降级：若未能检测到 TrayNotifyWnd，预留托盘大约 260px 宽度
        target_x = t_right - widget_width - 260 + offset_x

    # 智能防左侧任务栏程序图标重叠检测
    if h_tray:
        h_rebar = user32.FindWindowExW(h_tray, 0, "ReBarWindow32", None)
        if h_rebar and user32.IsWindowVisible(h_rebar):
            rect_rebar = RECT()
            user32.GetWindowRect(h_rebar, ctypes.byref(rect_rebar))
            # 若位置侵入中间程序图标区域，自动向右平移留出 8px 安全间隙
            if target_x < rect_rebar.right + 8:
                target_x = rect_rebar.right + 8

    target_y = t_top
    return target_x, target_y, widget_width, taskbar_height


# 64位 SetWindowLongPtrW 支持
try:
    SetWindowLongPtr = user32.SetWindowLongPtrW
except AttributeError:
    SetWindowLongPtr = user32.SetWindowLongW

SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HWND]
SetWindowLongPtr.restype = wintypes.HWND

kernel32 = ctypes.windll.kernel32
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def get_process_name_by_hwnd(hwnd):
    """根据窗口句柄毫秒级获取其所属进程文件名（低开销原生 Win32，不依赖 psutil）"""
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h_proc:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
            import os
            return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(h_proc)
    return ""


def setup_taskbar_window_style(hwnd):
    """
    为监控窗口配置永不被任务栏或其他程序覆盖的核心样式：
    1. WS_EX_TOOLWINDOW: 工具窗口，不产生任务栏按钮，不入 Alt+Tab
    2. WS_EX_NOACTIVATE: 鼠标交互不抢占前台焦点（打字/全屏/游戏无干扰）
    3. WS_EX_TOPMOST: 强力置顶
    4. GWLP_HWNDPARENT: 绑定 Shell_TrayWnd 为所有者（Owner），使 Windows 窗口管理器
       保证小部件永远渲染在任务栏的上层，点击任务栏图标绝不消失
    """
    try:
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex_style |= win32con.WS_EX_TOOLWINDOW
        ex_style |= win32con.WS_EX_NOACTIVATE
        ex_style |= win32con.WS_EX_TOPMOST
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)

        # 绑定 Shell_TrayWnd 为所有者（Owner Window）
        # 在 Windows 体系中，Owned Window 永远显示在其 Owner 窗口之上，任务栏被点击时绝不遮挡小部件
        h_tray = user32.FindWindowW("Shell_TrayWnd", None)
        if h_tray:
            SetWindowLongPtr(hwnd, -8, h_tray)  # GWLP_HWNDPARENT = -8

        # 初始强力置顶
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


def is_screenshot_active():
    """
    毫秒级准确侦测系统是否正处于截屏定格状态
    支持微信 (Weixin/WeChat/WeChatAppEx)、QQ/TIM、Win11自带截图 (ScreenClippingHost/SnippingTool)、Snipaste、PixPin、PrtScn按键等
    """
    try:
        # 1. 检查物理键盘是否正按下 PrtScn 截屏键 (VK_SNAPSHOT = 0x2C)
        if user32.GetAsyncKeyState(0x2C) & 0x8000:
            return True

        fg = user32.GetForegroundWindow()
        if not fg or not user32.IsWindowVisible(fg):
            return False

        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(fg, cls_buf, 256)
        cls = cls_buf.value.lower()

        # 忽略常规桌面与任务栏
        if cls in ('progman', 'workerw', 'shell_traywnd', 'shell_secondarytraywnd'):
            return False

        title_buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(fg, title_buf, 256)
        title = title_buf.value.lower()

        pname = get_process_name_by_hwnd(fg)

        # 2. 专用截图工具进程（前台只要是它们，必定处于截图状态）
        DEDICATED_SCREENSHOT_PROCS = {
            'screenclippinghost.exe',
            'snippingtool.exe',
            'snipaste.exe',
            'pixpin.exe',
            'flameshot.exe',
            'sharex.exe'
        }
        if pname in DEDICATED_SCREENSHOT_PROCS:
            return True

        # 3. 检查窗口几何特征与 TOPMOST 遮罩
        rect = wintypes.RECT()
        user32.GetWindowRect(fg, ctypes.byref(rect))
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)

        # 跨越并覆盖整块屏幕（包括任务栏底栏：rect.bottom >= sh 且 rect.top <= 0）
        # 普通最大化常规窗口受限于工作区，rect.bottom 会小于 sh
        is_fullscreen_overlay = (rect.left <= 0 and rect.top <= 0 and rect.right >= sw and rect.bottom >= sh)

        GWL_EXSTYLE = -20
        WS_EX_TOPMOST = 0x00000008
        ex_style = user32.GetWindowLongW(fg, GWL_EXSTYLE)
        is_topmost = bool(ex_style & WS_EX_TOPMOST)

        # 微信 / QQ 等通讯工具截图：前台覆盖全屏遮罩且置顶，或类名/标题匹配截图词
        COMM_PROCS = {'weixin.exe', 'wechat.exe', 'wechatappex.exe', 'qq.exe', 'tim.exe'}
        if pname in COMM_PROCS:
            if is_fullscreen_overlay and is_topmost:
                return True
            if any(k in cls for k in ('screenshot', 'screenclip', 'capture', 'snip')):
                return True
            if any(k in title for k in ('screenshot', 'screenclip', 'capture', 'snip', '截图')):
                return True

        # 4. 任何全屏置顶且无标题的捕获遮罩
        if is_fullscreen_overlay and is_topmost and not title:
            return True

    except Exception:
        pass

    return False


