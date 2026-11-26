# -*- coding: utf-8 -*-
"""
Windows 任务栏与系统托盘定位辅助模块
优化点：
1. 全面统一物理像素计算，根治 125%/150%/200% 高 DPI 缩放下的错位与托盘遮挡；
2. 优先使用 Win10 2004+ 原生 SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) 实现零延迟无感防截屏；
3. 多显示器感知的全屏检测（副屏全屏看视频不误隐藏主屏任务栏监控）+ SHQueryUserNotificationState 辅助判定；
4. 支持自动隐藏任务栏检测、Explorer 重启句柄变更感知、浅色/深色任务栏主题读取与安全提权启动任务管理器；
5. 拆分坐标移动与轻量 Z-order 置顶，避免每 300ms 无意义强制重绘。
"""

import ctypes
import ctypes.wintypes as wintypes
import math
import os
import sys

from logger import get_logger

log = get_logger("taskbar_helper")

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import win32con
    import win32gui
    import winreg

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    shell32 = ctypes.windll.shell32

    # 严谨声明 64 位 API 原型，杜绝 64 位 HWND / HANDLE 截断或负数溢出
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND

    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = wintypes.HWND

    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND

    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL

    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int

    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int

    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long

    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short

    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int

    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL

    try:
        SetWindowLongPtr = user32.SetWindowLongPtrW
    except AttributeError:
        SetWindowLongPtr = user32.SetWindowLongW
    SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HWND]
    SetWindowLongPtr.restype = wintypes.HWND

    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL

    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = ctypes.c_void_p

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE

    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    shell32.ShellExecuteW.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_int,
    ]
    shell32.ShellExecuteW.restype = ctypes.c_void_p
else:
    win32con = None
    win32gui = None
    winreg = None
    user32 = None
    kernel32 = None
    shell32 = None
    SetWindowLongPtr = None


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", ctypes.c_uint32),
    ]


class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("hWnd", ctypes.c_void_p),
        ("uCallbackMessage", ctypes.c_uint32),
        ("uEdge", ctypes.c_uint32),
        ("rc", RECT),
        ("lParam", ctypes.c_ssize_t),
    ]


if IS_WINDOWS and user32 is not None:
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]
    shell32.SHAppBarMessage.restype = ctypes.c_size_t
    try:
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = wintypes.UINT
    except AttributeError:
        pass
    try:
        shell32.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
        shell32.SHQueryUserNotificationState.restype = ctypes.c_long
    except AttributeError:
        pass

# Win32 常量
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
MONITOR_DEFAULTTONEAREST = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
ABM_GETSTATE = 0x00000004
ABS_AUTOHIDE = 0x0000001
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4


def get_taskbar_hwnd() -> int:
    """获取当前主任务栏 Shell_TrayWnd 句柄（用于感知 explorer.exe 重启）。"""
    if not IS_WINDOWS or user32 is None:
        return 0
    return int(user32.FindWindowW("Shell_TrayWnd", None) or 0)


def get_taskbar_info():
    """获取任务栏主窗口句柄、任务栏物理矩形、系统托盘物理矩形与 ReBar 物理矩形。"""
    if not IS_WINDOWS or user32 is None:
        return 0, None, None, None

    h_tray = user32.FindWindowW("Shell_TrayWnd", None)
    if not h_tray:
        return 0, None, None, None

    rect_tray = RECT()
    user32.GetWindowRect(h_tray, ctypes.byref(rect_tray))
    tray_tuple = (rect_tray.left, rect_tray.top, rect_tray.right, rect_tray.bottom)

    h_notify = user32.FindWindowExW(h_tray, 0, "TrayNotifyWnd", None)
    notify_tuple = None
    if h_notify:
        rect_notify = RECT()
        user32.GetWindowRect(h_notify, ctypes.byref(rect_notify))
        notify_tuple = (rect_notify.left, rect_notify.top, rect_notify.right, rect_notify.bottom)

    h_rebar = user32.FindWindowExW(h_tray, 0, "ReBarWindow32", None)
    rebar_tuple = None
    if h_rebar and user32.IsWindowVisible(h_rebar):
        rect_rebar = RECT()
        user32.GetWindowRect(h_rebar, ctypes.byref(rect_rebar))
        rebar_tuple = (rect_rebar.left, rect_rebar.top, rect_rebar.right, rect_rebar.bottom)

    return int(h_tray), tray_tuple, notify_tuple, rebar_tuple


