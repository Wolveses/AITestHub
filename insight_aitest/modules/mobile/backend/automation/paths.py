# -*- coding: utf-8 -*-
"""手机 App 自动化文件布局（DB 只存相对路径，默认根目录 ~/.insight_eye/mobile）。

目录结构：
    apps/<project_id>/<filename>.apk
    scripts/<project_id>/<case_id>/case.py
    scripts/<project_id>/<case_id>/history/case_v<n>.py
    scripts/<project_id>/pages/*.py
    scripts/<project_id>/common/*.py
    staging/<project_id>/<case_id>/{case.py, pages/*.py}
    artifacts/<project_id>/<case_id>/<run_key>/{junit.xml,result.json,*.png,device.log,stdout.log}
    generations/<case_id>/<gen_id>.jsonl
    generations/<case_id>/steps/<gen_id>_<seq>.png
    envs.json
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

_OVERRIDE_ROOT: Path | None = None


def set_workspace_root(path: Path | str | None) -> None:
    """允许测试覆写工作区根目录。"""
    global _OVERRIDE_ROOT
    _OVERRIDE_ROOT = Path(path) if path else None


def workspace_root() -> Path:
    if _OVERRIDE_ROOT is not None:
        return _OVERRIDE_ROOT
    raw = os.environ.get("INSIGHT_MOBILE_WORKSPACE", "").strip()
    return Path(os.path.expanduser(raw or "~/.insight_eye/mobile"))


def resolve_rel(rel: str) -> Path:
    root = workspace_root()
    return root / rel if rel else root


def to_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def apps_dir(project_id: int) -> Path:
    d = workspace_root() / "apps" / str(project_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_scripts_dir(project_id: int) -> Path:
    d = workspace_root() / "scripts" / str(project_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_pkg(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    init = d / "__init__.py"
    if not init.exists():
        init.write_text("# -*- coding: utf-8 -*-\n", encoding="utf-8")
    return d


def pages_dir(project_id: int) -> Path:
    return _ensure_pkg(project_scripts_dir(project_id) / "pages")


def common_dir(project_id: int) -> Path:
    return _ensure_pkg(project_scripts_dir(project_id) / "common")


def case_dir(project_id: int, case_id: int) -> Path:
    d = project_scripts_dir(project_id) / str(case_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def case_script_path(project_id: int, case_id: int) -> Path:
    return case_dir(project_id, case_id) / "case.py"


def case_history_dir(project_id: int, case_id: int) -> Path:
    d = case_dir(project_id, case_id) / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def staging_dir(project_id: int, case_id: int) -> Path:
    d = workspace_root() / "staging" / str(project_id) / str(case_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def artifacts_dir(project_id: int, case_id: int, run_key: str = "") -> Path:
    key = run_key or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    d = workspace_root() / "artifacts" / str(project_id) / str(case_id) / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def generation_log_path(case_id: int, gen_id: int) -> Path:
    d = workspace_root() / "generations" / str(case_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{gen_id}.jsonl"


def generation_steps_dir(case_id: int, gen_id: int) -> Path:
    d = workspace_root() / "generations" / str(case_id) / "steps" / str(gen_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def env_secrets_path() -> Path:
    root = workspace_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "envs.json"
