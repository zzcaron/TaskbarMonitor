# -*- coding: utf-8 -*-
"""
统一日志管理模块
解决 --noconsole 打包模式下 print 报错静默丢失的问题，支持按大小自动轮转。
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_INITIALIZED = False
_LOG_FILE_PATH = ""


def _resolve_log_dir() -> str:
    """将日志统一保存在用户 AppData 目录，避免受限于程序目录写权限。"""
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    log_dir = os.path.join(appdata, "TaskbarMonitor", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        return log_dir
    except OSError:
        fallback = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
        return fallback


def setup_logging(level: int = logging.INFO) -> str:
    """初始化全局根日志器，返回日志文件路径。"""
    global _INITIALIZED, _LOG_FILE_PATH
    if _INITIALIZED:
        return _LOG_FILE_PATH

    log_dir = _resolve_log_dir()
    _LOG_FILE_PATH = os.path.join(log_dir, "taskbar_monitor.log")

    root_logger = logging.getLogger("TaskbarMonitor")
    root_logger.setLevel(level)
    root_logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        file_handler = RotatingFileHandler(
            _LOG_FILE_PATH,
            maxBytes=1024 * 1024,  # 单文件最大 1MB
            backupCount=2,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except OSError:
        pass

    # 仅在存在可用控制台流时挂载 StreamHandler（避免 pythonw / --noconsole 异常）
    if sys.stderr is not None and not getattr(sys, "frozen", False):
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    _INITIALIZED = True
    return _LOG_FILE_PATH


def get_logger(name: str) -> logging.Logger:
    """获取模块子日志器。"""
    if not _INITIALIZED:
        setup_logging()
    return logging.getLogger(f"TaskbarMonitor.{name}")


def get_log_file_path() -> str:
    """获取当前日志文件路径。"""
    if not _INITIALIZED:
        setup_logging()
    return _LOG_FILE_PATH
