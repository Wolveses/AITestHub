# -*- coding: utf-8 -*-
"""AI 自动化脚本数据库单例（与 Midscene 共库 ui.db）。"""

from __future__ import annotations

import os
import threading

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
    return _db