def get_cursor_phys_pos():
    """读取当前鼠标在虚拟桌面中的 Win32 物理像素坐标 (x, y)。"""
    if not IS_WINDOWS or user32 is None:
        return None
    pt = POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        return int(pt.x), int(pt.y)
    return None


def round_phys(val: float) -> int:
    """与 Qt qRound 一致的半入整数取整，避免 Python 银行家舍入在 1.5x DPI 下引起 1px 偏移。"""
    if val >= 0:
        return int(math.floor(val + 0.5))
    return -int(math.floor(-val + 0.5))


def get_taskbar_dpi_ratio(h_tray: int = 0, fallback: float = 1.0) -> float:
    """获取任务栏所在显示器的真实 Win32 DPI 缩放比（无效或模拟句柄时回退到 fallback）。"""
    fb = fallback if fallback and fallback > 0 else 1.0
    if IS_WINDOWS and user32 is not None and h_tray and hasattr(user32, "GetDpiForWindow"):
        try:
            dpi = int(user32.GetDpiForWindow(h_tray) or 0)
            if dpi > 0:
                return dpi / 96.0
        except Exception:
            pass
    return fb


def get_taskbar_logical_height(dpi_ratio: float = 1.0) -> int:
    """
    获取当前主任务栏的逻辑像素高度（水平任务栏返回实际高度，如 Win10=40、Win11=48；
    竖向任务栏或未检测到任务栏时返回 48）。
    """
    h_tray, tray_rect, _, _ = get_taskbar_info()
    if not tray_rect:
        return 48
    ratio = get_taskbar_dpi_ratio(h_tray, dpi_ratio)
    t_left, t_top, t_right, t_bottom = tray_rect
    taskbar_w = t_right - t_left
    taskbar_h = t_bottom - t_top
    if taskbar_w >= taskbar_h and taskbar_h > 0:
        return max(1, round_phys(taskbar_h / ratio))
    return 48


