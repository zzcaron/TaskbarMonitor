# -*- coding: utf-8 -*-
"""
任务栏硬件监控悬浮条界面
优化点：
1. 全面修复高 DPI 物理像素/逻辑像素混用问题，拖动与自动吸附均按精确物理像素计算；
2. MetricItem 缓存文本与颜色，消除每秒无意义 setStyleSheet 重排；
3. 按需响应 QEvent.ToolTip 动态生成悬浮硬件详情（包含显存利用率及无管理员权限温度提示），杜绝非悬停期字符串拼接；
4. 自动适配 Windows 浅色/深色任务栏主题，感知 Explorer 重启与任务栏自动隐藏；
5. 修复右键连弹两次菜单、快捷菜单可关闭全部监控项、设置弹窗多开及非管理员双击任务管理器报 WinError 740 等问题；
6. 对外发射 config_changed 信号，保证后台采样频率、网卡过滤、显卡策略实时生效无需重启。
"""

from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolTip,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter

from autostart import is_autostart_enabled, set_autostart
from config import (
    DEFAULT_CONFIG,
    DISPLAY_KEYS,
    OFFSET_X_MAX,
    OFFSET_X_MIN,
    load_config,
    sanitize_config,
    save_config,
)
from monitor import format_bytes_speed
from taskbar_helper import (
    calculate_window_rect,
    ensure_topmost,
    get_cursor_phys_pos,
    get_drag_phys_bounds,
    get_taskbar_hwnd,
    get_taskbar_logical_height,
    get_window_phys_rect,
    is_fullscreen_active,
    is_screenshot_active,
    is_taskbar_light_theme,
    is_taskbar_retracted,
    move_window_phys,
    open_task_manager,
    round_phys,
    set_exclude_from_capture,
    setup_taskbar_window_style,
)
from ui_settings import SettingsDialog

# 深色/浅色任务栏双套高可读配色表
PALETTES = {
    "dark": {
        "title": "#dcdde1",
        "upload": "#00f2fe",
        "download": "#2ed573",
        "disk_read": "#ffd32a",
        "disk_write": "#ff9f43",
        "cpu": "#ff6b6b",
        "cpu_hot": "#ff3838",
        "gpu": "#4bcffa",
        "gpu_hot": "#ff3838",
        "ram": "#ef5777",
        "ram_val": "#ffffff",
        "sep": "rgba(255, 255, 255, 0.22)",
        "capsule_bg": "rgba(16, 16, 20, 0.92)",
        "capsule_border": "rgba(255, 255, 255, 0.18)",
        "shadow": QColor(0, 0, 0, 235),
    },
    "light": {
        "title": "#334155",
        "upload": "#0284c7",
        "download": "#15803d",
        "disk_read": "#b45309",
        "disk_write": "#c2410c",
        "cpu": "#dc2626",
        "cpu_hot": "#991b1b",
        "gpu": "#0369a1",
        "gpu_hot": "#991b1b",
        "ram": "#be123c",
        "ram_val": "#0f172a",
        "sep": "rgba(15, 23, 42, 0.20)",
        "capsule_bg": "rgba(248, 250, 252, 0.92)",
        "capsule_border": "rgba(15, 23, 42, 0.16)",
        "shadow": QColor(255, 255, 255, 190),
    },
}

MENU_STYLESHEET = """
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
"""


