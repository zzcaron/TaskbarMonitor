# -*- coding: utf-8 -*-
"""
任务栏硬件监控悬浮条界面
紧凑嵌入/贴合在 Windows 任务栏系统托盘左侧，支持双行四列排版、主题美化与右键菜单
"""

import os
import subprocess
from PyQt5.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout, QFrame,
    QMenu, QAction, QToolTip
)
from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import QFont, QCursor, QColor

from monitor import format_bytes_speed
from taskbar_helper import calculate_window_rect, setup_taskbar_window_style
from autostart import is_autostart_enabled, set_autostart


class MetricItem(QWidget):
    """单个监控项组件（标签 + 数值），支持双行排布"""
    def __init__(self, label_text, color="#ffffff", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 0, 3, 0)
        layout.setSpacing(3)

        # 指标名称标签
        self.lbl_title = QLabel(label_text)
        self.lbl_title.setStyleSheet("color: #a0a0a0; font-size: 11px; font-weight: 500;")

        # 指标实时数值标签
        self.lbl_value = QLabel("--")
        self.lbl_value.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600; font-family: 'Consolas', 'Segoe UI', 'Microsoft YaHei';")

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)

    def set_value(self, text, custom_color=None):
        """更新显示数值与可选颜色"""
        self.lbl_value.setText(text)
        if custom_color:
            self.lbl_value.setStyleSheet(f"color: {custom_color}; font-size: 11px; font-weight: 600; font-family: 'Consolas', 'Segoe UI', 'Microsoft YaHei';")