def compute_anchor_phys_x(
    tray_rect,
    notify_rect,
    phys_widget_w: int,
    dpi_ratio: float = 1.0,
) -> int:
    """计算 offset_x=0 时的基准物理横坐标（不含 ReBar 防重叠推让）。"""
    t_left, t_top, t_right, t_bottom = tray_rect
    taskbar_w = max(1, t_right - t_left)
    taskbar_h = max(1, t_bottom - t_top)
    gap = max(6, round_phys(10 * dpi_ratio))

    if taskbar_w >= taskbar_h:
        if notify_rect and notify_rect[0] > t_left:
            return int(notify_rect[0] - phys_widget_w - gap)
        fallback_tray_w = round_phys(260 * dpi_ratio)
        return int(t_right - phys_widget_w - fallback_tray_w)
    return int(t_left + max(0, (taskbar_w - phys_widget_w) // 2))


def get_drag_phys_bounds(
    phys_widget_w: int,
    offset_min: int,
    offset_max: int,
    dpi_ratio: float = 1.0,
):
    """
    计算拖动时的基准横坐标与允许的物理横坐标范围 (anchor_x, min_x, max_x)，
    用于保证跨 DPI 水平拖动不越界且释放时准确反算 offset_x。
    """
    _, tray_rect, notify_rect, _ = get_taskbar_info()
    if not tray_rect:
        if IS_WINDOWS and user32 is not None:
            screen_w = user32.GetSystemMetrics(0)
        else:
            screen_w = 1920
        anchor_x = screen_w - phys_widget_w - round_phys(320 * dpi_ratio)
        min_x = max(0, anchor_x + round_phys(offset_min * dpi_ratio))
        max_x = min(max(0, screen_w - phys_widget_w), anchor_x + round_phys(offset_max * dpi_ratio))
        if min_x > max_x:
            min_x, max_x = 0, max(0, screen_w - phys_widget_w)
        return int(anchor_x), int(min_x), int(max_x)

    t_left, t_top, t_right, t_bottom = tray_rect
    taskbar_w = max(1, t_right - t_left)
    taskbar_h = max(1, t_bottom - t_top)
    anchor_x = compute_anchor_phys_x(tray_rect, notify_rect, phys_widget_w, dpi_ratio)
    raw_min = anchor_x + round_phys(offset_min * dpi_ratio)
    raw_max = anchor_x + round_phys(offset_max * dpi_ratio)

    if taskbar_w >= taskbar_h:
        safe_margin = max(4, round_phys(8 * dpi_ratio))
        tray_min_x = t_left + safe_margin
        tray_max_x = max(tray_min_x, t_right - phys_widget_w - safe_margin)
        min_x = max(tray_min_x, raw_min)
        max_x = min(tray_max_x, raw_max)
        if min_x > max_x:
            min_x, max_x = tray_min_x, tray_max_x
        return int(anchor_x), int(min_x), int(max_x)

    return int(anchor_x), int(raw_min), int(raw_max)


def compute_aligned_phys_rect(
    tray_rect,
    notify_rect,
    rebar_rect,
    phys_widget_w: int,
    phys_widget_h: int,
    phys_offset_x: int = 0,
    dpi_ratio: float = 1.0,
):
    """
    纯物理像素几何计算函数（便于跨 DPI 单元测试）：
    计算监控条应放置的精确物理像素坐标 (phys_x, phys_y, phys_w, phys_h)。
    """
    t_left, t_top, t_right, t_bottom = tray_rect
    taskbar_w = max(1, t_right - t_left)
    taskbar_h = max(1, t_bottom - t_top)
    gap = max(6, round_phys(10 * dpi_ratio))
    safe_margin = max(4, round_phys(8 * dpi_ratio))

    # 水平任务栏（底部或顶部）
    if taskbar_w >= taskbar_h:
        anchor_x = compute_anchor_phys_x(tray_rect, notify_rect, phys_widget_w, dpi_ratio)
        target_x = anchor_x + phys_offset_x

        # 防左侧程序图标区域重叠（仅当 ReBar 有效且右侧不会挤出托盘区时生效）
        if rebar_rect is not None:
            r_right = rebar_rect[2]
            max_allowed_x = (notify_rect[0] - phys_widget_w - safe_margin) if notify_rect else (t_right - phys_widget_w)
            auto_clamp_threshold = round_phys(-40 * dpi_ratio)
            if r_right < max_allowed_x and target_x < r_right + safe_margin and phys_offset_x >= auto_clamp_threshold:
                target_x = r_right + safe_margin

        # 约束在任务栏可视横坐标范围内
        min_x = t_left + safe_margin
        max_x = max(min_x, t_right - phys_widget_w - safe_margin)
        target_x = max(min_x, min(max_x, int(target_x)))

        # 兼容 Win10 40px 与 Win11 48px 任务栏：物理高度不超过任务栏高度并垂直居中
        clamped_h = min(int(phys_widget_h), taskbar_h)
        target_y = t_top + max(0, (taskbar_h - clamped_h) // 2)
        return int(target_x), int(target_y), int(phys_widget_w), int(clamped_h)
    else:
        # 竖向任务栏（Win10 左侧/右侧任务栏兜底：贴近通知区上方）
        target_x = compute_anchor_phys_x(tray_rect, notify_rect, phys_widget_w, dpi_ratio) + phys_offset_x
        if notify_rect:
            target_y = max(t_top + safe_margin, notify_rect[1] - phys_widget_h - gap)
        else:
            target_y = max(t_top + safe_margin, t_bottom - phys_widget_h - round_phys(160 * dpi_ratio))

    return int(target_x), int(target_y), int(phys_widget_w), int(phys_widget_h)


def calculate_window_rect(
    phys_widget_w: int,
    phys_widget_h: int,
    phys_offset_x: int = -4,
    dpi_ratio: float = 1.0,
):
    """
    计算监控条在屏幕上的物理像素目标矩形 (phys_x, phys_y, phys_w, phys_h)。
    所有输入输出均严格使用物理像素，彻底避免高 DPI 单位混用。
    """
    _, tray_rect, notify_rect, rebar_rect = get_taskbar_info()
    if not tray_rect:
        if IS_WINDOWS and user32 is not None:
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
        else:
            screen_w, screen_h = 1920, 1080
        fallback_h = round_phys(48 * dpi_ratio)
        return (
            screen_w - phys_widget_w - round_phys(320 * dpi_ratio) + phys_offset_x,
            screen_h - fallback_h + max(0, (fallback_h - phys_widget_h) // 2),
            phys_widget_w,
            phys_widget_h,
        )

    return compute_aligned_phys_rect(
        tray_rect=tray_rect,
        notify_rect=notify_rect,
        rebar_rect=rebar_rect,
        phys_widget_w=phys_widget_w,
        phys_widget_h=phys_widget_h,
        phys_offset_x=phys_offset_x,
        dpi_ratio=dpi_ratio,
    )


def is_taskbar_retracted(h_tray: int = 0) -> bool:
    """检测任务栏是否开启自动隐藏且当前已缩起隐藏。"""
    if not IS_WINDOWS or user32 is None or shell32 is None:
        return False
    try:
        abd = APPBARDATA()
        abd.cbSize = ctypes.sizeof(APPBARDATA)
        state = shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(abd))
        if not (state & ABS_AUTOHIDE):
            return False

        hwnd = h_tray or user32.FindWindowW("Shell_TrayWnd", None)
        if not hwnd or not user32.IsWindowVisible(hwnd):
            return True

        h_mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not h_mon:
            return False

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(h_mon, ctypes.byref(mi)):
            return False

        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        mon = mi.rcMonitor

        # 计算任务栏与所在显示器可见区域的交集宽高
        vis_w = max(0, min(r.right, mon.right) - max(r.left, mon.left))
        vis_h = max(0, min(r.bottom, mon.bottom) - max(r.top, mon.top))
        return vis_w <= 6 or vis_h <= 6
    except Exception:
        return False


def is_taskbar_light_theme() -> bool:
    """读取 Windows 注册表判断系统任务栏当前是否为浅色主题。"""
    if not IS_WINDOWS or winreg is None:
        return False
    try:
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
        return int(val) == 1
    except Exception:
        return False


def set_exclude_from_capture(hwnd: int, enable: bool) -> bool:
    """
    通过 Win10 2004+ 原生 API (WDA_EXCLUDEFROMCAPTURE) 让截屏/录屏自动忽略监控条。
    相比定时器轮询隐藏：零延迟、不闪烁，微信/QQ/Snipaste/Win+Shift+S/PrtScn 均瞬间生效。
    返回 True 表示系统原生支持并设置成功；低版本 Windows 返回 False，由调用方降级到轮询检测。
    """
    if not IS_WINDOWS or user32 is None or not hwnd:
        return False
    try:
        affinity = WDA_EXCLUDEFROMCAPTURE if enable else WDA_NONE
        return bool(user32.SetWindowDisplayAffinity(hwnd, affinity))
    except Exception:
        return False


def get_process_name_by_hwnd(hwnd: int) -> str:
    """根据窗口句柄低开销获取进程文件名。"""
    if not IS_WINDOWS or user32 is None or kernel32 is None or not hwnd:
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
            return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(h_proc)
    return ""


def setup_taskbar_window_style(hwnd: int) -> int:
    """
    为监控窗口配置防覆盖样式并绑定 Shell_TrayWnd 为 Owner Window。
    返回当前绑定的 Shell_TrayWnd 句柄，供调用方检测 Explorer 重启。
    """
    if not IS_WINDOWS or user32 is None or win32gui is None or not hwnd:
        return 0
    try:
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex_style |= win32con.WS_EX_TOOLWINDOW
        ex_style |= win32con.WS_EX_NOACTIVATE
        ex_style |= win32con.WS_EX_TOPMOST
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)

        h_tray = user32.FindWindowW("Shell_TrayWnd", None)
        if h_tray and SetWindowLongPtr is not None:
            SetWindowLongPtr(hwnd, -8, h_tray)  # GWLP_HWNDPARENT = -8

        ensure_topmost(hwnd, show=True)
        return int(h_tray or 0)
    except Exception as e:
        log.warning("配置防覆盖样式失败: %s", e)
        return 0


def move_window_phys(hwnd: int, x: int, y: int, w: int, h: int):
    """按物理像素精确定位并置顶窗口（不抢占前台焦点）。"""
    if not IS_WINDOWS or user32 is None or not hwnd:
        return
    user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST,
        int(x),
        int(y),
        int(w),
        int(h),
        SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )


def get_window_phys_rect(hwnd: int):
    """直接读取窗口当前的 Win32 物理像素矩形 (left, top, right, bottom)。"""
    if not IS_WINDOWS or user32 is None or not hwnd:
        return None
    rect = RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    return None


def ensure_topmost(hwnd: int, show: bool = False):
    """轻量级 Z-order 置顶维持（不触发坐标移动与尺寸重算，极低开销）。"""
    if not IS_WINDOWS or user32 is None or not hwnd:
        return
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    if show:
        flags |= SWP_SHOWWINDOW
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)


