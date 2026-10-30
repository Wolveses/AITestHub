# -*- coding: utf-8 -*-
"""自动化脚本的文件布局（DB 只存相对路径，根目录可配，保证跨服务器迁移）。

布局（相对 ``ui_workspace_dir``，默认 ``~/.insight_eye/ui``）::

    scripts/<project_id>/<case_id>/case.py
    scripts/<project_id>/<case_id>/history/case_v<n>.py
    scripts/<project_id>/pages/*.py  （项目级页面对象，跨用例复用）
    artifacts/<project_id>/<case_id>/<run_key>/{junit.xml,result.json,*.png,trace.zip}
    generations/<case_id>/<gen_id>.jsonl
    auth/<project_id>/<env_id>/storage.json
    envs.json  （环境密码，独立文件，接口永不返回明文）
    mcp/       （playwright MCP 探索时的临时输出）
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def workspace_root() -> Path:
    """脚本/产物的存储根目录（默认 ~/.insight_eye/ui）。"""
    raw = ""
    try:
        from insight_aitest.platform.services.kb.deps import get_llm_config

        raw = getattr(get_llm_config(), "ui_workspace_dir", "") or ""
    except Exception:
        raw = ""
    return Path(os.path.expanduser(raw or "~/.insight_eye/ui"))


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
    return workspace_root() / "scripts" / str(project_id)


def case_dir(project_id: int, case_id: int) -> Path:
    return project_scripts_dir(project_id) / str(case_id)


def pages_dir(project_id: int) -> Path:
    """项目级页面对象目录（跨用例复用的业务公共代码）。"""
    d = project_scripts_dir(project_id) / "pages"
    d.mkdir(parents=True, exist_ok=True)
    init = d / "__init__.py"
    if not init.exists():
        init.write_text("# -*- coding: utf-8 -*-\n", encoding="utf-8")
    return d


def common_dir(project_id: int) -> Path:
    """项目级通用代码目录（被 ≥2 处复用的非业务逻辑，可覆盖并备份）。"""
    d = project_scripts_dir(project_id) / "common"
    d.mkdir(parents=True, exist_ok=True)
    init = d / "__init__.py"
    if not init.exists():
        init.write_text("# -*- coding: utf-8 -*-\n", encoding="utf-8")
    return d


def data_dir(project_id: int) -> Path:
    """项目级测试数据目录（上传样例、外部数据），脚本只读。"""
    d = project_scripts_dir(project_id) / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def staging_root(project_id: int, case_id: int) -> Path:
    """生成期暂存目录：页面对象先落这里，首跑通过后再原子并入正式 pages/。"""
    d = workspace_root() / "staging" / str(project_id) / str(case_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def case_script(project_id: int, case_id: int) -> Path:
    return case_dir(project_id, case_id) / "case.py"


def case_history_path(project_id: int, case_id: int, version: int) -> Path:
    return case_dir(project_id, case_id) / "history" / f"case_v{version}.py"


def new_run_dir(project_id: int, case_id: int) -> Path:
    key = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    d = workspace_root() / "artifacts" / str(project_id) / str(case_id) / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def generation_log(ui_case_id: int, gen_id: int) -> Path:
    d = workspace_root() / "generations" / str(ui_case_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{gen_id}.jsonl"


def storage_state_path(project_id: int, env_id: int) -> Path:
    d = workspace_root() / "auth" / str(project_id) / str(env_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / "storage.json"


def env_secrets_path() -> Path:
    return workspace_root() / "envs.json"


def mcp_dir() -> Path:
    d = workspace_root() / "mcp"
    d.mkdir(parents=True, exist_ok=True)
    return d
