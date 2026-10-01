# -*- coding: utf-8 -*-
"""
用户偏好配置管理模块
负责将显示项勾选、背景模式、文字阴影及采样频率持久化到本地 config.json
"""

import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# 默认配置项
DEFAULT_CONFIG = {
    "bg_style": "transparent",       # 背景风格: "transparent" (完全透明悬浮) 或 "capsule" (磨砂深黑胶囊)
    "enable_shadow": True,            # 是否开启文字防透微投影（确保透明背景下绝对清晰）
    "show_net": True,                 # 是否显示网络流速
    "show_disk": True,                # 是否显示磁盘读写
    "show_cpu": True,                 # 是否显示 CPU 占用与温度
    "show_gpu": True,                 # 是否显示 GPU 占用与温度
    "show_ram": True,                 # 是否显示内存占用
    "refresh_interval": 1.0,          # 采样刷新频率（秒）
    "offset_x": -4,                   # 水平吸附微调偏移（像素）
    "freeze_on_screenshot": True,     # 截屏时自动定格暂停（支持微信/QQ/Snipaste/Win+Shift+S）
    "hide_on_fullscreen": True        # 全屏游戏/观影播放时自动静默隐藏，退出全屏自动恢复
}


def load_config():
    """从本地读取配置，若不存在则创建并返回默认配置"""
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            # 补齐可能缺失的新字段
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception as e:
        print(f"[配置模块] 读取配置失败，恢复默认配置: {e}")
        return DEFAULT_CONFIG.copy()


def save_config(cfg):
    """保存配置到本地 json 文件"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[配置模块] 保存配置失败: {e}")
        return False
