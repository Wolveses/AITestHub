# -*- coding: utf-8 -*-
"""AI 自动化脚本数据库单例（与 Midscene 共库 ui.db）。"""

from __future__ import annotations

import os
import threading

from logzero import logger

from insight_aitest.modules.ui.backend.automation.database import UIAutomationDatabase

_DB_PATH = os.path.expanduser("~/.insight_eye/ui.db")

_db: UIAutomationDatabase | None = None
_db_lock = threading.Lock()


def get_automation_db() -> UIAutomationDatabase:
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                _db = UIAutomationDatabase(_DB_PATH)
                try:
                    # 后端重启后内存任务已丢失，先收敛残留的生成/执行中状态
                    _db.recover_interrupted_jobs()
                except Exception as exc:  # 恢复失败不影响服务启动
                    logger.warning("UI 自动化残留任务状态恢复失败：%s", exc)
    return _db
