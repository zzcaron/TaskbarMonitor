# -*- coding: utf-8 -*-
"""
任务栏硬件监控悬浮条界面
支持：完全透明原生悬浮 / 磨砂胶囊切换、显示项自由勾选、宽度智能收缩、文字微投影高清晰度与详细设置
"""

import os
import subprocess
from PyQt5.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout, QFrame,
    QMenu, QAction, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt5.QtGui import QFont, QCursor, QColor

from monitor import format_bytes_speed
from taskbar_helper import calculate_window_rect, setup_taskbar_window_style
from autostart import is_autostart_enabled, set_autostart
from config import load_config, save_config
from ui_settings import SettingsDialog


class MetricItem(QWidget):
    """单个监控项组件（标签 + 数值），支持高清晰度抗锯齿与深色文字投影"""
    def __init__(self, label_text, color="#ffffff", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 0, 3, 0)
        layout.setSpacing(4)

        base_font = QFont("Segoe UI Variable Display", 9, QFont.Bold)
        base_font.setStyleStrategy(QFont.PreferAntialias)

        # 指标标题标签
        self.lbl_title = QLabel(label_text)
        self.lbl_title.setFont(base_font)
        self.lbl_title.setStyleSheet("color: #dcdde1; font-size: 12px; font-weight: 700; font-family: 'Segoe UI Variable Display', 'Segoe UI', 'Microsoft YaHei UI';")

        # 指标数值标签
        self.lbl_value = QLabel("--")
        self.lbl_value.setFont(base_font)
        self.lbl_value.setStyleSheet(f"color: {color}; font-size: 12.5px; font-weight: 700; font-family: 'Segoe UI Variable Display', 'Segoe UI', 'Microsoft YaHei UI';")

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)

        self.shadow_title = None
        self.shadow_value = None

    def set_value(self, text, custom_color=None):
        """更新显示数值与可选颜色"""
        self.lbl_value.setText(text)
        if custom_color:
            self.lbl_value.setStyleSheet(f"color: {custom_color}; font-size: 12.5px; font-weight: 700; font-family: 'Segoe UI Variable Display', 'Segoe UI', 'Microsoft YaHei UI';")

    def set_shadow_enabled(self, enabled=True):
        """启用或关闭深色文字微投影，确保在任何壁纸底色下均极其清晰"""
        if enabled:
            shadow_t = QGraphicsDropShadowEffect(self)
            shadow_t.setBlurRadius(3)
            shadow_t.setColor(QColor(0, 0, 0, 240))
            shadow_t.setOffset(1, 1)
            self.lbl_title.setGraphicsEffect(shadow_t)

            shadow_v = QGraphicsDropShadowEffect(self)
            shadow_v.setBlurRadius(3)
            shadow_v.setColor(QColor(0, 0, 0, 240))
            shadow_v.setOffset(1, 1)
            self.lbl_value.setGraphicsEffect(shadow_v)
        else:
            self.lbl_title.setGraphicsEffect(None)
            self.lbl_value.setGraphicsEffect(None)


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

        # 加载用户持久化偏好
        self.cfg = load_config()
        self.offset_x = self.cfg.get("offset_x", -4)
        self.drag_start_pos = None

        # 初始化无边框、置顶、任务栏工具样式（免抢焦点）
        self.setWindowFlags(
            Qt.Window |
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._init_ui()
        self.apply_theme()
        self.update_layout_visibility()

        # 定位定时器：自动检测托盘变动并强力维持置顶
        self.pos_timer = QTimer(self)
        self.pos_timer.timeout.connect(self.align_to_taskbar)
        self.pos_timer.start(1000)

        # 存储当前最新监控指标用于 Tooltip 显示
        self.latest_metrics = None

    def changeEvent(self, event):
        """防止按 Win+D 或点击任务栏时被系统异常最小化"""
        if event.type() == event.WindowStateChange:
            if self.isMinimized():
                self.showNormal()
                self.align_to_taskbar()
        super().changeEvent(event)

    def _init_ui(self):
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(1, 2, 1, 2)

        # 主容器
        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        self.container_layout = QHBoxLayout(self.container)
        self.container_layout.setContentsMargins(8, 2, 8, 2)
        self.container_layout.setSpacing(6)

        # 1. 网络列 (上: 上传, 下: 下载)
        self.net_col_widget = QWidget(self)
        net_col = QVBoxLayout(self.net_col_widget)
        net_col.setContentsMargins(0, 0, 0, 0)
        net_col.setSpacing(1)
        self.item_upload = MetricItem("↑", color="#00f2fe")
        self.item_download = MetricItem("↓", color="#2ed573")
        net_col.addWidget(self.item_upload)
        net_col.addWidget(self.item_download)

        # 2. 磁盘列 (上: 读, 下: 写)
        self.disk_col_widget = QWidget(self)
        disk_col = QVBoxLayout(self.disk_col_widget)
        disk_col.setContentsMargins(0, 0, 0, 0)
        disk_col.setSpacing(1)
        self.item_disk_read = MetricItem("读", color="#ffd32a")
        self.item_disk_write = MetricItem("写", color="#ff9f43")
        disk_col.addWidget(self.item_disk_read)
        disk_col.addWidget(self.item_disk_write)

        # 3. 核心硬件列 (上: CPU, 下: GPU)
        self.chip_col_widget = QWidget(self)
        chip_col = QVBoxLayout(self.chip_col_widget)
        chip_col.setContentsMargins(0, 0, 0, 0)
        chip_col.setSpacing(1)
        self.item_cpu = MetricItem("CPU", color="#ff4d4d")
        self.item_gpu = MetricItem("GPU", color="#4bcffa")
        chip_col.addWidget(self.item_cpu)
        chip_col.addWidget(self.item_gpu)

        # 4. 内存列
        self.ram_col_widget = QWidget(self)
        ram_col = QVBoxLayout(self.ram_col_widget)
        ram_col.setContentsMargins(0, 0, 0, 0)
        ram_col.setSpacing(1)
        self.item_ram = MetricItem("RAM", color="#ef5777")
        self.item_ram_val = MetricItem("已用", color="#ffffff")
        ram_col.addWidget(self.item_ram)
        ram_col.addWidget(self.item_ram_val)

        # 分割线
        self.sep1 = SeparatorLine(self)
        self.sep2 = SeparatorLine(self)
        self.sep3 = SeparatorLine(self)

        # 组装到主容器
        self.container_layout.addWidget(self.net_col_widget)
        self.container_layout.addWidget(self.sep1)
        self.container_layout.addWidget(self.disk_col_widget)
        self.container_layout.addWidget(self.sep2)
        self.container_layout.addWidget(self.chip_col_widget)
        self.container_layout.addWidget(self.sep3)
        self.container_layout.addWidget(self.ram_col_widget)

        outer_layout.addWidget(self.container)

        self.all_metric_items = [
            self.item_upload, self.item_download,
            self.item_disk_read, self.item_disk_write,
            self.item_cpu, self.item_gpu,
            self.item_ram, self.item_ram_val
        ]

    def apply_theme(self):
        """应用背景模式与文字投影设置"""
        bg_style = self.cfg.get("bg_style", "transparent")
        enable_shadow = self.cfg.get("enable_shadow", True)

        if bg_style == "transparent":
            # 完全透明原生悬浮：无黑框，文字像系统原生部件直接漂在任务栏上
            self.container.setStyleSheet("""
                QFrame#MainContainer {
                    background-color: transparent;
                    border: none;
                }
            """)
        else:
            # 磨砂深黑胶囊卡片
            self.container.setStyleSheet("""
                QFrame#MainContainer {
                    background-color: rgba(16, 16, 20, 0.95);
                    border: 1px solid rgba(255, 255, 255, 0.18);
                    border-radius: 6px;
                }
            """)

        # 应用文字深色微投影
        for item in self.all_metric_items:
            item.set_shadow_enabled(enable_shadow)

    def update_layout_visibility(self):
        """根据当前配置智能收缩/展示各监控列，并动态调整窗口宽度自适应吸附"""
        show_net = self.cfg.get("show_net", True)
        show_disk = self.cfg.get("show_disk", True)
        show_cpu = self.cfg.get("show_cpu", True)
        show_gpu = self.cfg.get("show_gpu", True)
        show_ram = self.cfg.get("show_ram", True)

        # 控制单个 item 与整列显示
        self.net_col_widget.setVisible(show_net)
        self.disk_col_widget.setVisible(show_disk)

        self.item_cpu.setVisible(show_cpu)
        self.item_gpu.setVisible(show_gpu)
        self.chip_col_widget.setVisible(show_cpu or show_gpu)

        self.ram_col_widget.setVisible(show_ram)

        # 智能动态计算总宽度
        total_width = 18  # 基础 padding
        active_cols = []

        if show_net:
            total_width += 85
            active_cols.append("net")
        if show_disk:
            total_width += 85
            active_cols.append("disk")
        if show_cpu or show_gpu:
            total_width += 95
            active_cols.append("chip")
        if show_ram:
            total_width += 65
            active_cols.append("ram")

        # 动态控制分割线
        self.sep1.setVisible("net" in active_cols and len(active_cols) > 1 and active_cols[-1] != "net")
        self.sep2.setVisible("disk" in active_cols and ("chip" in active_cols or "ram" in active_cols))
        self.sep3.setVisible("chip" in active_cols and "ram" in active_cols)

        # 加上实际显示的分割线宽度
        total_width += (max(0, len(active_cols) - 1)) * 6

        # 至少保证合理最小宽度
        target_w = max(100, total_width)
        self.resize(target_w, 44)
        self.align_to_taskbar()

    def showEvent(self, event):
        super().showEvent(event)
        setup_taskbar_window_style(int(self.winId()))
        self.align_to_taskbar()

    def align_to_taskbar(self):
        """精准对齐到任务栏托盘左边缘并强力维持置顶防遮挡"""
        x, y, w, h = calculate_window_rect(self.width(), self.offset_x)
        margin_y = max(1, (h - self.height()) // 2)
        real_y = y + margin_y

        # 1. 先通过 Qt 原生移动到目标屏幕坐标
        self.move(x, real_y)

        # 2. 再调用底层 Windows API 强力维持 HWND_TOPMOST 顶层状态
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

    def update_metrics(self, m):
        """接收后台采样的系统指标并刷新 UI"""
        self.latest_metrics = m

        # 1. 网络
        if self.cfg.get("show_net", True):
            self.item_upload.set_value(format_bytes_speed(m.upload_speed))
            self.item_download.set_value(format_bytes_speed(m.download_speed))

        # 2. 磁盘
        if self.cfg.get("show_disk", True):
            self.item_disk_read.set_value(format_bytes_speed(m.disk_read_speed))
            self.item_disk_write.set_value(format_bytes_speed(m.disk_write_speed))

        # 3. CPU 占用与温度
        if self.cfg.get("show_cpu", True):
            cpu_temp_str = f"{int(m.cpu_temp)}℃" if m.cpu_temp > 0 else ""
            cpu_color = "#ff3838" if m.cpu_temp >= 75 else "#ff4d4d"
            self.item_cpu.set_value(f"{int(m.cpu_usage)}% {cpu_temp_str}".strip(), cpu_color)

        # 4. GPU 占用与温度
        if self.cfg.get("show_gpu", True):
            gpu_temp_str = f"{int(m.gpu_temp)}℃" if m.gpu_temp > 0 else ""
            gpu_color = "#ff3838" if m.gpu_temp >= 75 else "#4bcffa"
            self.item_gpu.set_value(f"{int(m.gpu_usage)}% {gpu_temp_str}".strip(), gpu_color)

        # 5. 内存
        if self.cfg.get("show_ram", True):
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
            f"💡 提示: 双击打开任务管理器，右键弹出偏好设置"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_pos = event.globalPos() - self.pos()
        elif event.button() == Qt.RightButton:
            self.show_context_menu(event.globalPos())

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_start_pos:
            new_pos = event.globalPos() - self.drag_start_pos
            self.move(new_pos.x(), self.y())
            self.pos_timer.stop()
            self.pos_timer.start(5000)

    def mouseDoubleClickEvent(self, event):
        """双击打开任务管理器"""
        if event.button() == Qt.LeftButton:
            subprocess.Popen("taskmgr.exe")

    def show_context_menu(self, pos):
        """右键快捷设置菜单"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #202024;
                color: #ffffff;
                border: 1px solid #3e3e42;
                padding: 4px;
                font-family: 'Segoe UI', 'Microsoft YaHei UI';
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 24px 6px 12px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #0984e3;
            }
            QMenu::separator {
                height: 1px;
                background-color: #3e3e42;
                margin: 4px 0px;
            }
        """)

        # 1. 显示项目快速勾选子菜单
        menu_items = menu.addMenu("📊 显示项目")
        menu_items.setStyleSheet(menu.styleSheet())

        for key, name in [
            ("show_net", "网络流速 (上传/下载)"),
            ("show_disk", "磁盘读写 (读/写)"),
            ("show_cpu", "CPU 监控 (占用/温度)"),
            ("show_gpu", "GPU 监控 (占用/温度)"),
            ("show_ram", "内存监控 (占用/已用)")
        ]:
            act = QAction(name, menu_items, checkable=True)
            act.setChecked(self.cfg.get(key, True))
            act.triggered.connect(lambda chk, k=key: self._toggle_display_item(k, chk))
            menu_items.addAction(act)

        # 2. 背景样式快速切换子菜单
        menu_bg = menu.addMenu("🎨 背景样式")
        menu_bg.setStyleSheet(menu.styleSheet())

        act_trans = QAction("完全透明 (文字悬浮任务栏)", menu_bg, checkable=True)
        act_trans.setChecked(self.cfg.get("bg_style", "transparent") == "transparent")
        act_trans.triggered.connect(lambda: self._set_bg_style("transparent"))
        menu_bg.addAction(act_trans)

        act_capsule = QAction("磨砂深黑胶囊卡片", menu_bg, checkable=True)
        act_capsule.setChecked(self.cfg.get("bg_style", "transparent") == "capsule")
        act_capsule.triggered.connect(lambda: self._set_bg_style("capsule"))
        menu_bg.addAction(act_capsule)

        menu.addSeparator()

        # 3. 详细设置对话框
        action_settings = QAction("⚙️ 偏好设置...", menu)
        action_settings.triggered.connect(self._open_settings_dialog)
        menu.addAction(action_settings)

        # 开机自启
        action_autostart = QAction("开机自动启动", menu, checkable=True)
        action_autostart.setChecked(is_autostart_enabled())
        action_autostart.triggered.connect(lambda chk: set_autostart(chk))
        menu.addAction(action_autostart)

        # 任务管理器
        action_taskmgr = QAction("打开任务管理器", menu)
        action_taskmgr.triggered.connect(lambda: subprocess.Popen("taskmgr.exe"))
        menu.addAction(action_taskmgr)

        # 重新对齐
        action_realign = QAction("重新对齐到任务栏托盘", menu)
        action_realign.triggered.connect(self.align_to_taskbar)
        menu.addAction(action_realign)

        menu.addSeparator()

        # 退出
        action_quit = QAction("退出程序", menu)
        action_quit.triggered.connect(self._quit_app)
        menu.addAction(action_quit)

        menu.exec_(pos)

    def _toggle_display_item(self, key, checked):
        """快捷切换单个显示项"""
        self.cfg[key] = checked
        save_config(self.cfg)
        self.update_layout_visibility()

    def _set_bg_style(self, style_name):
        """快捷切换背景模式"""
        self.cfg["bg_style"] = style_name
        save_config(self.cfg)
        self.apply_theme()

    def _open_settings_dialog(self):
        """弹出可视化偏好设置对话框"""
        dlg = SettingsDialog(self)
        dlg.settings_changed.connect(self.on_settings_updated)
        dlg.exec_()

    def on_settings_updated(self, new_cfg):
        """接收设置弹窗的实时更新"""
        self.cfg = new_cfg
        self.offset_x = new_cfg.get("offset_x", -4)
        self.apply_theme()
        self.update_layout_visibility()

    def _quit_app(self):
        from PyQt5.QtWidgets import QApplication
        QApplication.quit()