class SeparatorLine(QFrame):
    """细竖直分割线"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.VLine)
        self.setFrameShadow(QFrame.Sunken)
        self.setStyleSheet("color: rgba(255, 255, 255, 0.15); margin-top: 6px; margin-bottom: 6px;")


class TaskbarMonitorWidget(QWidget):
    """任务栏监控主窗口"""
    def __init__(self, parent=None):
        super().__init__(parent)

        # 偏移微调（用户自定义）
        self.offset_x = -4
        self.drag_start_pos = None

        # 初始化无边框、置顶、任务栏工具样式
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.SubWindow
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # 整体界面风格：任务栏深色半透明胶囊风格
        self.setStyleSheet("""
            QWidget#MainContainer {
                background-color: rgba(26, 26, 28, 0.88);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
            }
        """)

        self._init_ui()

        # 定位定时器：自动检测托盘变动并对齐
        self.pos_timer = QTimer(self)
        self.pos_timer.timeout.connect(self.align_to_taskbar)
        self.pos_timer.start(2000)

        # 存储当前最新监控指标用于 Tooltip 显示
        self.latest_metrics = None

    def _init_ui(self):
        # 外层布局
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(1, 2, 1, 2)

        # 内部主容器
        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(6, 2, 6, 2)
        container_layout.setSpacing(6)

        # 1. 网络列 (上: 上传, 下: 下载)
        net_col = QVBoxLayout()
        net_col.setContentsMargins(0, 0, 0, 0)
        net_col.setSpacing(1)
        self.item_upload = MetricItem("↑", color="#00d2d3")
        self.item_download = MetricItem("↓", color="#10ac84")
        net_col.addWidget(self.item_upload)
        net_col.addWidget(self.item_download)

        # 2. 磁盘列 (上: 读, 下: 写)
        disk_col = QVBoxLayout()
        disk_col.setContentsMargins(0, 0, 0, 0)
        disk_col.setSpacing(1)
        self.item_disk_read = MetricItem("读", color="#feca57")
        self.item_disk_write = MetricItem("写", color="#ff9f43")
        disk_col.addWidget(self.item_disk_read)
        disk_col.addWidget(self.item_disk_write)

        # 3. CPU 列 (上: 占用与温度)
        # 4. GPU 列 (下: 占用与温度)
        chip_col = QVBoxLayout()
        chip_col.setContentsMargins(0, 0, 0, 0)
        chip_col.setSpacing(1)
        self.item_cpu = MetricItem("CPU", color="#ff6b6b")
        self.item_gpu = MetricItem("GPU", color="#54a0ff")
        chip_col.addWidget(self.item_cpu)
        chip_col.addWidget(self.item_gpu)

        # 5. 内存列
        ram_col = QVBoxLayout()
        ram_col.setContentsMargins(0, 0, 0, 0)
        ram_col.setSpacing(1)
        self.item_ram = MetricItem("RAM", color="#5f27cd")
        self.item_ram_val = MetricItem("已用", color="#c8d6e5")
        ram_col.addWidget(self.item_ram)
        ram_col.addWidget(self.item_ram_val)

        # 组装到容器
        container_layout.addLayout(net_col)
        container_layout.addWidget(SeparatorLine())
        container_layout.addLayout(disk_col)
        container_layout.addWidget(SeparatorLine())
        container_layout.addLayout(chip_col)
        container_layout.addWidget(SeparatorLine())
        container_layout.addLayout(ram_col)

        outer_layout.addWidget(self.container)

        # 预设合理尺寸
        self.resize(360, 44)

    def showEvent(self, event):
        super().showEvent(event)
        # 配置免夺取焦点的 Windows 窗口样式
        setup_taskbar_window_style(int(self.winId()))
        self.align_to_taskbar()

    def align_to_taskbar(self):
        """对齐到任务栏托盘左边缘"""
        x, y, w, h = calculate_window_rect(self.width(), self.offset_x)
        # 居中垂直摆放
        margin_y = max(1, (h - self.height()) // 2)
        real_y = y + margin_y
        self.move(x, real_y)

    def update_metrics(self, m):
        """接收后台采样的系统指标并刷新 UI"""
        self.latest_metrics = m

        # 1. 网络
        self.item_upload.set_value(format_bytes_speed(m.upload_speed))
        self.item_download.set_value(format_bytes_speed(m.download_speed))

        # 2. 磁盘
        self.item_disk_read.set_value(format_bytes_speed(m.disk_read_speed))
        self.item_disk_write.set_value(format_bytes_speed(m.disk_write_speed))

        # 3. CPU 占用与温度
        cpu_temp_str = f"{int(m.cpu_temp)}℃" if m.cpu_temp > 0 else ""
        cpu_color = "#ff4757" if m.cpu_temp >= 75 else "#ff6b6b"
        self.item_cpu.set_value(f"{int(m.cpu_usage)}% {cpu_temp_str}".strip(), cpu_color)

        # 4. GPU 占用与温度
        gpu_temp_str = f"{int(m.gpu_temp)}℃" if m.gpu_temp > 0 else ""
        gpu_color = "#ff4757" if m.gpu_temp >= 75 else "#54a0ff"
        self.item_gpu.set_value(f"{int(m.gpu_usage)}% {gpu_temp_str}".strip(), gpu_color)

        # 5. 内存
        self.item_ram.set_value(f"{int(m.ram_usage)}%")
        self.item_ram_val.set_value(f"{m.ram_used_gb:.1f}G")

        # 更新悬浮卡片详细提示
        self.setToolTip(
            f"【系统硬件监控】\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"CPU: {m.cpu_name}\n"
            f"  • 使用率: {m.cpu_usage:.1f}%\n"
            f"  • 核心温度: {m.cpu_temp:.1f} ℃\n\n"
            f"GPU: {m.gpu_name}\n"
            f"  • 使用率: {m.gpu_usage:.1f}%\n"
            f"  • 核心温度: {m.gpu_temp:.1f} ℃\n\n"
            f"内存 (RAM):\n"
            f"  • 已用: {m.ram_used_gb:.2f} GB / {m.ram_total_gb:.2f} GB ({m.ram_usage:.1f}%)\n\n"
            f"网络流速:\n"
            f"  • 上传: {format_bytes_speed(m.upload_speed)}\n"
            f"  • 下载: {format_bytes_speed(m.download_speed)}\n\n"
            f"磁盘读写:\n"
            f"  • 读取: {format_bytes_speed(m.disk_read_speed)}\n"
            f"  • 写入: {format_bytes_speed(m.disk_write_speed)}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 提示: 单击打开任务管理器，右键弹出设置菜单"
        )

    # 鼠标交互：支持左键点击打开任务管理器，右键弹出菜单，中键拖拽微调
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # 记录拖动起点
            self.drag_start_pos = event.globalPos() - self.pos()
        elif event.button() == Qt.RightButton:
            self.show_context_menu(event.globalPos())

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_start_pos:
            new_pos = event.globalPos() - self.drag_start_pos
            # 锁定 Y 轴贴合任务栏，仅允许在任务栏横向微调
            self.move(new_pos.x(), self.y())
            # 计算新的偏移量
            tray_rect, notify_rect = calculate_window_rect(self.width(), 0)[:2], None
            # 暂停几秒自动重置
            self.pos_timer.stop()
            self.pos_timer.start(5000)

    def mouseDoubleClickEvent(self, event):
        """双击打开 Windows 任务管理器"""
        if event.button() == Qt.LeftButton:
            subprocess.Popen("taskmgr.exe")

    def show_context_menu(self, pos):
        """右键快捷设置菜单"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #252526;
                color: #ffffff;
                border: 1px solid #3e3e42;
                padding: 4px;
                font-family: 'Segoe UI', 'Microsoft YaHei';
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 24px 6px 12px;
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

        # 开机自启
        action_autostart = QAction("开机自动启动", menu, checkable=True)
        action_autostart.setChecked(is_autostart_enabled())
        action_autostart.triggered.connect(self._toggle_autostart)
        menu.addAction(action_autostart)

        menu.addSeparator()

        # 任务管理器
        action_taskmgr = QAction("打开任务管理器", menu)
        action_taskmgr.triggered.connect(lambda: subprocess.Popen("taskmgr.exe"))
        menu.addAction(action_taskmgr)

        # 重新对齐任务栏
        action_realign = QAction("重新对齐到任务栏托盘", menu)
        action_realign.triggered.connect(self.align_to_taskbar)
        menu.addAction(action_realign)

        menu.addSeparator()

        # 退出程序
        action_quit = QAction("退出程序", menu)
        action_quit.triggered.connect(self._quit_app)
        menu.addAction(action_quit)

        menu.exec_(pos)

    def _toggle_autostart(self, checked):
        set_autostart(checked)

    def _quit_app(self):
        from PyQt5.QtWidgets import QApplication
        QApplication.quit()