class MetricItem(QWidget):
    """单个监控项组件（标签 + 数值），内置文本与颜色缓存，避免重复样式表解析。"""

    FONT_FAMILY = "'Segoe UI Variable Display', 'Segoe UI', 'Microsoft YaHei UI'"

    def __init__(self, label_text, color="#ffffff", title_width=None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        base_font = QFont("Segoe UI Variable Display", 9, QFont.Bold)
        base_font.setStyleStrategy(QFont.PreferAntialias)

        self.lbl_title = QLabel(label_text)
        self.lbl_title.setFont(base_font)
        if title_width:
            self.lbl_title.setFixedWidth(title_width)

        self.lbl_value = QLabel("--")
        self.lbl_value.setFont(base_font)
        self.lbl_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)
        layout.addStretch()

        self._last_text = "--"
        self._last_title_color = None
        self._last_value_color = None
        self._title_font_px = 12
        self._value_font_px = 12
        self.set_colors("#dcdde1", color)

    def _apply_title_style(self):
        self.lbl_title.setStyleSheet(
            f"color: {self._last_title_color}; font-size: {self._title_font_px}px; font-weight: 700; font-family: {self.FONT_FAMILY};"
        )

    def _apply_value_style(self):
        self.lbl_value.setStyleSheet(
            f"color: {self._last_value_color}; font-size: {self._value_font_px}px; font-weight: 700; font-family: {self.FONT_FAMILY};"
        )

    def set_font_sizes(self, title_px: int, value_px: int):
        """按任务栏高度动态适配整数像素字号（Qt QSS 仅解析整数 px）。"""
        t_px = int(round(title_px))
        v_px = int(round(value_px))
        if t_px != self._title_font_px:
            self._title_font_px = t_px
            if self._last_title_color:
                self._apply_title_style()
        if v_px != self._value_font_px:
            self._value_font_px = v_px
            if self._last_value_color:
                self._apply_value_style()

    def set_colors(self, title_color: str, value_color: str):
        """仅在颜色变化时更新样式，大幅降低 Qt 样式重排开销。"""
        if title_color != self._last_title_color:
            self._last_title_color = title_color
            self._apply_title_style()
        if value_color != self._last_value_color:
            self._last_value_color = value_color
            self._apply_value_style()

    def set_value(self, text: str, custom_color: str = None):
        """更新显示数值与可选颜色（带差异缓存）。"""
        if text != self._last_text:
            self._last_text = text
            self.lbl_value.setText(text)
        if custom_color and custom_color != self._last_value_color:
            self._last_value_color = custom_color
            self._apply_value_style()

    def set_shadow_enabled(self, enabled: bool = True, shadow_color: QColor = None):
        """启用或关闭文字微投影。"""
        if enabled:
            color = shadow_color or QColor(0, 0, 0, 235)
            for lbl in (self.lbl_title, self.lbl_value):
                eff = lbl.graphicsEffect()
                if not isinstance(eff, QGraphicsDropShadowEffect):
                    eff = QGraphicsDropShadowEffect(self)
                    eff.setBlurRadius(3)
                    eff.setOffset(1, 1)
                    lbl.setGraphicsEffect(eff)
                eff.setColor(color)
        else:
            self.lbl_title.setGraphicsEffect(None)
            self.lbl_value.setGraphicsEffect(None)


