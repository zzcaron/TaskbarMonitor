# -*- coding: utf-8 -*-
"""
偏好设置对话框界面
优化点：
1. 水平偏移微调范围与拖动范围统一为 [-800, 300]，彻底消除打开设置后位置被强行截断的问题；
2. 新增系统任务栏浅色/深色自动适配选项；
3. 新增虚拟网卡过滤开关与多显卡优先策略，并支持全部选项实时热生效。
"""

from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)
from PyQt5.QtCore import Qt, pyqtSignal

from autostart import is_autostart_enabled, set_autostart
from config import OFFSET_X_MAX, OFFSET_X_MIN, load_config, save_config, sanitize_config


class SettingsDialog(QDialog):
    """可视化详细设置窗口"""

    settings_changed = pyqtSignal(dict)

    def __init__(self, parent=None, current_cfg=None):
        super().__init__(parent)
        self.setWindowTitle("TaskbarMonitor 偏好设置")
        self.setMinimumSize(460, 620)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.cfg = sanitize_config(current_cfg) if current_cfg is not None else load_config()

        self.setStyleSheet("""
            QDialog {
                background-color: #202024;
                color: #ffffff;
                font-family: 'Segoe UI', 'Microsoft YaHei UI';
            }
            QGroupBox {
                border: 1px solid #3a3a40;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 14px;
                color: #00d2d3;
                font-weight: bold;
                font-size: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QCheckBox, QRadioButton, QLabel {
                color: #e2e8f0;
                font-size: 12px;
            }
            QComboBox, QSpinBox {
                background-color: #2d2d34;
                border: 1px solid #4a4a54;
                border-radius: 4px;
                padding: 4px 8px;
                color: #ffffff;
            }
            QPushButton {
                background-color: #0984e3;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #74b9ff;
            }
            QPushButton#BtnCancel {
                background-color: #4a4a54;
            }
            QPushButton#BtnCancel:hover {
                background-color: #636e72;
            }
        """)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        # 1. 监控显示项勾选
        grp_items = QGroupBox("监控项目显示开关", self)
        layout_items = QVBoxLayout(grp_items)

        self.chk_net = QCheckBox("网络流速 (实时上传 / 下载速率)", self)
        self.chk_net.setChecked(self.cfg.get("show_net", True))

        self.chk_disk = QCheckBox("磁盘读写 (实时读取 / 写入速率)", self)
        self.chk_disk.setChecked(self.cfg.get("show_disk", True))

        self.chk_cpu = QCheckBox("CPU 监控 (占用率与核心温度)", self)
        self.chk_cpu.setChecked(self.cfg.get("show_cpu", True))

        self.chk_gpu = QCheckBox("GPU 监控 (显卡占用率与核心温度)", self)
        self.chk_gpu.setChecked(self.cfg.get("show_gpu", True))

        self.chk_ram = QCheckBox("内存监控 (占用率与实际已用容量)", self)
        self.chk_ram.setChecked(self.cfg.get("show_ram", True))

        for chk in (self.chk_net, self.chk_disk, self.chk_cpu, self.chk_gpu, self.chk_ram):
            layout_items.addWidget(chk)
        main_layout.addWidget(grp_items)

        # 2. 背景与视觉风格
        grp_visual = QGroupBox("视觉外观与主题适配", self)
        layout_visual = QVBoxLayout(grp_visual)

        self.btn_group_bg = QButtonGroup(self)
        self.rad_transparent = QRadioButton("完全透明悬浮 (文字直接悬浮在任务栏底色上)", self)
        self.rad_capsule = QRadioButton("磨砂胶囊卡片 (高对比度微磨砂轮廓与细边框)", self)
        self.btn_group_bg.addButton(self.rad_transparent)
        self.btn_group_bg.addButton(self.rad_capsule)

        if self.cfg.get("bg_style", "transparent") == "capsule":
            self.rad_capsule.setChecked(True)
        else:
            self.rad_transparent.setChecked(True)

        h_theme = QHBoxLayout()
        h_theme.addWidget(QLabel("任务栏深浅配色:", self))
        self.cmb_theme = QComboBox(self)
        self.cmb_theme.addItem("跟随系统任务栏主题 (自动)", "auto")
        self.cmb_theme.addItem("深色任务栏模式 (亮色文字)", "dark")
        self.cmb_theme.addItem("浅色任务栏模式 (深色文字)", "light")
        cur_theme = self.cfg.get("theme_mode", "auto")
        theme_idx = self.cmb_theme.findData(cur_theme)
        self.cmb_theme.setCurrentIndex(theme_idx if theme_idx >= 0 else 0)
        h_theme.addWidget(self.cmb_theme)

        self.chk_shadow = QCheckBox("启用文字微投影 (透明模式下防壁纸反光，提升清晰度)", self)
        self.chk_shadow.setChecked(self.cfg.get("enable_shadow", True))

        layout_visual.addWidget(self.rad_transparent)
        layout_visual.addWidget(self.rad_capsule)
        layout_visual.addLayout(h_theme)
        layout_visual.addWidget(self.chk_shadow)
        main_layout.addWidget(grp_visual)

        # 3. 硬件采集与系统集成
        grp_perf = QGroupBox("采集策略与系统集成", self)
        layout_perf = QVBoxLayout(grp_perf)

        # 刷新频率（修改后即时热生效）
        h_freq = QHBoxLayout()
        h_freq.addWidget(QLabel("数据采样刷新频率:", self))
        self.cmb_freq = QComboBox(self)
        self.cmb_freq.addItem("0.5 秒 (流畅灵敏)", 0.5)
        self.cmb_freq.addItem("1.0 秒 (推荐平衡)", 1.0)
        self.cmb_freq.addItem("2.0 秒 (节能低耗)", 2.0)
        self.cmb_freq.addItem("3.0 秒 (超长续航)", 3.0)
        cur_interval = float(self.cfg.get("refresh_interval", 1.0))
        freq_idx = self.cmb_freq.findData(cur_interval)
        self.cmb_freq.setCurrentIndex(freq_idx if freq_idx >= 0 else 1)
        h_freq.addWidget(self.cmb_freq)
        layout_perf.addLayout(h_freq)

        # 显卡选择策略
        h_gpu = QHBoxLayout()
        h_gpu.addWidget(QLabel("多显卡优先策略:", self))
        self.cmb_gpu = QComboBox(self)
        self.cmb_gpu.addItem("自动优先独立显卡 (推荐双显笔记本)", "auto")
        self.cmb_gpu.addItem("默认系统首个检测到的显卡", "first")
        gpu_idx = self.cmb_gpu.findData(self.cfg.get("preferred_gpu", "auto"))
        self.cmb_gpu.setCurrentIndex(gpu_idx if gpu_idx >= 0 else 0)
        h_gpu.addWidget(self.cmb_gpu)
        layout_perf.addLayout(h_gpu)

        # 水平偏移微调（与鼠标拖动范围一致）
        h_offset = QHBoxLayout()
        h_offset.addWidget(QLabel("任务栏水平对齐偏移微调:", self))
        self.spn_offset = QSpinBox(self)
        self.spn_offset.setRange(OFFSET_X_MIN, OFFSET_X_MAX)
        self.spn_offset.setSuffix(" px")
        self.spn_offset.setValue(int(self.cfg.get("offset_x", -4)))
        h_offset.addWidget(self.spn_offset)
        layout_perf.addLayout(h_offset)

        self.chk_filter_nic = QCheckBox("过滤虚拟/代理 TUN 网卡 (防止 VPN 或 Docker 导致网速翻倍)", self)
        self.chk_filter_nic.setChecked(self.cfg.get("filter_virtual_nics", True))
        layout_perf.addWidget(self.chk_filter_nic)

        self.chk_freeze = QCheckBox("截屏时自动隐身避让 (Win10/11 原生防截屏，零延迟不入图)", self)
        self.chk_freeze.setChecked(self.cfg.get("freeze_on_screenshot", True))
        layout_perf.addWidget(self.chk_freeze)

        self.chk_fullscreen = QCheckBox("主屏全屏游戏或观影时自动隐藏 (副屏全屏不影响主屏)", self)
        self.chk_fullscreen.setChecked(self.cfg.get("hide_on_fullscreen", True))
        layout_perf.addWidget(self.chk_fullscreen)

        self.chk_autostart = QCheckBox("跟随 Windows 开机自动启动", self)
        self.chk_autostart.setChecked(is_autostart_enabled())
        layout_perf.addWidget(self.chk_autostart)

        main_layout.addWidget(grp_perf)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_apply = QPushButton("应用", self)
        btn_apply.clicked.connect(self._apply_settings)

        btn_ok = QPushButton("确定", self)
        btn_ok.clicked.connect(self._save_and_close)

        btn_cancel = QPushButton("取消", self)
        btn_cancel.setObjectName("BtnCancel")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(btn_apply)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        main_layout.addLayout(btn_layout)

    def _collect_current_config(self) -> dict:
        """收集界面上的最新配置数据。"""
        if not any(
            [
                self.chk_net.isChecked(),
                self.chk_disk.isChecked(),
                self.chk_cpu.isChecked(),
                self.chk_gpu.isChecked(),
                self.chk_ram.isChecked(),
            ]
        ):
            self.chk_net.setChecked(True)
            self.chk_cpu.setChecked(True)

        return sanitize_config(
            {
                "bg_style": "capsule" if self.rad_capsule.isChecked() else "transparent",
                "theme_mode": self.cmb_theme.currentData(),
                "enable_shadow": self.chk_shadow.isChecked(),
                "show_net": self.chk_net.isChecked(),
                "show_disk": self.chk_disk.isChecked(),
                "show_cpu": self.chk_cpu.isChecked(),
                "show_gpu": self.chk_gpu.isChecked(),
                "show_ram": self.chk_ram.isChecked(),
                "refresh_interval": self.cmb_freq.currentData(),
                "offset_x": self.spn_offset.value(),
                "freeze_on_screenshot": self.chk_freeze.isChecked(),
                "hide_on_fullscreen": self.chk_fullscreen.isChecked(),
                "filter_virtual_nics": self.chk_filter_nic.isChecked(),
                "preferred_gpu": self.cmb_gpu.currentData(),
            }
        )

    def _apply_settings(self):
        new_cfg = self._collect_current_config()
        save_config(new_cfg)
        set_autostart(self.chk_autostart.isChecked())
        self.cfg = new_cfg
        self.settings_changed.emit(new_cfg)

    def _save_and_close(self):
        self._apply_settings()
        self.accept()
