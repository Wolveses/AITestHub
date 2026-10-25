# -*- coding: utf-8 -*-
"""testcase 模块依赖注入。"""

from __future__ import annotations

import os
import threading

from insight_aitest.modules.testcase.backend.persistence.database import TestCaseDatabase

_tc_db: TestCaseDatabase | None = None
_tc_db_lock = threading.Lock()


def get_tc_db() -> TestCaseDatabase:
    global _tc_db
    if _tc_db is None:
        with _tc_db_lock:
            if _tc_db is None:
                _tc_db = TestCaseDatabase(os.path.expanduser("~/.insight_eye/testcase.db"))
    return _tc_db


def get_analyzer():
    """分析器（Phase A）：组合平台 retriever + llm。"""
    from insight_aitest.platform.services.kb.deps import get_retriever, get_llm, get_llm_config
    from insight_aitest.modules.testcase.backend.generator.analyzer import Analyzer

    return Analyzer(get_retriever(), get_llm(), get_llm_config())


def get_generator():
    """生成器（Phase B）：组合平台 retriever + llm。"""
    from insight_aitest.platform.services.kb.deps import get_retriever, get_llm, get_llm_config
    from insight_aitest.modules.testcase.backend.generator.generator import Generator

    return Generator(get_retriever(), get_llm(), get_llm_config())
