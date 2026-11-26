# -*- coding: utf-8 -*-
"""
配置持久化管理模块
自动保存与加载用户的个性化显示项、外观主题、刷新频率、虚拟网卡过滤与位置偏移设置。
"""

import json
import os
import sys
import tempfile

from logger import get_logger

log = get_logger("config")

# 水平偏移范围（与拖动和设置界面保持统一）
OFFSET_X_MIN = -800
OFFSET_X_MAX = 300

# 默认配置项
DEFAULT_CONFIG = {
    "bg_style": "transparent",        # 背景风格: "transparent" 或 "capsule"
    "theme_mode": "auto",             # 主题模式: "auto" (跟随系统任务栏) / "dark" (深色任务栏用浅字) / "light" (浅色任务栏用深字)
    "enable_shadow": True,            # 是否开启文字微投影（确保透明背景下清晰可读）
    "show_net": True,                 # 是否显示网络流速
    "show_disk": True,                # 是否显示磁盘读写
    "show_cpu": True,                 # 是否显示 CPU 占用与温度
    "show_gpu": True,                 # 是否显示 GPU 占用与温度
    "show_ram": True,                 # 是否显示内存占用
    "refresh_interval": 1.0,          # 采样刷新频率（秒）
    "offset_x": -4,                   # 水平吸附微调偏移（逻辑像素）
    "freeze_on_screenshot": True,     # 截屏时自动避让隐藏（优先使用 Win10/11 原生防截屏属性）
    "hide_on_fullscreen": True,       # 主屏全屏游戏/观影时自动静默隐藏，退出自动恢复
    "filter_virtual_nics": True,      # 智能过滤虚拟网卡（防止 VPN/代理 TUN/Docker 导致网速翻倍）
    "preferred_gpu": "auto",          # 显卡优先策略: "auto" (优先独立显卡) 或 "first" (首个检测设备)
}

DISPLAY_KEYS = ("show_net", "show_disk", "show_cpu", "show_gpu", "show_ram")


def _is_dir_writable(directory: str) -> bool:
    """无副作用检测目录写入权限（不修改现有 config.json 的时间戳）。"""
    if not os.path.isdir(directory):
        return False
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".tm_perm_", dir=directory)
        os.close(fd)
        os.remove(tmp_path)
        return True
    except OSError:
        return False


def get_config_path() -> str:
    """
    获取配置文件路径：
    1. 打包为单文件 exe 运行时，定位真实 exe 所在目录，而非临时解压目录 _MEIxxxx；
    2. 优先在程序同级目录读写 config.json（绿色便携模式）；
    3. 若处于受限目录（如 Program Files 等无写权限），平滑降级至 %APPDATA%\\TaskbarMonitor。
    """
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    if _is_dir_writable(base_dir):
        return os.path.join(base_dir, "config.json")

    appdata_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "TaskbarMonitor")
    os.makedirs(appdata_dir, exist_ok=True)
    return os.path.join(appdata_dir, "config.json")


CONFIG_FILE = get_config_path()


def sanitize_config(raw_cfg: dict) -> dict:
    """校验并规范化配置项，防止异常数值或全部关闭导致界面失效。"""
    cfg = DEFAULT_CONFIG.copy()
    if isinstance(raw_cfg, dict):
        for k, default_v in DEFAULT_CONFIG.items():
            if k in raw_cfg:
                cfg[k] = raw_cfg[k]

    if cfg.get("bg_style") not in ("transparent", "capsule"):
        cfg["bg_style"] = DEFAULT_CONFIG["bg_style"]

    if cfg.get("theme_mode") not in ("auto", "dark", "light"):
        cfg["theme_mode"] = DEFAULT_CONFIG["theme_mode"]

    if cfg.get("preferred_gpu") not in ("auto", "first"):
        cfg["preferred_gpu"] = DEFAULT_CONFIG["preferred_gpu"]

    for key in (
        "enable_shadow",
        "show_net",
        "show_disk",
        "show_cpu",
        "show_gpu",
        "show_ram",
        "freeze_on_screenshot",
        "hide_on_fullscreen",
        "filter_virtual_nics",
    ):
        cfg[key] = bool(cfg.get(key, DEFAULT_CONFIG[key]))

    # 至少保留一个显示项，避免出现空白悬浮壳
    if not any(cfg[k] for k in DISPLAY_KEYS):
        cfg["show_net"] = True
        cfg["show_cpu"] = True

    try:
        interval = float(cfg.get("refresh_interval", 1.0))
        cfg["refresh_interval"] = max(0.5, min(5.0, interval))
    except (TypeError, ValueError):
        cfg["refresh_interval"] = DEFAULT_CONFIG["refresh_interval"]

    try:
        offset_x = int(cfg.get("offset_x", DEFAULT_CONFIG["offset_x"]))
        cfg["offset_x"] = max(OFFSET_X_MIN, min(OFFSET_X_MAX, offset_x))
    except (TypeError, ValueError):
        cfg["offset_x"] = DEFAULT_CONFIG["offset_x"]

    return cfg


def load_config() -> dict:
    """从本地读取配置，若不存在则创建并返回默认配置。"""
    if not os.path.exists(CONFIG_FILE):
        cfg = DEFAULT_CONFIG.copy()
        save_config(cfg)
        return cfg

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return sanitize_config(raw)
    except Exception as e:
        log.warning("读取配置失败，恢复默认配置: %s", e)
        return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> bool:
    """以原子替换方式保存配置到本地 json 文件，避免异常断电损坏配置。"""
    clean_cfg = sanitize_config(cfg)
    target_dir = os.path.dirname(os.path.abspath(CONFIG_FILE))
    tmp_path = None
    try:
        os.makedirs(target_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".config_", suffix=".tmp", dir=target_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(clean_cfg, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, CONFIG_FILE)
        return True
    except Exception as e:
        log.error("保存配置失败: %s", e)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False