def open_task_manager() -> bool:
    """使用 ShellExecuteW 安全启动任务管理器，避免非管理员权限下 Popen 触发 WinError 740。"""
    if not IS_WINDOWS or shell32 is None:
        return False
    try:
        ret = shell32.ShellExecuteW(None, "open", "taskmgr.exe", None, None, 1)
        return int(ret or 0) > 32
    except Exception as e:
        log.warning("打开任务管理器失败: %s", e)
        return False


def open_file_in_shell(path: str) -> bool:
    """用系统默认程序打开指定文件（如日志文件）。"""
    if not IS_WINDOWS or shell32 is None or not path:
        return False
    try:
        ret = shell32.ShellExecuteW(None, "open", path, None, None, 1)
        return int(ret or 0) > 32
    except Exception as e:
        log.warning("打开文件失败 (%s): %s", path, e)
        return False


def is_screenshot_active() -> bool:
    """
    降级截屏状态侦测（用于不支持 WDA_EXCLUDEFROMCAPTURE 的旧版 Windows）。
    支持多显示器判断，避免副屏截屏误判。
    """
    if not IS_WINDOWS or user32 is None:
        return False
    try:
        if user32.GetAsyncKeyState(0x2C) & 0x8000:
            return True

        fg = user32.GetForegroundWindow()
        if not fg or not user32.IsWindowVisible(fg):
            return False

        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(fg, cls_buf, 256)
        cls = cls_buf.value.lower()
        if cls in ("progman", "workerw", "shell_traywnd", "shell_secondarytraywnd"):
            return False

        pname = get_process_name_by_hwnd(fg)
        dedicated_procs = {
            "screenclippinghost.exe",
            "snippingtool.exe",
            "snipaste.exe",
            "pixpin.exe",
            "flameshot.exe",
            "sharex.exe",
        }
        if pname in dedicated_procs:
            return True

        h_mon = user32.MonitorFromWindow(fg, MONITOR_DEFAULTTONEAREST)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not h_mon or not user32.GetMonitorInfoW(h_mon, ctypes.byref(mi)):
            return False

        rect = RECT()
        user32.GetWindowRect(fg, ctypes.byref(rect))
        mon_r = mi.rcMonitor
        is_fullscreen_overlay = (
            rect.left <= mon_r.left
            and rect.top <= mon_r.top
            and rect.right >= mon_r.right
            and rect.bottom >= mon_r.bottom
        )

        ex_style = user32.GetWindowLongW(fg, -20)  # GWL_EXSTYLE
        is_topmost = bool(ex_style & 0x00000008)  # WS_EX_TOPMOST

        title_buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(fg, title_buf, 256)
        title = title_buf.value.lower()

        comm_procs = {"weixin.exe", "wechat.exe", "wechatappex.exe", "qq.exe", "tim.exe"}
        if pname in comm_procs:
            if is_fullscreen_overlay and is_topmost:
                return True
            if any(k in cls for k in ("screenshot", "screenclip", "capture", "snip")):
                return True
            if any(k in title for k in ("screenshot", "screenclip", "capture", "snip", "截图")):
                return True

        if is_fullscreen_overlay and is_topmost and not title:
            return True
    except Exception:
        pass
    return False


