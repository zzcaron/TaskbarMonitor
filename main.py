# -*- coding: utf-8 -*-
"""
任务栏硬件监控工具 (TaskbarMonitor)
主入口程序：负责单实例保护、全局日志初始化、系统托盘管理、后台采样热更新与优雅退出清理。
"""

import ctypes
import ctypes.wintypes as wintypes
import multiprocessing
import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QAction, QApplication, QMenu, QSystemTrayIcon

from autostart import is_autostart_enabled, set_autostart
from config import load_config
from logger import get_log_file_path, get_logger, setup_logging
from monitor import MonitorWorker
from taskbar_helper import open_file_in_shell, open_task_manager
from ui_taskbar import MENU_STYLESHEET, TaskbarMonitorWidget

# 单用户桌面应用使用 Local\ 前缀，避免非管理员权限或远程桌面会话冲突
MUTEX_NAME = "Local\\TaskbarMonitor_SingleInstance_Mutex"


def create_tray_pixmap() -> QPixmap:
    """动态生成兜底托盘图标（带监控波形标志）。"""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setBrush(QColor("#00d2d3"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(2, 2, 28, 28, 6, 6)

    painter.setPen(QColor("#ffffff"))
    painter.drawLine(6, 18, 11, 18)
    painter.drawLine(11, 18, 15, 8)
    painter.drawLine(15, 8, 20, 24)
    painter.drawLine(20, 24, 23, 14)
    painter.drawLine(23, 14, 27, 14)

    painter.end()
    return pixmap


def _install_exception_hook(log):
    """捕获未处理异常并写入轮转日志文件，便于 --noconsole 模式下定位问题。"""
    def _handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.critical("发生未捕获异常", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _handle_exception


def _load_app_icon() -> QIcon:
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico")
    if getattr(sys, "frozen", False):
        mei_icon = os.path.join(getattr(sys, "_MEIPASS", ""), "app_icon.ico")
        if os.path.exists(mei_icon):
            icon_path = mei_icon

    if os.path.exists(icon_path):
        return QIcon(icon_path)
    return QIcon(create_tray_pixmap())


def main():
    setup_logging()
    log = get_logger("main")
    _install_exception_hook(log)

    # 1. 单实例互斥检查（使用 use_last_error=True 与 64 位 HANDLE 原型，避免错误码被覆盖或句柄截断）
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    h_mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        log.info("检测到已有实例运行，本次启动自动退出。")
        if h_mutex:
            kernel32.CloseHandle(h_mutex)
        sys.exit(0)

    log.info("TaskbarMonitor 启动中...")

    # 2. 高 DPI 缩放适配（启用 PassThrough 防止 125%/150% 缩放被 Qt5 默认舍入为 1.0/2.0）
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if hasattr(QApplication, "setHighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    app_icon = _load_app_icon()
    app.setWindowIcon(app_icon)

    # 统一加载单一配置对象
    cfg = load_config()

    # 3. 创建任务栏展示窗口
    monitor_window = TaskbarMonitorWidget(initial_cfg=cfg)
    monitor_window.show()

    # 4. 创建系统托盘图标与上下文菜单
    tray = QSystemTrayIcon(app_icon, app)
    tray.setToolTip("任务栏硬件与网速监控 (双击打开设置)")

    tray_menu = QMenu()
    tray_menu.setStyleSheet(MENU_STYLESHEET)

    action_settings = QAction("偏好设置...", tray_menu)
    action_settings.triggered.connect(monitor_window.open_settings_dialog)
    tray_menu.addAction(action_settings)

    action_autostart = QAction("开机自动启动", tray_menu, checkable=True)
    action_autostart.setChecked(is_autostart_enabled())
    action_autostart.triggered.connect(lambda chk: set_autostart(chk))
    tray_menu.addAction(action_autostart)

    # 每次弹出托盘菜单前实时同步自启勾选状态，确保与设置窗口一致
    tray_menu.aboutToShow.connect(lambda: action_autostart.setChecked(is_autostart_enabled()))

    tray_menu.addSeparator()

    action_taskmgr = QAction("打开任务管理器", tray_menu)
    action_taskmgr.triggered.connect(open_task_manager)
    tray_menu.addAction(action_taskmgr)

    action_realign = QAction("重新对齐到任务栏托盘", tray_menu)
    action_realign.triggered.connect(monitor_window.reset_align_to_taskbar)
    tray_menu.addAction(action_realign)

    action_open_log = QAction("查看运行日志", tray_menu)
    action_open_log.triggered.connect(lambda: open_file_in_shell(get_log_file_path()))
    tray_menu.addAction(action_open_log)

    tray_menu.addSeparator()

    action_quit = QAction("退出程序", tray_menu)
    action_quit.triggered.connect(app.quit)
    tray_menu.addAction(action_quit)

    tray.setContextMenu(tray_menu)
    tray.activated.connect(
        lambda reason: monitor_window.open_settings_dialog()
        if reason == QSystemTrayIcon.DoubleClick
        else None
    )
    tray.show()

    # 5. 启动后台硬件采样线程，并订阅配置热更新（刷新频率/虚拟网卡过滤/多显卡策略即时生效）
    worker = MonitorWorker(
        interval=float(cfg.get("refresh_interval", 1.0)),
        filter_virtual_nics=bool(cfg.get("filter_virtual_nics", True)),
        preferred_gpu=str(cfg.get("preferred_gpu", "auto")),
    )
    worker.metrics_updated.connect(monitor_window.update_metrics)
    monitor_window.config_changed.connect(worker.update_config)
    worker.start()

    # 6. 退出清理：隐藏托盘防残留幽灵图标、优雅停止工作线程、释放互斥锁
    def on_about_to_quit():
        log.info("TaskbarMonitor 正在退出...")
        tray.hide()
        worker.stop()
        if h_mutex:
            kernel32.CloseHandle(h_mutex)

    app.aboutToQuit.connect(on_about_to_quit)
    sys.exit(app.exec_())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