class SeparatorLine(QFrame):
    """细竖直分割线"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.VLine)
        self.setFrameShadow(QFrame.Sunken)
        self._last_rgba = "rgba(255, 255, 255, 0.22)"
        self._last_compact = False
        self.set_color(self._last_rgba, compact=False)

    def set_color(self, rgba: str, compact: bool = False):
        self._last_rgba = rgba
        self._last_compact = compact
        margin = 3 if compact else 5
        self.setStyleSheet(f"color: {rgba}; margin-top: {margin}px; margin-bottom: {margin}px;")


class TaskbarMonitorWidget(QWidget):
    """任务栏监控主窗口"""

    config_changed = pyqtSignal(dict)

    def __init__(self, initial_cfg=None, parent=None):
        super().__init__(parent)

        self.cfg = sanitize_config(initial_cfg) if initial_cfg is not None else load_config()
        self.offset_x = self.cfg.get("offset_x", DEFAULT_CONFIG["offset_x"])
        self.drag_start_pos = None
        self._drag_press_global = None
        self._drag_press_cursor_phys = None
        self._drag_start_rect_phys = None
        self._drag_use_qt_fallback = False
        self._has_dragged = False
        self._settings_dlg = None

        # 窗口底层状态追踪
        self._bound_tray_hwnd = 0
        self._capture_excluded = False
        self._last_phys_rect = None
        self._active_palette_key = "dark"
        self._theme_poll_counter = 0
        self._shown_once = False
        self._aligning = False
        self._density_state = None
        self._last_layout_env = None

        # 初始化无边框、置顶、任务栏工具样式（免抢焦点）
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._init_ui()
        self.apply_theme()
        self.update_layout_visibility()

        # 守护定时器：350ms 轻量检查全屏/任务栏状态与 Explorer 重启
        self.pos_timer = QTimer(self)
        self.pos_timer.timeout.connect(self.align_to_taskbar)
        self.pos_timer.start(350)

        self.latest_metrics = None

    def _get_dpi_ratio(self) -> float:
        dpi_ratio = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        return dpi_ratio if dpi_ratio and dpi_ratio > 0 else 1.0

    def _resolve_palette_key(self) -> str:
        mode = self.cfg.get("theme_mode", "auto")
        if mode in ("dark", "light"):
            return mode
        return "light" if is_taskbar_light_theme() else "dark"

    def changeEvent(self, event):
        """防止按 Win+D 或点击任务栏时被系统最小化。"""
        if event.type() == QEvent.WindowStateChange:
            if self.isMinimized():
                self.showNormal()
                self._last_phys_rect = None
                self.align_to_taskbar()
        super().changeEvent(event)

    def event(self, ev):
        """按需生成详细硬件悬浮卡片，避免非悬停期间每秒无意义字符串拼接。"""
        if ev.type() == QEvent.ToolTip:
            tooltip_text = self._build_tooltip_text()
            if tooltip_text:
                QToolTip.showText(ev.globalPos(), tooltip_text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(ev)

    def _build_tooltip_text(self) -> str:
        m = self.latest_metrics
        if m is None:
            return "正在采集硬件传感器数据..."

        cpu_temp_line = f"{m.cpu_temp:.1f} ℃" if m.cpu_temp > 0 else (
            "未读取到传感器 (建议以管理员身份运行)" if not m.is_admin else "当前硬件未上报"
        )
        gpu_temp_line = f"{m.gpu_temp:.1f} ℃" if m.gpu_temp > 0 else "未上报"
        gpu_vram_line = f"\n  • 显存利用率: {m.gpu_mem_usage:.1f}%" if m.gpu_mem_usage > 0 else ""

        return (
            f"【系统硬件监控】\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"CPU: {m.cpu_name}\n"
            f"  • 使用率: {m.cpu_usage:.1f}%\n"
            f"  • 核心温度: {cpu_temp_line}\n\n"
            f"GPU: {m.gpu_name}\n"
            f"  • 核心利用率: {m.gpu_usage:.1f}%{gpu_vram_line}\n"
            f"  • 核心温度: {gpu_temp_line}\n\n"
            f"内存 (RAM):\n"
            f"  • 已用: {m.ram_used_gb:.2f} GB / {m.ram_total_gb:.2f} GB ({m.ram_usage:.1f}%)\n\n"
            f"网络流速:\n"
            f"  • 上传: {format_bytes_speed(m.upload_speed)}\n"
            f"  • 下载: {format_bytes_speed(m.download_speed)}\n\n"
            f"磁盘读写:\n"
            f"  • 读取: {format_bytes_speed(m.disk_read_speed)}\n"
            f"  • 写入: {format_bytes_speed(m.disk_write_speed)}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"提示: 双击打开任务管理器，左键拖动微调，右键设置"
        )

    def _init_ui(self):
        self.outer_layout = QHBoxLayout(self)
        self.outer_layout.setContentsMargins(1, 2, 1, 2)

        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        self.container_layout = QHBoxLayout(self.container)
        self.container_layout.setContentsMargins(8, 2, 8, 2)
        self.container_layout.setSpacing(6)

        # 1. 网络列
        self.net_col_widget = QWidget(self)
        self.net_col_widget.setFixedWidth(78)
        net_col = QVBoxLayout(self.net_col_widget)
        net_col.setContentsMargins(0, 0, 0, 0)
        net_col.setSpacing(1)
        self.item_upload = MetricItem("↑", color="#00f2fe", title_width=12)
        self.item_download = MetricItem("↓", color="#2ed573", title_width=12)
        net_col.addWidget(self.item_upload)
        net_col.addWidget(self.item_download)

        # 2. 磁盘列
        self.disk_col_widget = QWidget(self)
        self.disk_col_widget.setFixedWidth(84)
        disk_col = QVBoxLayout(self.disk_col_widget)
        disk_col.setContentsMargins(0, 0, 0, 0)
        disk_col.setSpacing(1)
        self.item_disk_read = MetricItem("读", color="#ffd32a", title_width=16)
        self.item_disk_write = MetricItem("写", color="#ff9f43", title_width=16)
        disk_col.addWidget(self.item_disk_read)
        disk_col.addWidget(self.item_disk_write)

        # 3. 核心硬件列
        self.chip_col_widget = QWidget(self)
        self.chip_col_widget.setFixedWidth(96)
        chip_col = QVBoxLayout(self.chip_col_widget)
        chip_col.setContentsMargins(0, 0, 0, 0)
        chip_col.setSpacing(1)
        self.item_cpu = MetricItem("CPU", color="#ff6b6b", title_width=28)
        self.item_gpu = MetricItem("GPU", color="#4bcffa", title_width=28)
        chip_col.addWidget(self.item_cpu)
        chip_col.addWidget(self.item_gpu)

        # 4. 内存列
        self.ram_col_widget = QWidget(self)
        self.ram_col_widget.setFixedWidth(62)
        ram_col = QVBoxLayout(self.ram_col_widget)
        ram_col.setContentsMargins(0, 0, 0, 0)
        ram_col.setSpacing(1)
        self.item_ram = MetricItem("RAM", color="#ef5777", title_width=28)
        self.item_ram_val = MetricItem("已用", color="#ffffff", title_width=28)
        ram_col.addWidget(self.item_ram)
        ram_col.addWidget(self.item_ram_val)

        self.sep1 = SeparatorLine(self)
        self.sep2 = SeparatorLine(self)
        self.sep3 = SeparatorLine(self)

        self.container_layout.addWidget(self.net_col_widget)
        self.container_layout.addWidget(self.sep1)
        self.container_layout.addWidget(self.disk_col_widget)
        self.container_layout.addWidget(self.sep2)
        self.container_layout.addWidget(self.chip_col_widget)
        self.container_layout.addWidget(self.sep3)
        self.container_layout.addWidget(self.ram_col_widget)

        self.outer_layout.addWidget(self.container)
        self._col_layouts = (net_col, disk_col, chip_col, ram_col)

        self.all_metric_items = [
            self.item_upload,
            self.item_download,
            self.item_disk_read,
            self.item_disk_write,
            self.item_cpu,
            self.item_gpu,
            self.item_ram,
            self.item_ram_val,
        ]

    def _apply_taskbar_density(self, taskbar_h: int):
        """按任务栏可用逻辑高度适配外边距、行距与字体大小，防止 Win10 40px 及小任务栏内容被裁切。"""
        is_capsule = self.cfg.get("bg_style", "transparent") == "capsule"
        if taskbar_h <= 34:
            density = ("ultra", is_capsule)
            outer_margins = (1, 0, 1, 0)
            container_margins = (6, 0, 6, 0)
            col_spacing = 0
            font_sizes = (9, 9)
            item_fixed_h = None
            sep_compact = True
        elif taskbar_h <= 42:
            density = ("compact", is_capsule)
            outer_margins = (1, 0 if is_capsule else 1, 1, 0 if is_capsule else 1)
            container_margins = (8, 1, 8, 1)
            col_spacing = 0
            font_sizes = (11, 12)
            item_fixed_h = None
            sep_compact = True
        else:
            density = ("normal", is_capsule)
            outer_margins = (1, 2, 1, 2)
            container_margins = (8, 2, 8, 2)
            col_spacing = 1
            font_sizes = (12, 12)
            item_fixed_h = None
            sep_compact = False

        if density == self._density_state:
            return
        self._density_state = density

        self.outer_layout.setContentsMargins(*outer_margins)
        self.container_layout.setContentsMargins(*container_margins)
        for col_layout in self._col_layouts:
            col_layout.setSpacing(col_spacing)
        for item in self.all_metric_items:
            item.set_font_sizes(*font_sizes)
            if item_fixed_h is not None:
                item.setFixedHeight(item_fixed_h)
            else:
                item.setMinimumHeight(0)
                item.setMaximumHeight(16777215)
        for sep in (self.sep1, self.sep2, self.sep3):
            sep.set_color(sep._last_rgba, compact=sep_compact)

    def _sync_widget_size(self):
        """同步触发布局重算并按精确 sizeHint 与任务栏高度调整窗口尺寸。"""
        dpi_ratio = self._get_dpi_ratio()
        taskbar_h = get_taskbar_logical_height(dpi_ratio)
        self._last_layout_env = (taskbar_h, round(dpi_ratio, 3))
        self._apply_taskbar_density(taskbar_h)

        # 显式使两级布局失效并立即重算，确保隐藏列后 minimumSize 立刻更新，窗口可顺利缩回
        self.container_layout.invalidate()
        self.container_layout.activate()
        self.outer_layout.invalidate()
        self.outer_layout.activate()

        hint = self.sizeHint()
        target_w = max(80, hint.width())
        if taskbar_h <= 34:
            target_h = max(1, min(taskbar_h, hint.height()))
        elif taskbar_h <= 42:
            target_h = max(1, min(taskbar_h, max(38, hint.height())))
        else:
            target_h = max(1, min(taskbar_h, max(44, hint.height())))

        self.resize(target_w, target_h)
        self._last_phys_rect = None
        if self._shown_once and not self._aligning:
            self.align_to_taskbar()

    def apply_theme(self):
        """应用背景模式、浅/深色任务栏调色板与文字投影设置。"""
        bg_style = self.cfg.get("bg_style", "transparent")
        enable_shadow = self.cfg.get("enable_shadow", True)
        self._active_palette_key = self._resolve_palette_key()
        pal = PALETTES[self._active_palette_key]

        if bg_style == "transparent":
            # #01000000 视觉全透明，同时保证 Windows DWM 正常命中鼠标事件不穿透到任务栏
            self.container.setStyleSheet("""
                QFrame#MainContainer {
                    background-color: #01000000;
                    border: none;
                }
            """)
        else:
            self.container.setStyleSheet(f"""
                QFrame#MainContainer {{
                    background-color: {pal['capsule_bg']};
                    border: 1px solid {pal['capsule_border']};
                    border-radius: 6px;
                }}
            """)

        # 同步各指标调色板与分割线
        self.item_upload.set_colors(pal["title"], pal["upload"])
        self.item_download.set_colors(pal["title"], pal["download"])
        self.item_disk_read.set_colors(pal["title"], pal["disk_read"])
        self.item_disk_write.set_colors(pal["title"], pal["disk_write"])
        self.item_cpu.set_colors(pal["title"], pal["cpu"])
        self.item_gpu.set_colors(pal["title"], pal["gpu"])
        self.item_ram.set_colors(pal["title"], pal["ram"])
        self.item_ram_val.set_colors(pal["title"], pal["ram_val"])

        sep_compact = self._density_state is not None and self._density_state[0] in ("compact", "ultra")
        for sep in (self.sep1, self.sep2, self.sep3):
            sep.set_color(pal["sep"], compact=sep_compact)

        # 浅色胶囊卡片下无需重投影，透明模式或深色模式下启用微投影
        use_shadow = enable_shadow and not (bg_style == "capsule" and self._active_palette_key == "light")
        for item in self.all_metric_items:
            item.set_shadow_enabled(use_shadow, pal["shadow"])

        self._apply_capture_protection()
        self._sync_widget_size()

    def _apply_capture_protection(self):
        """按配置开启或关闭 Windows 原生防截屏属性。"""
        if not self._shown_once:
            return
        hwnd = int(self.winId())
        if not hwnd:
            return
        want_exclude = bool(self.cfg.get("freeze_on_screenshot", True))
        if want_exclude:
            self._capture_excluded = set_exclude_from_capture(hwnd, True)
        else:
            set_exclude_from_capture(hwnd, False)
            self._capture_excluded = False

    def update_layout_visibility(self):
        """根据配置动态显示各监控列并精确计算紧凑总尺寸。"""
        show_net = self.cfg.get("show_net", True)
        show_disk = self.cfg.get("show_disk", True)
        show_cpu = self.cfg.get("show_cpu", True)
        show_gpu = self.cfg.get("show_gpu", True)
        show_ram = self.cfg.get("show_ram", True)

        self.net_col_widget.setVisible(show_net)
        self.disk_col_widget.setVisible(show_disk)
        self.item_cpu.setVisible(show_cpu)
        self.item_gpu.setVisible(show_gpu)
        self.chip_col_widget.setVisible(show_cpu or show_gpu)
        self.ram_col_widget.setVisible(show_ram)

        active_cols = []
        if show_net:
            active_cols.append("net")
        if show_disk:
            active_cols.append("disk")
        if show_cpu or show_gpu:
            active_cols.append("chip")
        if show_ram:
            active_cols.append("ram")

        self.sep1.setVisible("net" in active_cols and len(active_cols) > 1 and active_cols[-1] != "net")
        self.sep2.setVisible("disk" in active_cols and ("chip" in active_cols or "ram" in active_cols))
        self.sep3.setVisible("chip" in active_cols and "ram" in active_cols)

        self._sync_widget_size()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))

    def _realign_after_show(self):
        """在 Qt 完成首次 show 事件与平台窗口 expose 同步后二次对齐，消除非整数 DPI 下的 1px 纵向覆盖偏差。"""
        if self._shown_once and self.isVisible() and not self._aligning:
            self._last_phys_rect = None
            self.align_to_taskbar()

    def showEvent(self, event):
        super().showEvent(event)
        self._shown_once = True
        hwnd = int(self.winId())
        self._bound_tray_hwnd = setup_taskbar_window_style(hwnd)
        self._apply_capture_protection()
        self._last_phys_rect = None
        if not self._aligning:
            self.align_to_taskbar()
        QTimer.singleShot(60, self._realign_after_show)

    def align_to_taskbar(self):
        """
        精准对齐到任务栏托盘左边缘并低开销维持置顶：
        - 感知 Explorer 重启并自动重新绑定 Owner；
        - 感知自动隐藏任务栏缩起、主屏全屏应用及旧版系统截屏；
        - 仅在物理几何发生变化时才执行移动/缩放，否则仅做轻量 Z-order 维持。
        """
        if not self._shown_once or self._aligning:
            return
        self._aligning = True
        try:
            hwnd = int(self.winId())
            if not hwnd:
                return

            # 1. 自动跟随系统浅/深色任务栏切换（每 ~3.5 秒检查一次注册表，开销极低）
            if self.cfg.get("theme_mode", "auto") == "auto":
                self._theme_poll_counter += 1
                if self._theme_poll_counter >= 10:
                    self._theme_poll_counter = 0
                    detected = "light" if is_taskbar_light_theme() else "dark"
                    if detected != self._active_palette_key:
                        self.apply_theme()

            # 2. 感知 explorer.exe 重启，Shell_TrayWnd 句柄变化时自动重新绑定防覆盖样式
            cur_tray_hwnd = get_taskbar_hwnd()
            if cur_tray_hwnd and cur_tray_hwnd != self._bound_tray_hwnd:
                self._bound_tray_hwnd = setup_taskbar_window_style(hwnd)
                self._apply_capture_protection()
                self._last_phys_rect = None

            # 3. 判定是否需要临时隐藏（自动隐藏任务栏已缩起 / 主屏全屏独占 / 旧版 Win10 截屏降级）
            should_hide = False
            if is_taskbar_retracted(cur_tray_hwnd):
                should_hide = True
            elif self.cfg.get("hide_on_fullscreen", True) and is_fullscreen_active(cur_tray_hwnd):
                should_hide = True
            elif (
                self.cfg.get("freeze_on_screenshot", True)
                and not self._capture_excluded
                and is_screenshot_active()
            ):
                should_hide = True

            if should_hide:
                if self.isVisible():
                    self.hide()
                    self._last_phys_rect = None
                return

            just_shown = False
            if not self.isVisible():
                self.show()
                just_shown = True

            # 4. 感知任务栏高度或 DPI 动态变化，并严格按物理像素计算目标坐标与尺寸
            dpi_ratio = self._get_dpi_ratio()
            cur_taskbar_h = get_taskbar_logical_height(dpi_ratio)
            cur_env = (cur_taskbar_h, round(dpi_ratio, 3))
            if cur_env != self._last_layout_env:
                self._sync_widget_size()

            phys_w = round_phys(self.width() * dpi_ratio)
            phys_h = round_phys(self.height() * dpi_ratio)
            phys_offset_x = round_phys(self.offset_x * dpi_ratio)

            target_rect = calculate_window_rect(phys_w, phys_h, phys_offset_x, dpi_ratio)
            cur_rect = get_window_phys_rect(hwnd)
            cur_xywh = (cur_rect[0], cur_rect[1], cur_rect[2] - cur_rect[0], cur_rect[3] - cur_rect[1]) if cur_rect else None
            if just_shown or target_rect != self._last_phys_rect or (cur_xywh is not None and cur_xywh != target_rect):
                move_window_phys(hwnd, *target_rect)
                self._last_phys_rect = target_rect
            elif QApplication.activePopupWidget() is None:
                ensure_topmost(hwnd)
        finally:
            self._aligning = False

    def update_metrics(self, m):
        """接收后台采样的系统指标并刷新 UI。"""
        self.latest_metrics = m
        if not self.isVisible():
            return

        pal = PALETTES[self._active_palette_key]

        if self.cfg.get("show_net", True):
            self.item_upload.set_value(format_bytes_speed(m.upload_speed))
            self.item_download.set_value(format_bytes_speed(m.download_speed))

        if self.cfg.get("show_disk", True):
            self.item_disk_read.set_value(format_bytes_speed(m.disk_read_speed))
            self.item_disk_write.set_value(format_bytes_speed(m.disk_write_speed))

        if self.cfg.get("show_cpu", True):
            cpu_temp_str = f"{int(round(m.cpu_temp))}℃" if m.cpu_temp > 0 else ""
            cpu_color = pal["cpu_hot"] if m.cpu_temp >= 75 else pal["cpu"]
            self.item_cpu.set_value(f"{int(round(m.cpu_usage))}% {cpu_temp_str}".strip(), cpu_color)

        if self.cfg.get("show_gpu", True):
            gpu_temp_str = f"{int(round(m.gpu_temp))}℃" if m.gpu_temp > 0 else ""
            gpu_color = pal["gpu_hot"] if m.gpu_temp >= 75 else pal["gpu"]
            self.item_gpu.set_value(f"{int(round(m.gpu_usage))}% {gpu_temp_str}".strip(), gpu_color)

        if self.cfg.get("show_ram", True):
            self.item_ram.set_value(f"{int(round(m.ram_usage))}%")
            self.item_ram_val.set_value(f"{m.ram_used_gb:.1f}G")

        hint = self.sizeHint()
        if hint.height() > self.height() or hint.width() > self.width():
            self._sync_widget_size()

    def mousePressEvent(self, event):
        # 右键菜单统一由 contextMenuEvent 处理，杜绝重复弹两次菜单
        if event.button() == Qt.LeftButton:
            self._drag_press_global = event.globalPos()
            self.drag_start_pos = event.globalPos() - self.pos()
            self._drag_press_cursor_phys = get_cursor_phys_pos()
            self._drag_start_rect_phys = get_window_phys_rect(int(self.winId()))
            self._drag_use_qt_fallback = False
            self._has_dragged = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.LeftButton) and self._drag_press_global is not None:
            dpi_ratio = self._get_dpi_ratio()
            cur_cursor_phys = get_cursor_phys_pos()
            qt_delta = event.globalPos() - self._drag_press_global
            threshold = max(3, round_phys(3 * dpi_ratio))

            # 优先使用 Win32 物理光标位移；仅在光标不可用或纯合成 QMouseEvent 测试时锁存回退到 Qt 位移
            if self._drag_press_cursor_phys is None or cur_cursor_phys is None:
                use_qt = True
            elif cur_cursor_phys[0] != self._drag_press_cursor_phys[0] or cur_cursor_phys[1] != self._drag_press_cursor_phys[1]:
                self._drag_use_qt_fallback = False
                use_qt = False
            elif self._drag_use_qt_fallback or (not self._has_dragged and qt_delta.manhattanLength() > 0):
                self._drag_use_qt_fallback = True
                use_qt = True
            else:
                use_qt = False

            if not use_qt:
                dx_phys = cur_cursor_phys[0] - self._drag_press_cursor_phys[0]
                dy_phys = cur_cursor_phys[1] - self._drag_press_cursor_phys[1]
                moved_dist = abs(dx_phys) + abs(dy_phys)
            else:
                dx_phys = round_phys(qt_delta.x() * dpi_ratio)
                moved_dist = round_phys(qt_delta.manhattanLength() * dpi_ratio)

            if not self._has_dragged:
                if moved_dist <= threshold:
                    return
                self._has_dragged = True
                self.pos_timer.stop()

            hwnd = int(self.winId())
            if self._drag_start_rect_phys is not None and hwnd:
                start_x, start_y, start_r, start_b = self._drag_start_rect_phys
                phys_w = start_r - start_x
                phys_h = start_b - start_y
                _, min_x, max_x = get_drag_phys_bounds(phys_w, OFFSET_X_MIN, OFFSET_X_MAX, dpi_ratio)
                target_phys_x = max(min_x, min(max_x, start_x + dx_phys))
                # 严格沿用按下瞬间的物理 Y 与物理尺寸，彻底消除跨 DPI 下 self.y() 引起的纵向漂移
                move_window_phys(hwnd, target_phys_x, start_y, phys_w, phys_h)
            elif self.drag_start_pos is not None:
                new_pos = event.globalPos() - self.drag_start_pos
                self.move(new_pos.x(), self.y())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._has_dragged:
                self._has_dragged = False
                dpi_ratio = self._get_dpi_ratio()
                win_rect = get_window_phys_rect(int(self.winId()))
                phys_w = (win_rect[2] - win_rect[0]) if win_rect else round_phys(self.width() * dpi_ratio)
                # 统一在物理像素下反算逻辑偏移量 offset_x，彻底消除高 DPI 拖动漂移
                anchor_phys_x, _, _ = get_drag_phys_bounds(phys_w, OFFSET_X_MIN, OFFSET_X_MAX, dpi_ratio)
                cur_phys_x = win_rect[0] if win_rect else round_phys(self.x() * dpi_ratio)
                new_offset_x = round_phys((cur_phys_x - anchor_phys_x) / dpi_ratio)
                new_offset_x = max(OFFSET_X_MIN, min(OFFSET_X_MAX, new_offset_x))

                self.offset_x = new_offset_x
                self.cfg["offset_x"] = new_offset_x
                save_config(self.cfg)
                self._last_phys_rect = None
                self.config_changed.emit(self.cfg.copy())

            self.drag_start_pos = None
            self._drag_press_global = None
            self._drag_press_cursor_phys = None
            self._drag_start_rect_phys = None
            self._drag_use_qt_fallback = False
            if not self.pos_timer.isActive():
                self.pos_timer.start(350)
            self.align_to_taskbar()

    def mouseDoubleClickEvent(self, event):
        """双击安全打开任务管理器（兼容非管理员权限 UAC）。"""
        if event.button() == Qt.LeftButton:
            open_task_manager()

    def contextMenuEvent(self, event):
        """统一右键上下文菜单入口。"""
        self.show_context_menu(event.globalPos())
        event.accept()

    def show_context_menu(self, pos):
        """右键快捷设置菜单"""
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLESHEET)

        # 1. 显示项目快速勾选子菜单
        menu_items = menu.addMenu("显示项目")
        menu_items.setStyleSheet(MENU_STYLESHEET)

        active_count = sum(1 for k in DISPLAY_KEYS if self.cfg.get(k, True))
        for key, name in [
            ("show_net", "网络流速 (上传/下载)"),
            ("show_disk", "磁盘读写 (读/写)"),
            ("show_cpu", "CPU 监控 (占用/温度)"),
            ("show_gpu", "GPU 监控 (占用/温度)"),
            ("show_ram", "内存监控 (占用/已用)"),
        ]:
            act = QAction(name, menu_items, checkable=True)
            checked = bool(self.cfg.get(key, True))
            act.setChecked(checked)
            # 仅剩最后一项时禁用取消勾选，防止变成空白悬浮条
            if checked and active_count <= 1:
                act.setEnabled(False)
            act.triggered.connect(lambda chk, k=key: self._toggle_display_item(k, chk))
            menu_items.addAction(act)

        # 2. 背景样式快速切换子菜单
        menu_bg = menu.addMenu("背景样式")
        menu_bg.setStyleSheet(MENU_STYLESHEET)

        act_trans = QAction("完全透明 (文字悬浮任务栏)", menu_bg, checkable=True)
        act_trans.setChecked(self.cfg.get("bg_style", "transparent") == "transparent")
        act_trans.triggered.connect(lambda: self._set_bg_style("transparent"))
        menu_bg.addAction(act_trans)

        act_capsule = QAction("磨砂胶囊卡片", menu_bg, checkable=True)
        act_capsule.setChecked(self.cfg.get("bg_style", "transparent") == "capsule")
        act_capsule.triggered.connect(lambda: self._set_bg_style("capsule"))
        menu_bg.addAction(act_capsule)

        menu.addSeparator()

        action_settings = QAction("偏好设置...", menu)
        action_settings.triggered.connect(self.open_settings_dialog)
        menu.addAction(action_settings)

        action_freeze = QAction("截屏时自动隐身避让", menu, checkable=True)
        action_freeze.setChecked(self.cfg.get("freeze_on_screenshot", True))
        action_freeze.triggered.connect(self._toggle_freeze_screenshot)
        menu.addAction(action_freeze)

        action_fullscreen = QAction("主屏全屏时自动隐藏", menu, checkable=True)
        action_fullscreen.setChecked(self.cfg.get("hide_on_fullscreen", True))
        action_fullscreen.triggered.connect(self._toggle_hide_on_fullscreen)
        menu.addAction(action_fullscreen)

        action_autostart = QAction("开机自动启动", menu, checkable=True)
        action_autostart.setChecked(is_autostart_enabled())
        action_autostart.triggered.connect(lambda chk: set_autostart(chk))
        menu.addAction(action_autostart)

        action_taskmgr = QAction("打开任务管理器", menu)
        action_taskmgr.triggered.connect(open_task_manager)
        menu.addAction(action_taskmgr)

        action_realign = QAction("重新对齐到任务栏托盘", menu)
        action_realign.triggered.connect(self.reset_align_to_taskbar)
        menu.addAction(action_realign)

        menu.addSeparator()

        action_quit = QAction("退出程序", menu)
        action_quit.triggered.connect(QApplication.quit)
        menu.addAction(action_quit)

        menu.exec_(pos)

    def reset_align_to_taskbar(self):
        """重置拖动偏移量为默认值并立即吸附归位。"""
        default_offset = DEFAULT_CONFIG["offset_x"]
        self.offset_x = default_offset
        self.cfg["offset_x"] = default_offset
        save_config(self.cfg)
        self._last_phys_rect = None
        self.align_to_taskbar()
        self.config_changed.emit(self.cfg.copy())

    def _toggle_display_item(self, key: str, checked: bool):
        if not checked:
            remaining = [k for k in DISPLAY_KEYS if k != key and self.cfg.get(k, True)]
            if not remaining:
                return
        self.cfg[key] = checked
        save_config(self.cfg)
        self.update_layout_visibility()
        self.config_changed.emit(self.cfg.copy())

    def _toggle_freeze_screenshot(self, checked: bool):
        self.cfg["freeze_on_screenshot"] = checked
        save_config(self.cfg)
        self._apply_capture_protection()
        self.config_changed.emit(self.cfg.copy())

    def _toggle_hide_on_fullscreen(self, checked: bool):
        self.cfg["hide_on_fullscreen"] = checked
        save_config(self.cfg)
        self.align_to_taskbar()
        self.config_changed.emit(self.cfg.copy())

    def _set_bg_style(self, style_name: str):
        self.cfg["bg_style"] = style_name
        save_config(self.cfg)
        self.apply_theme()
        self.config_changed.emit(self.cfg.copy())

    def open_settings_dialog(self):
        """单例弹出偏好设置对话框，防止重复打开多个设置窗口。"""
        if self._settings_dlg is not None and self._settings_dlg.isVisible():
            self._settings_dlg.raise_()
            self._settings_dlg.activateWindow()
            return

        dlg = SettingsDialog(parent=None, current_cfg=self.cfg)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
        dlg.settings_changed.connect(self.on_settings_updated)
        self._settings_dlg = dlg
        try:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            dlg.exec_()
        finally:
            self._settings_dlg = None

    # 兼容旧方法名调用
    _open_settings_dialog = open_settings_dialog

    def on_settings_updated(self, new_cfg: dict):
        """接收设置弹窗的实时更新并同步广播给后台采样线程。"""
        self.cfg = sanitize_config(new_cfg)
        self.offset_x = self.cfg.get("offset_x", DEFAULT_CONFIG["offset_x"])
        self.apply_theme()
        self.update_layout_visibility()
        self.config_changed.emit(self.cfg.copy())
