# -*- coding: utf-8 -*-
"""
偏好设置对话框界面
提供可视化界面管理监控指标开关、背景样式切换、文字阴影及采样频率
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QCheckBox,
    QRadioButton, QButtonGroup, QComboBox, QSpinBox, QLabel,
    QPushButton, QDialogButtonBox, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from config import load_config, save_config
from autostart import is_autostart_enabled, set_autostart


class SettingsDialog(QDialog):
    """可视化详细设置窗口"""
    settings_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TaskbarMonitor 偏好设置")
        self.setFixedSize(420, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # 加载当前配置
        self.cfg = load_config()

        # 对话框暗黑现代风格
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
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. 监控显示项勾选
        grp_items = QGroupBox("📊 监控项目显示开关", self)
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

        layout_items.addWidget(self.chk_net)
        layout_items.addWidget(self.chk_disk)
        layout_items.addWidget(self.chk_cpu)
        layout_items.addWidget(self.chk_gpu)
        layout_items.addWidget(self.chk_ram)
        main_layout.addWidget(grp_items)

        # 2. 背景与视觉风格
        grp_visual = QGroupBox("🎨 视觉外观与清晰度", self)
        layout_visual = QVBoxLayout(grp_visual)

        self.btn_group_bg = QButtonGroup(self)
        self.rad_transparent = QRadioButton("完全透明悬浮 (文字直接浮在任务栏底色上，像原生一样)", self)
        self.rad_capsule = QRadioButton("磨砂深黑胶囊 (精致微磨砂卡片轮廓与细发光边框)", self)
        self.btn_group_bg.addButton(self.rad_transparent)
        self.btn_group_bg.addButton(self.rad_capsule)

        if self.cfg.get("bg_style", "transparent") == "capsule":
            self.rad_capsule.setChecked(True)
        else:
            self.rad_transparent.setChecked(True)

        self.chk_shadow = QCheckBox("启用文字深色微投影 (强力防背景反光，确保任何壁纸下均清晰)", self)
        self.chk_shadow.setChecked(self.cfg.get("enable_shadow", True))

        layout_visual.addWidget(self.rad_transparent)
        layout_visual.addWidget(self.rad_capsule)
        layout_visual.addWidget(self.chk_shadow)
        main_layout.addWidget(grp_visual)

        # 3. 性能刷新与位置
        grp_perf = QGroupBox("⚙️ 刷新与系统集成", self)
        layout_perf = QVBoxLayout(grp_perf)

        # 刷新频率
        h_freq = QHBoxLayout()
        h_freq.addWidget(QLabel("数据采样刷新频率:", self))
        self.cmb_freq = QComboBox(self)
        self.cmb_freq.addItem("0.5 秒 (极致流畅灵敏)", 0.5)
        self.cmb_freq.addItem("1.0 秒 (推荐 平衡省电)", 1.0)
        self.cmb_freq.addItem("2.0 秒 (节能模式)", 2.0)
        cur_interval = self.cfg.get("refresh_interval", 1.0)
        if cur_interval == 0.5:
            self.cmb_freq.setCurrentIndex(0)
        elif cur_interval == 2.0:
            self.cmb_freq.setCurrentIndex(2)
        else:
            self.cmb_freq.setCurrentIndex(1)
        h_freq.addWidget(self.cmb_freq)
        layout_perf.addLayout(h_freq)

        # 水平偏移微调
        h_offset = QHBoxLayout()
        h_offset.addWidget(QLabel("任务栏水平对齐偏移微调:", self))
        self.spn_offset = QSpinBox(self)
        self.spn_offset.setRange(-200, 200)
        self.spn_offset.setSuffix(" px")
        self.spn_offset.setValue(self.cfg.get("offset_x", -4))
        h_offset.addWidget(self.spn_offset)
        layout_perf.addLayout(h_offset)

        # 开机自启
        self.chk_autostart = QCheckBox("跟随 Windows 开机自动启动", self)
        self.chk_autostart.setChecked(is_autostart_enabled())
        layout_perf.addWidget(self.chk_autostart)

        main_layout.addWidget(grp_perf)

        # 底部操作按钮
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

    def _collect_current_config(self):
        """收集界面上的最新配置数据"""
        # 至少保留一个监控项
        if not any([
            self.chk_net.isChecked(),
            self.chk_disk.isChecked(),
            self.chk_cpu.isChecked(),
            self.chk_gpu.isChecked(),
            self.chk_ram.isChecked()
        ]):
            self.chk_net.setChecked(True)
            self.chk_cpu.setChecked(True)

        new_cfg = {
            "bg_style": "capsule" if self.rad_capsule.isChecked() else "transparent",
            "enable_shadow": self.chk_shadow.isChecked(),
            "show_net": self.chk_net.isChecked(),
            "show_disk": self.chk_disk.isChecked(),
            "show_cpu": self.chk_cpu.isChecked(),
            "show_gpu": self.chk_gpu.isChecked(),
            "show_ram": self.chk_ram.isChecked(),
            "refresh_interval": self.cmb_freq.currentData(),
            "offset_x": self.spn_offset.value()
        }
        return new_cfg

    def _apply_settings(self):
        """应用设置并实时触发通知"""
        new_cfg = self._collect_current_config()
        save_config(new_cfg)
        set_autostart(self.chk_autostart.isChecked())
        self.settings_changed.emit(new_cfg)

    def _save_and_close(self):
        """保存并关闭窗口"""
        self._apply_settings()
        self.accept()
