# -*- coding: utf-8 -*-
"""自动化脚本的文件布局（DB 只存相对路径，根目录可配，保证跨服务器迁移）。

布局（相对 ``ui_workspace_dir``，默认 ~/.insight_eye）::

    ui_scripts/<project_id>/<case_id>/case.py
    ui_scripts/<project_id>/<case_id>/history/case_v<n>.py
    ui_scripts/<project_id>/conftest.py
    ui_artifacts/<project_id>/<case_id>/<run_key>/{junit.xml,result.json,*.png,trace.zip}
    ui_generations/<case_id>/<gen_id>.jsonl
    ui_auth/<project_id>/<env_id>/storage.json
    ui_envs.json  （环境密码，独立文件，接口永不返回明文）
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def workspace_root() -> Path:
    """脚本/产物的存储根目录（默认 ~/.insight_eye）。"""
    raw = ""
    try:
        from insight_aitest.platform.services.kb.deps import get_llm_config

        raw = getattr(get_llm_config(), "ui_workspace_dir", "") or ""
    except Exception:
        raw = ""
    return Path(os.path.expanduser(raw or "~/.insight_eye"))


def resolve_rel(rel: str) -> Path:
    """相对路径 → 绝对路径（空串返回根目录）。"""
    root = workspace_root()
    return root / rel if rel else root


def to_rel(path: Path) -> str:
    """绝对路径 → 相对根目录的 posix 路径。"""
    try:
        return path.resolve().relative_to(workspace_root().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def project_scripts_dir(project_id: int) -> Path:
    return workspace_root() / "ui_scripts" / str(project_id)


def case_dir(project_id: int, case_id: int) -> Path:
    return project_scripts_dir(project_id) / str(case_id)


def case_script(project_id: int, case_id: int) -> Path:
    return case_dir(project_id, case_id) / "case.py"


def case_history_path(project_id: int, case_id: int, version: int) -> Path:
    return case_dir(project_id, case_id) / "history" / f"case_v{version}.py"


def new_run_dir(project_id: int, case_id: int) -> Path:
    key = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    d = workspace_root() / "ui_artifacts" / str(project_id) / str(case_id) / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def generation_log(ui_case_id: int, gen_id: int) -> Path:
    d = workspace_root() / "ui_generations" / str(ui_case_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{gen_id}.jsonl"


def storage_state_path(project_id: int, env_id: int) -> Path:
    d = workspace_root() / "ui_auth" / str(project_id) / str(env_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / "storage.json"


def env_secrets_path() -> Path:
    return workspace_root() / "ui_envs.json"
