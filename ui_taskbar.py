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
    """单个监控项组件（标签 + 数值），支持高清晰度抗锯齿与高对比度排布"""
    def __init__(self, label_text, color="#ffffff", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 0, 3, 0)
        layout.setSpacing(4)

        # 优质抗锯齿字体配置
        base_font = QFont("Segoe UI Variable Display", 9, QFont.Bold)
        base_font.setStyleStrategy(QFont.PreferAntialias)

        # 指标名称标签（明亮清晰高对比度）
        self.lbl_title = QLabel(label_text)
        self.lbl_title.setFont(base_font)
        self.lbl_title.setStyleSheet("color: #dcdde1; font-size: 12px; font-weight: 700; font-family: 'Segoe UI Variable Display', 'Segoe UI', 'Microsoft YaHei UI';")

        # 指标实时数值标签（粗体锐利数字）
        self.lbl_value = QLabel("--")
        self.lbl_value.setFont(base_font)
        self.lbl_value.setStyleSheet(f"color: {color}; font-size: 12.5px; font-weight: 700; font-family: 'Segoe UI Variable Display', 'Segoe UI', 'Microsoft YaHei UI';")

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)

    def set_value(self, text, custom_color=None):
        """更新显示数值与可选颜色"""
        self.lbl_value.setText(text)
        if custom_color:
            self.lbl_value.setStyleSheet(f"color: {custom_color}; font-size: 12.5px; font-weight: 700; font-family: 'Segoe UI Variable Display', 'Segoe UI', 'Microsoft YaHei UI';")


class SeparatorLine(QFrame):
    """细竖直分割线"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.VLine)
        self.setFrameShadow(QFrame.Sunken)
        self.setStyleSheet("color: rgba(255, 255, 255, 0.22); margin-top: 5px; margin-bottom: 5px;")


class TaskbarMonitorWidget(QWidget):
    """任务栏监控主窗口"""
    def __init__(self, parent=None):
        super().__init__(parent)

        # 偏移微调（用户自定义）
        self.offset_x = -4
        self.drag_start_pos = None

        # 初始化无边框、置顶、任务栏工具样式（去掉 SubWindow，加入 Window 和免焦点）
        self.setWindowFlags(
            Qt.Window |
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # 整体界面风格：深色纯黑微磨砂胶囊风格，杜绝背景杂色穿透
        self.setStyleSheet("""
            QWidget#MainContainer {
                background-color: rgba(16, 16, 20, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 6px;
            }
        """)

        self._init_ui()

        # 定位定时器：自动检测托盘变动并强力维持置顶
        self.pos_timer = QTimer(self)
        self.pos_timer.timeout.connect(self.align_to_taskbar)
        self.pos_timer.start(1000)

        # 存储当前最新监控指标用于 Tooltip 显示
        self.latest_metrics = None

    def changeEvent(self, event):
        """防止按 Win+D 或点击任务栏时被系统异常最小化或掩盖"""
        if event.type() == event.WindowStateChange:
            if self.isMinimized():
                self.showNormal()
                self.align_to_taskbar()
        super().changeEvent(event)

    def _init_ui(self):
        # 外层布局
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(1, 2, 1, 2)

        # 内部主容器
        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(8, 2, 8, 2)
        container_layout.setSpacing(6)

        # 1. 网络列 (上: 上传, 下: 下载) - 亮青 / 鲜翠绿
        net_col = QVBoxLayout()
        net_col.setContentsMargins(0, 0, 0, 0)
        net_col.setSpacing(1)
        self.item_upload = MetricItem("↑", color="#00f2fe")
        self.item_download = MetricItem("↓", color="#2ed573")
        net_col.addWidget(self.item_upload)
        net_col.addWidget(self.item_download)

        # 2. 磁盘列 (上: 读, 下: 写) - 亮琥珀金 / 活力亮橙
        disk_col = QVBoxLayout()
        disk_col.setContentsMargins(0, 0, 0, 0)
        disk_col.setSpacing(1)
        self.item_disk_read = MetricItem("读", color="#ffd32a")
        self.item_disk_write = MetricItem("写", color="#ff9f43")
        disk_col.addWidget(self.item_disk_read)
        disk_col.addWidget(self.item_disk_write)

        # 3. CPU 列 (上: 占用与温度) - 醒目珊瑚红
        # 4. GPU 列 (下: 占用与温度) - 晴空亮蓝
        chip_col = QVBoxLayout()
        chip_col.setContentsMargins(0, 0, 0, 0)
        chip_col.setSpacing(1)
        self.item_cpu = MetricItem("CPU", color="#ff4d4d")
        self.item_gpu = MetricItem("GPU", color="#4bcffa")
        chip_col.addWidget(self.item_cpu)
        chip_col.addWidget(self.item_gpu)

        # 5. 内存列 - 极光紫 / 高亮纯白
        ram_col = QVBoxLayout()
        ram_col.setContentsMargins(0, 0, 0, 0)
        ram_col.setSpacing(1)
        self.item_ram = MetricItem("RAM", color="#ef5777")
        self.item_ram_val = MetricItem("已用", color="#ffffff")
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

        # 预设合理尺寸（字号放大后拓宽至 390px 保证各数值舒展）
        self.resize(390, 44)

    def showEvent(self, event):
        super().showEvent(event)
        # 配置免夺取焦点的 Windows 窗口样式
        setup_taskbar_window_style(int(self.winId()))
        self.align_to_taskbar()

    def align_to_taskbar(self):
        """对齐到任务栏托盘左边缘并强力维持置顶防遮挡"""
        x, y, w, h = calculate_window_rect(self.width(), self.offset_x)
        margin_y = max(1, (h - self.height()) // 2)
        real_y = y + margin_y

        hwnd = int(self.winId())
        if hwnd:
            import ctypes
            user32 = ctypes.windll.user32
            HWND_TOPMOST = -1
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST,
                x, real_y, self.width(), self.height(),
                SWP_NOACTIVATE | SWP_SHOWWINDOW
            )
        else:
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

        # 3. CPU 占用与温度（明亮粉红/珊瑚红，高温警示亮红）
        cpu_temp_str = f"{int(m.cpu_temp)}℃" if m.cpu_temp > 0 else ""
        cpu_color = "#ff3838" if m.cpu_temp >= 75 else "#ff4d4d"
        self.item_cpu.set_value(f"{int(m.cpu_usage)}% {cpu_temp_str}".strip(), cpu_color)

        # 4. GPU 占用与温度（明亮晴空蓝，高温警示亮红）
        gpu_temp_str = f"{int(m.gpu_temp)}℃" if m.gpu_temp > 0 else ""
        gpu_color = "#ff3838" if m.gpu_temp >= 75 else "#4bcffa"
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
