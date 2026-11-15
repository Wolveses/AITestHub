# -*- coding: utf-8 -*-
"""mobile 模块依赖注入单例。"""

from __future__ import annotations

import os
import threading

from insight_aitest.modules.mobile.backend.persistence.database import MobileDatabase

_DB_PATH = os.path.expanduser("~/.insight_eye/mobile.db")

_db: MobileDatabase | None = None
_db_lock = threading.Lock()


def get_mobile_db() -> MobileDatabase:
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                _db = MobileDatabase(_DB_PATH)
    return _db
