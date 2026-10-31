# -*- coding: utf-8 -*-
"""进程内并发闸门：同项目同时只允许 1 个生成/执行任务（浏览器串行）。"""

from __future__ import annotations

import threading

_guard = threading.Lock()
_busy_projects: set[int] = set()
# 用例级别进度：case_id -> {"phase", "message", "updated_at"}
_progress: dict[int, dict] = {}
# 用例级别终止标记：case_id -> Event（生成/修复线程在关键节点检查）
_cancel_flags: dict[int, threading.Event] = {}


def acquire(project_id: int) -> bool:
    with _guard:
        if project_id in _busy_projects:
            return False
        _busy_projects.add(project_id)
        return True


def release(project_id: int) -> None:
    with _guard:
        _busy_projects.discard(project_id)


def is_busy(project_id: int) -> bool:
    with _guard:
        return project_id in _busy_projects


def set_progress(case_id: int, phase: str, message: str = "") -> None:
    from datetime import datetime

    with _guard:
        _progress[case_id] = {
            "phase": phase,
            "message": message,
            "updated_at": datetime.now().isoformat(),
        }


def get_progress(case_id: int) -> dict | None:
    with _guard:
        p = _progress.get(case_id)
        return dict(p) if p else None


def request_cancel(case_id: int) -> None:
    """标记用例的生成/修复任务需要终止（由任务线程在关键节点检查）。"""
    with _guard:
        ev = _cancel_flags.get(case_id)
        if ev is None:
            ev = threading.Event()
            _cancel_flags[case_id] = ev
        ev.set()


def is_cancelled(case_id: int) -> bool:
    with _guard:
        ev = _cancel_flags.get(case_id)
        return bool(ev and ev.is_set())


def clear_cancel(case_id: int) -> None:
    with _guard:
        _cancel_flags.pop(case_id, None)
