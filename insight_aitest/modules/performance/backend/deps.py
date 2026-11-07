# -*- coding: utf-8 -*-
"""performance 模块依赖注入。"""

from __future__ import annotations

import os
import threading

from insight_aitest.modules.performance.backend.persistence.database import PerfDatabase

_DB_PATH = os.path.expanduser("~/.insight_eye/performance.db")

_perf_db: PerfDatabase | None = None
_perf_db_lock = threading.Lock()


def get_perf_db() -> PerfDatabase:
    """获取服务端性能测试持久化数据库单例。"""
    global _perf_db
    if _perf_db is None:
        with _perf_db_lock:
            if _perf_db is None:
                _perf_db = PerfDatabase(_DB_PATH)
    return _perf_db
