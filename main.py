# -*- coding: utf-8 -*-
"""
任务栏硬件监控工具 (TaskbarMonitor)
主入口程序：负责单实例保护、系统托盘管理、后台数据采样与界面装配
"""

import sys
import os
import ctypes
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor

from monitor import MonitorWorker
from ui_taskbar import TaskbarMonitorWidget
from autostart import is_autostart_enabled, set_autostart

MUTEX_NAME = "Global\\TaskbarMonitor_Deepmind_Aron_Instance"


def create_tray_pixmap():
    """动态生成极简美观的托盘图标（带监控波形标志）"""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # 绘制深青色渐变圆角底板
    painter.setBrush(QColor("#00d2d3"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(2, 2, 28, 28, 6, 6)

    # 绘制内部监控曲线折线
    painter.setPen(QColor("#ffffff"))
    painter.drawLine(6, 18, 11, 18)
    painter.drawLine(11, 18, 15, 8)
    painter.drawLine(15, 8, 20, 24)
    painter.drawLine(20, 24, 23, 14)
    painter.drawLine(23, 14, 27, 14)

    painter.end()
    return pixmap


def main():
    # 1. 单实例互斥检查
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    h_mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print("程序已在运行中，请勿重复启动。")
        sys.exit(0)

    # 2. 高 DPI 缩放适配
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 保持后台常驻

    tray_icon_pixmap = create_tray_pixmap()
    app_icon = QIcon(tray_icon_pixmap)
    app.setWindowIcon(app_icon)

    # 3. 创建任务栏展示窗口
    monitor_window = TaskbarMonitorWidget()
    monitor_window.show()

    # 4. 创建系统托盘图标与上下文菜单
    tray = QSystemTrayIcon(app_icon, app)
    tray.setToolTip("任务栏硬件与网速监控")

    tray_menu = QMenu()
    tray_menu.setStyleSheet("""
        QMenu {
            background-color: #252526;
            color: #ffffff;
            border: 1px solid #3e3e42;
            padding: 4px;
            font-family: 'Segoe UI', 'Microsoft YaHei';
            font-size: 12px;
        }
        QMenu::item {
            padding: 6px 20px 6px 12px;
            border-radius: 3px;
        }
        QMenu::item:selected {
            background-color: #094771;
        }
        QMenu::separator {
            height: 1px;
            background-color: #3e3e42;
            margin: 4px 0px;
        }
    """)

    action_autostart = QAction("开机自动启动", tray_menu, checkable=True)
    action_autostart.setChecked(is_autostart_enabled())
    action_autostart.triggered.connect(lambda chk: set_autostart(chk))
    tray_menu.addAction(action_autostart)

    tray_menu.addSeparator()

    action_realign = QAction("重新对齐到任务栏托盘", tray_menu)
    action_realign.triggered.connect(monitor_window.align_to_taskbar)
    tray_menu.addAction(action_realign)

    tray_menu.addSeparator()

    action_quit = QAction("退出程序", tray_menu)
    action_quit.triggered.connect(app.quit)
    tray_menu.addAction(action_quit)

    tray.setContextMenu(tray_menu)
    tray.show()

    # 5. 启动后台硬件采样线程
    worker = MonitorWorker(interval=1.0)
    worker.metrics_updated.connect(monitor_window.update_metrics)
    worker.start()

    # 退出清理
    def on_about_to_quit():
        worker.stop()
        if h_mutex:
            kernel32.CloseHandle(h_mutex)

    app.aboutToQuit.connect(on_about_to_quit)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
