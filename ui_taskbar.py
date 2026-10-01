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
from taskbar_helper import calculate_window_rect, setup_taskbar_window_style, is_screenshot_active, is_fullscreen_active
from autostart import is_autostart_enabled, set_autostart
from config import load_config, save_config
from ui_settings import SettingsDialog


class MetricItem(QWidget):
    """单个监控项组件（标签 + 数值），支持固定列宽防抖动、高清晰度抗锯齿与深色文字投影"""
    def __init__(self, label_text, color="#ffffff", title_width=None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        base_font = QFont("Segoe UI Variable Display", 9, QFont.Bold)
        base_font.setStyleStrategy(QFont.PreferAntialias)

        # 指标标题标签（支持定宽避免任何抖动）
        self.lbl_title = QLabel(label_text)
        self.lbl_title.setFont(base_font)
        if title_width:
            self.lbl_title.setFixedWidth(title_width)
        self.lbl_title.setStyleSheet("color: #dcdde1; font-size: 12px; font-weight: 700; font-family: 'Segoe UI Variable Display', 'Segoe UI', 'Microsoft YaHei UI';")

        # 指标数值标签（左对齐，预留充足展示位，数值变化绝不推移后方控件）
        self.lbl_value = QLabel("--")
        self.lbl_value.setFont(base_font)
        self.lbl_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_value.setStyleSheet(f"color: {color}; font-size: 12.5px; font-weight: 700; font-family: 'Segoe UI Variable Display', 'Segoe UI', 'Microsoft YaHei UI';")

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)
        layout.addStretch()

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

        # 定位定时器：高频极速检测托盘变动并强力维持置顶（0.3秒平滑守护，告别任何消失感）
        self.pos_timer = QTimer(self)
        self.pos_timer.timeout.connect(self.align_to_taskbar)
        self.pos_timer.start(300)

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

        # 1. 网络列 (定宽 78px，紧凑防抖)
        self.net_col_widget = QWidget(self)
        self.net_col_widget.setFixedWidth(78)
        net_col = QVBoxLayout(self.net_col_widget)
        net_col.setContentsMargins(0, 0, 0, 0)
        net_col.setSpacing(1)
        self.item_upload = MetricItem("↑", color="#00f2fe", title_width=12)
        self.item_download = MetricItem("↓", color="#2ed573", title_width=12)
        net_col.addWidget(self.item_upload)
        net_col.addWidget(self.item_download)

        # 2. 磁盘列 (定宽 84px)
        self.disk_col_widget = QWidget(self)
        self.disk_col_widget.setFixedWidth(84)
        disk_col = QVBoxLayout(self.disk_col_widget)
        disk_col.setContentsMargins(0, 0, 0, 0)
        disk_col.setSpacing(1)
        self.item_disk_read = MetricItem("读", color="#ffd32a", title_width=16)
        self.item_disk_write = MetricItem("写", color="#ff9f43", title_width=16)
        disk_col.addWidget(self.item_disk_read)
        disk_col.addWidget(self.item_disk_write)

        # 3. 核心硬件列 (定宽 96px)
        self.chip_col_widget = QWidget(self)
        self.chip_col_widget.setFixedWidth(96)
        chip_col = QVBoxLayout(self.chip_col_widget)
        chip_col.setContentsMargins(0, 0, 0, 0)
        chip_col.setSpacing(1)
        self.item_cpu = MetricItem("CPU", color="#ff4d4d", title_width=28)
        self.item_gpu = MetricItem("GPU", color="#4bcffa", title_width=28)
        chip_col.addWidget(self.item_cpu)
        chip_col.addWidget(self.item_gpu)

        # 4. 内存列 (定宽 62px)
        self.ram_col_widget = QWidget(self)
        self.ram_col_widget.setFixedWidth(62)
        ram_col = QVBoxLayout(self.ram_col_widget)
        ram_col.setContentsMargins(0, 0, 0, 0)
        ram_col.setSpacing(1)
        self.item_ram = MetricItem("RAM", color="#ef5777", title_width=28)
        self.item_ram_val = MetricItem("已用", color="#ffffff", title_width=28)
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
        """
        根据当前配置智能缩进与展示各监控列：
        各列具有严格固定宽度，数值变动绝不引起位置推移；
        当且仅当用户取消勾选某个项目时，后方项目才自动向左缩进。
        """
        show_net = self.cfg.get("show_net", True)
        show_disk = self.cfg.get("show_disk", True)
        show_cpu = self.cfg.get("show_cpu", True)
        show_gpu = self.cfg.get("show_gpu", True)
        show_ram = self.cfg.get("show_ram", True)

        # 1. 控制各列显示与隐藏
        self.net_col_widget.setVisible(show_net)
        self.disk_col_widget.setVisible(show_disk)

        self.item_cpu.setVisible(show_cpu)
        self.item_gpu.setVisible(show_gpu)
        self.chip_col_widget.setVisible(show_cpu or show_gpu)

        self.ram_col_widget.setVisible(show_ram)

        # 2. 精确固定列宽映射
        COL_WIDTHS = {
            "net": 78,
            "disk": 84,
            "chip": 96,
            "ram": 62
        }

        active_cols = []
        if show_net:
            active_cols.append("net")
        if show_disk:
            active_cols.append("disk")
        if show_cpu or show_gpu:
            active_cols.append("chip")
        if show_ram:
            active_cols.append("ram")

        # 3. 动态控制分割线可见性
        self.sep1.setVisible("net" in active_cols and len(active_cols) > 1 and active_cols[-1] != "net")
        self.sep2.setVisible("disk" in active_cols and ("chip" in active_cols or "ram" in active_cols))
        self.sep3.setVisible("chip" in active_cols and "ram" in active_cols)

        # 4. 精确计算总宽度并平滑吸附任务栏
        total_width = 16  # 容器左右 padding 边距
        for col in active_cols:
            total_width += COL_WIDTHS[col]
        if len(active_cols) > 1:
            total_width += (len(active_cols) - 1) * 6  # 分割线间隙

        target_w = max(80, total_width)
        self.resize(target_w, 44)
        self.align_to_taskbar()

    def showEvent(self, event):
        super().showEvent(event)
        setup_taskbar_window_style(int(self.winId()))
        self.align_to_taskbar()

    def align_to_taskbar(self):
        """精准对齐到任务栏托盘左边缘并强力维持置顶防遮挡"""
        # 1. 截屏或全屏独占程序（游戏/观影）时自动退避隐藏，退出全屏或截屏瞬间恢复
        should_hide = False
        if self.cfg.get("freeze_on_screenshot", True) and is_screenshot_active():
            should_hide = True
        elif self.cfg.get("hide_on_fullscreen", True) and is_fullscreen_active():
            should_hide = True

        if should_hide:
            if self.isVisible():
                self.hide()
            return
        else:
            if not self.isVisible():
                self.show()

        # 计算任务栏上的物理像素坐标 (phys_x, phys_y, w, h)
        phys_x, phys_y, phys_w, phys_h = calculate_window_rect(self.width(), self.offset_x)
        margin_y = max(1, (phys_h - self.height()) // 2)
        real_phys_y = phys_y + margin_y

        # 获取当前窗口的 DPI 缩放比例（支持 100%、125%、150%、200% 等非标高分屏）
        dpi_ratio = self.devicePixelRatioF() if hasattr(self, 'devicePixelRatioF') else 1.0
        if dpi_ratio <= 0:
            dpi_ratio = 1.0

        qt_x = int(phys_x / dpi_ratio)
        qt_y = int(real_phys_y / dpi_ratio)

        # 2. 逻辑坐标发生变动时才调用 Qt 原生移动，减少不必要的重绘
        if self.x() != qt_x or self.y() != qt_y:
            self.move(qt_x, qt_y)

        # 3. 调用底层 Windows API SetWindowPos（使用物理像素）强力维持 HWND_TOPMOST 顶层状态
        hwnd = int(self.winId())
        if hwnd:
            import ctypes
            user32 = ctypes.windll.user32
            HWND_TOPMOST = -1
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST,
                phys_x, real_phys_y, int(self.width() * dpi_ratio), int(self.height() * dpi_ratio),
                SWP_NOACTIVATE | SWP_SHOWWINDOW
            )

    def update_metrics(self, m):
        """接收后台采样的系统指标并刷新 UI"""
        # 截屏或全屏隐藏状态下：跳过数值更新与重绘，保持静默零开销
        if self.cfg.get("freeze_on_screenshot", True) and is_screenshot_active():
            if self.isVisible():
                self.hide()
            return
        if self.cfg.get("hide_on_fullscreen", True) and is_fullscreen_active():
            if self.isVisible():
                self.hide()
            return

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
            self._has_dragged = False
        elif event.button() == Qt.RightButton:
            self.show_context_menu(event.globalPos())

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_start_pos:
            new_pos = event.globalPos() - self.drag_start_pos
            if (new_pos - self.pos()).manhattanLength() > 2:
                self._has_dragged = True
            self.move(new_pos.x(), self.y())
            self.pos_timer.stop()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and getattr(self, '_has_dragged', False):
            self._has_dragged = False
            # 计算基准物理位置（offset_x=0 时的理论横坐标）
            base_phys_x, _, _, _ = calculate_window_rect(self.width(), 0)
            dpi_ratio = self.devicePixelRatioF() if hasattr(self, 'devicePixelRatioF') else 1.0
            if dpi_ratio <= 0:
                dpi_ratio = 1.0
            base_qt_x = int(base_phys_x / dpi_ratio)
            # 反算用户手动拖动产生的新偏好偏移 offset_x
            new_offset_x = self.x() - base_qt_x
            new_offset_x = max(-800, min(300, new_offset_x))
            self.offset_x = new_offset_x
            self.cfg["offset_x"] = new_offset_x
            save_config(self.cfg)

        self.pos_timer.start(300)

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

        # 截屏时自动定格
        action_freeze = QAction("截屏时自动定格暂停", menu, checkable=True)
        action_freeze.setChecked(self.cfg.get("freeze_on_screenshot", True))
        action_freeze.triggered.connect(self._toggle_freeze_screenshot)
        menu.addAction(action_freeze)

        # 全屏游戏/观影自动隐藏
        action_fullscreen = QAction("全屏游戏或视频时自动隐藏", menu, checkable=True)
        action_fullscreen.setChecked(self.cfg.get("hide_on_fullscreen", True))
        action_fullscreen.triggered.connect(self._toggle_hide_on_fullscreen)
        menu.addAction(action_fullscreen)

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
        action_realign.triggered.connect(self.reset_align_to_taskbar)
        menu.addAction(action_realign)

        menu.addSeparator()

        # 退出
        action_quit = QAction("退出程序", menu)
        action_quit.triggered.connect(self._quit_app)
        menu.addAction(action_quit)

        menu.exec_(pos)

    def reset_align_to_taskbar(self):
        """用户点击菜单重新对齐：重置所有拖动偏移量为初始默认值，并立即吸附归位"""
        DEFAULT_OFFSET_X = -4
        self.offset_x = DEFAULT_OFFSET_X
        self.cfg["offset_x"] = DEFAULT_OFFSET_X
        save_config(self.cfg)
        self.align_to_taskbar()

    def _toggle_display_item(self, key, checked):
        """快捷切换单个显示项"""
        self.cfg[key] = checked
        save_config(self.cfg)
        self.update_layout_visibility()

    def _toggle_freeze_screenshot(self, checked):
        """快捷切换截屏定格"""
        self.cfg["freeze_on_screenshot"] = checked
        save_config(self.cfg)

    def _toggle_hide_on_fullscreen(self, checked):
        """快捷切换全屏隐藏"""
        self.cfg["hide_on_fullscreen"] = checked
        save_config(self.cfg)
        self.align_to_taskbar()

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