def is_fullscreen_active(taskbar_hwnd: int = 0) -> bool:
    """
    多显示器感知的全屏检测：
    仅当全屏应用（游戏、全屏视频、PPT 放映）位于【任务栏同一物理显示器】时才返回 True，
    杜绝副屏全屏观影误隐藏主屏任务栏监控条的问题。
    """
    if not IS_WINDOWS or user32 is None:
        return False
    try:
        fg = user32.GetForegroundWindow()
        if not fg or not user32.IsWindowVisible(fg):
            return False

        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(fg, cls_buf, 256)
        cls = cls_buf.value.lower()
        if cls in ("progman", "workerw", "shell_traywnd", "shell_secondarytraywnd"):
            return False

        h_fg_mon = user32.MonitorFromWindow(fg, MONITOR_DEFAULTTONEAREST)
        if not h_fg_mon:
            return False

        # 校验前台全屏窗口是否与主任务栏位于同一显示器
        h_tray = taskbar_hwnd or user32.FindWindowW("Shell_TrayWnd", None)
        if h_tray:
            h_tray_mon = user32.MonitorFromWindow(h_tray, MONITOR_DEFAULTTONEAREST)
            if h_tray_mon and h_fg_mon != h_tray_mon:
                return False

        # 检测 Windows 原生 D3D 独占全屏 / 演示模式
        if shell32 is not None and hasattr(shell32, "SHQueryUserNotificationState"):
            state = ctypes.c_int(0)
            if shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
                if state.value in (QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE):
                    return True

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(h_fg_mon, ctypes.byref(mi)):
            return False

        rect = RECT()
        user32.GetWindowRect(fg, ctypes.byref(rect))
        mon_r = mi.rcMonitor

        # 覆盖整个物理显示器（含任务栏区域）
        return (
            rect.left <= mon_r.left
            and rect.top <= mon_r.top
            and rect.right >= mon_r.right
            and rect.bottom >= mon_r.bottom
        )
    except Exception:
        return False
