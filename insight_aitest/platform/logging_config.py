# -*- coding: utf-8 -*-
"""平台日志系统配置模块。

统一管理 logzero 业务日志与 Uvicorn 请求日志的文件持久化和轮转。
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import logzero
from uvicorn.config import LOGGING_CONFIG

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_LOG_DIR = _PROJECT_ROOT / "logs"
_LOG_FILE_NAME = "app.log"

_is_configured = False


def get_log_dir() -> Path:
    """获取日志存储目录（支持环境变量 INSIGHT_LOG_DIR 覆盖）"""
    env_dir = os.getenv("INSIGHT_LOG_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    return _DEFAULT_LOG_DIR


def setup_logging(
    log_dir: Path | str | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> dict[str, Any]:
    """配置日志持久化输出到文件，并返回供 Uvicorn 使用的 log_config。

    - 业务日志 (logzero.logger) 自动写入 logs/app.log
    - 服务请求日志 (uvicorn / uvicorn.access) 同步写入同一日志文件
    """
    global _is_configured

    target_dir = Path(log_dir).resolve() if log_dir else get_log_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    log_file = target_dir / _LOG_FILE_NAME

    if not _is_configured:
        # 1. 配置标准库 root logger（捕获 logging.getLogger(__name__) 的所有业务日志）
        import logging
        from logging.handlers import RotatingFileHandler

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s]: %(message)s")
        )
        root_logger.addHandler(file_handler)

        # 2. 配置 logzero 文件输出与轮转（关闭 propagate 避免被 root logger 重复记录）
        logzero.logfile(
            str(log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        logzero.logger.propagate = False
        _is_configured = True

    # 构造兼容 Uvicorn 的 logging dictConfig
    log_config = copy.deepcopy(LOGGING_CONFIG)
    log_config["formatters"]["file_default"] = {
        "()": "uvicorn.logging.DefaultFormatter",
        "fmt": "%(asctime)s %(levelprefix)s %(message)s",
        "use_colors": False,
    }
    log_config["formatters"]["file_access"] = {
        "()": "uvicorn.logging.AccessFormatter",
        "fmt": '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
        "use_colors": False,
    }

    log_config["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(log_file),
        "maxBytes": max_bytes,
        "backupCount": backup_count,
        "encoding": "utf-8",
        "formatter": "file_default",
    }
    log_config["handlers"]["access_file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(log_file),
        "maxBytes": max_bytes,
        "backupCount": backup_count,
        "encoding": "utf-8",
        "formatter": "file_access",
    }

    log_config["loggers"]["uvicorn"]["handlers"].append("file")
    log_config["loggers"]["uvicorn.access"]["handlers"].append("access_file")

    return log_config
