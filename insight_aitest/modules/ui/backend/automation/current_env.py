# -*- coding: utf-8 -*-
"""「当前应用环境」解析：项目 current_env_id → 默认环境兜底。"""

from __future__ import annotations

import os

from logzero import logger

_project_db = None


def _pdb():
    global _project_db
    if _project_db is None:
        from insight_aitest.platform.persistence.project_db import ProjectDatabase

        _project_db = ProjectDatabase(os.path.expanduser("~/.insight_eye/projects.db"))
    return _project_db


def resolve_current_env(db, project_id: int):
    """返回项目当前环境；current_env_id 失效时回退到默认环境。"""
    try:
        project = _pdb().get_project(int(project_id))
    except Exception as exc:
        logger.warning("读取项目当前环境失败（回退默认环境）：%s", exc)
        project = None
    env_id = getattr(project, "current_env_id", None)
    if env_id:
        env = db.get_env(int(env_id))
        if env is not None and int(env.project_id) == int(project_id):
            return env
    return db.default_env(int(project_id))


def set_current_env(project_id: int, env_id: int | None) -> None:
    try:
        _pdb().set_current_env(int(project_id), env_id)
    except Exception as exc:
        logger.warning("写入项目当前环境失败：%s", exc)


def current_env_id(project_id: int) -> int | None:
    try:
        project = _pdb().get_project(int(project_id))
        return getattr(project, "current_env_id", None)
    except Exception:
        return None


def project_name(project_id: int) -> str:
    try:
        project = _pdb().get_project(int(project_id))
        return (project.name if project is not None else "") or f"项目 {project_id}"
    except Exception:
        return f"项目 {project_id}"
