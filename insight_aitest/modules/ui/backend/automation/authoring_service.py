# -*- coding: utf-8 -*-
"""本地 Agent 编写脚本的服务层：校验状态机 / 租约 / 登录态 / 试跑 / 入库。

MCP 工具与 REST 接口共用本模块，保证两条入口行为完全一致。

状态机（按用例）：
``(空) → VALIDATED(hash) → DRY_RUN_OK(hash) → 入库``
- VALIDATED 30 分钟内有效，DRY_RUN_OK 24 小时内有效；
- 任一阶段拿到新 hash 都会重置状态；
- 同一用例同时只允许一个 Agent 操作（15 分钟租约，防并行提交）。
"""

from __future__ import annotations

import secrets
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from logzero import logger

from insight_aitest.modules.ui.backend.automation import contract, lessons, paths
from insight_aitest.modules.ui.backend.automation.current_env import resolve_current_env
from insight_aitest.modules.ui.backend.automation.env_service import prepare_auth, site_url
from insight_aitest.modules.ui.backend.automation.models import (
    AuthoringStage,
    CaseSource,
    CaseStatus,
)

LEASE_MINUTES = 15
VALIDATED_TTL = timedelta(minutes=30)
DRY_RUN_TTL = timedelta(hours=24)
DRY_RUN_COOLDOWN_SEC = 60
DRY_RUN_TIMEOUT_SEC = 240

_LEASE_LOCK = threading.Lock()
_dry_run_last: dict[int, float] = {}
_dry_run_guard = threading.Lock()

_SS_LOCK = threading.Lock()
# storage_state 一次性下载票据：token -> (path, expires_at, used)
_SS: dict[str, tuple[str, datetime, bool]] = {}


def fail(code: str, message: str, **extra) -> dict:
    data = {
        "ok": False,
        "code": code,
        "message": message,
        "fix": contract.ERROR_FIX.get(code, ""),
    }
    data.update(extra)
    return data


def record_event(db, case, kind: str, message: str = "", payload: dict | None = None) -> None:
    try:
        db.add_authoring_event(
            int(case.id), int(case.project_id), kind=kind, message=message, payload=payload or {}
        )
    except Exception as exc:  # 事件写失败不能影响主流程
        logger.warning("写入编写事件失败：%s", exc)


# ===== 用例 / 环境 =====


def resolve_case(db, case_id: int, project_id: int):
    case = db.get_case(int(case_id))
    if case is None or int(case.project_id) != int(project_id):
        return None
    return case


def case_payload(case) -> dict:
    return {
        "case_id": int(case.id),
        "project_id": int(case.project_id),
        "title": case.title or "",
        "precondition": case.precondition or "",
        "steps": list(case.steps or []),
        "expected": case.expected or "",
        "site": case.site,
        "category_path": case.category_path or "",
        "case_rev": contract.case_rev(case),
        "params": dict(case.params_json or {}),
        "params_schema": list(case.params_schema_json or []),
        "status": case.status,
        "script": {
            "version": int(case.script_version or 0),
            "hash": case.script_hash or "",
            "path": case.script_rel_path or "",
            "exists": bool(case.script_rel_path),
            "content": contract.current_script_source(case),
        },
        "source": getattr(case, "source", CaseSource.AI),
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }


def env_payload(db, case) -> dict:
    """返回当前应用环境的详情与认证信息（不返回密码明文）。"""
    env = resolve_current_env(db, int(case.project_id))
    if env is None:
        return fail("ENV_NOT_CONFIGURED", "项目未配置环境")
    if not bool(getattr(env, "allow_local_agent", 1)):
        return fail("ENV_NOT_ALLOWED", f"环境「{env.name}」已关闭本地 Agent 访问")
    if not (env.base_url or "").strip():
        return fail("ENV_NOT_CONFIGURED", f"环境「{env.name}」未配置 base_url")

    auth = prepare_auth(env)
    if not auth.ok:
        return fail("ENV_INVALID", f"登录态准备失败：{auth.message}")

    auth_mode = "none"
    header_name = ""
    header_value = ""
    storage_state_url = ""
    expires_at = datetime.now().isoformat()
    if auth.headers:
        auth_mode = "header"
        header_name, header_value = next(iter(auth.headers.items()))
    elif auth.storage_state_path and Path(auth.storage_state_path).is_file():
        auth_mode = getattr(env, "token_inject", "cookie") or "cookie"
        state_token, state_exp = issue_storage_state(auth.storage_state_path)
        storage_state_url = (
            f"/api/ui/automation/authoring/storage-state/{state_token}"
        )
        expires_at = state_exp.isoformat()

    return {
        "ok": True,
        "env_id": int(env.id),
        "name": env.name or "",
        "base_url": env.base_url or "",
        "entry_url": site_url(env, getattr(case, "site", "") or ""),
        "site": getattr(case, "site", "") or "",
        "auth": {
            "mode": auth_mode,
            "header_name": header_name,
            "header_value": header_value,
            "storage_state_url": storage_state_url,
            "expires_at": expires_at,
        },
        "auth_ready": auth_mode != "none",
        "message": auth.message,
        "usage": (
            "脚本里不要写死 token：运行时平台会自动注入 INSIGHT_UI_STORAGE_STATE / "
            "INSIGHT_UI_HEADERS。探索阶段把 storageState 下载到本地后传给 Playwright MCP，"
            "或使用 header 方式访问。"
        ),
    }


# ===== storage_state 一次性下载 =====


def issue_storage_state(path: str, ttl_minutes: int = 5) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(24)
    expires = datetime.now() + timedelta(minutes=ttl_minutes)
    with _SS_LOCK:
        now = datetime.now()
        for key in [k for k, v in _SS.items() if v[1] < now]:
            _SS.pop(key, None)
        _SS[token] = (path, expires, False)
    return token, expires


def consume_storage_state(token: str) -> Path | None:
    with _SS_LOCK:
        entry = _SS.get(token)
        if not entry:
            return None
        path, expires, used = entry
        if used or expires < datetime.now():
            return None
        _SS[token] = (path, expires, True)
    p = Path(path)
    return p if p.is_file() else None


# ===== 租约 =====


def acquire_lease(db, case, owner: str) -> bool:
    with _LEASE_LOCK:
        now = datetime.now()
        state = db.get_authoring_state(int(case.id))
        if (
            state is not None
            and state.lease_until is not None
            and state.lease_until > now
            and state.lease_owner
            and state.lease_owner != owner
        ):
            return False
        db.upsert_authoring_state(
            int(case.id),
            project_id=int(case.project_id),
            lease_owner=owner,
            lease_until=now + timedelta(minutes=LEASE_MINUTES),
        )
        return True


def release_lease(db, case) -> None:
    try:
        db.upsert_authoring_state(int(case.id), lease_owner="", lease_until=None)
    except Exception:
        pass


# ===== 校验 =====


def mark_generating(db, case) -> None:
    """Agent 首次拉取契约即视为开始生成；已有校验结果时不回退。"""
    try:
        state = db.get_authoring_state(int(case.id))
        if state is not None and state.stage in (
            AuthoringStage.GENERATING,
            AuthoringStage.VALIDATED,
            AuthoringStage.DRY_RUN_OK,
        ):
            return
        db.upsert_authoring_state(
            int(case.id),
            project_id=int(case.project_id),
            source_hash="",
            stage=AuthoringStage.GENERATING,
            validated_at=None,
            dry_run_at=None,
            last_error="",
        )
        record_event(db, case, "generating", "本地 Agent 已接入，开始生成脚本")
    except Exception as exc:  # 状态写入失败不能阻断 Agent 拉取契约
        logger.warning("写入生成中状态失败：%s", exc)


def validate(db, case, files) -> dict:
    normalized, problems = contract.normalize_files(files)
    if problems:
        first = problems[0]
        record_event(db, case, "validate_failed", first["message"], {"violations": problems})
        return fail(first["code"], first["message"], violations=problems)

    result = contract.validate_source(normalized, int(case.project_id))
    if result["ok"]:
        db.upsert_authoring_state(
            int(case.id),
            project_id=int(case.project_id),
            source_hash=result["source_hash"],
            stage=AuthoringStage.VALIDATED,
            validated_at=datetime.now(),
            dry_run_at=None,
            last_error="",
        )
        record_event(
            db,
            case,
            "validated",
            f"静态校验通过（{result['file_count']} 个文件）",
            {"source_hash": result["source_hash"]},
        )
        return {
            "ok": True,
            "stage": AuthoringStage.VALIDATED,
            "source_hash": result["source_hash"],
            "files": result["files"],
            "next": "script.dry_run",
        }

    db.upsert_authoring_state(
        int(case.id),
        project_id=int(case.project_id),
        source_hash=result["source_hash"],
        stage=AuthoringStage.NONE,
        last_error=result["violations"][0]["message"] if result["violations"] else "",
    )
    record_event(
        db,
        case,
        "validate_failed",
        result["violations"][0]["message"] if result["violations"] else "校验失败",
        {"violations": result["violations"]},
    )
    return fail(
        result["violations"][0]["code"],
        result["violations"][0]["message"],
        violations=result["violations"],
        stage=result["stage"],
    )


def _check_dry_run_ready(db, case, files_hash: str) -> dict | None:
    state = db.get_authoring_state(int(case.id))
    if (
        state is None
        or state.stage != AuthoringStage.VALIDATED
        or state.source_hash != files_hash
        or state.validated_at is None
        or datetime.now() - state.validated_at > VALIDATED_TTL
    ):
        return fail(
            "VALIDATION_REQUIRED",
            "请先对当前 files 调用 script.validate（结果 30 分钟内有效）",
        )
    return None


def dry_run(db, case, files, expected_hash: str) -> dict:
    """在 staging 目录真实执行一次（不写 ui_runs、不污染正式资产）。"""
    normalized, problems = contract.normalize_files(files)
    if problems:
        return fail(problems[0]["code"], problems[0]["message"], violations=problems)

    actual_hash = contract.source_hash(normalized)
    if expected_hash and expected_hash != actual_hash:
        return fail(
            "HASH_MISMATCH",
            f"source_hash 与 files 不一致：提交 {expected_hash[:12]}，实际 {actual_hash[:12]}",
        )

    # 先做一次 L1，避免把明显非法的脚本送进浏览器；同时刷新状态
    lint = contract.validate_source(normalized, int(case.project_id), run_l2=False)
    if not lint["ok"]:
        first = lint["violations"][0]
        return fail(first["code"], first["message"], violations=lint["violations"])
    ready = _check_dry_run_ready(db, case, actual_hash)
    if ready:
        return ready

    env = resolve_current_env(db, int(case.project_id))
    if env is None:
        return fail("ENV_NOT_CONFIGURED", "项目未配置环境")
    if not bool(getattr(env, "allow_local_agent", 1)):
        return fail("ENV_NOT_ALLOWED", f"环境「{env.name}」已关闭本地 Agent 访问")

    with _dry_run_guard:
        last = _dry_run_last.get(int(case.id), 0.0)
        if time.time() - last < DRY_RUN_COOLDOWN_SEC:
            return fail(
                "BUSY",
                f"试跑冷却中，请 {int(DRY_RUN_COOLDOWN_SEC - (time.time() - last))} 秒后重试",
            )
        _dry_run_last[int(case.id)] = time.time()

    from insight_aitest.modules.ui.backend.automation.runner import run_script

    staging = paths.staging_root(int(case.project_id), int(case.id)) / "agent" / actual_hash[:12]
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    for rel, content in normalized.items():
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run_dir = staging / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    record_event(db, case, "dry_run_started", "开始本地试跑", {"source_hash": actual_hash})
    try:
        result = run_script(
            case,
            env,
            script_path=staging / contract.CASE_FILE,
            run_dir=run_dir,
            timeout=DRY_RUN_TIMEOUT_SEC,
            pages_root=staging,
        )
    except Exception as exc:
        logger.exception("本地试跑异常")
        return fail("ENV_INVALID", f"试跑执行器异常：{type(exc).__name__}: {exc}")

    log_tail = ""
    log_file = run_dir / "stdout.log"
    if log_file.is_file():
        text = log_file.read_text(encoding="utf-8", errors="replace")
        log_tail = text[-4000:]

    passed = result.get("status") == "passed"
    if not passed:
        code = _classify_dry_run(result.get("error_message") or "", log_tail)
        message = result.get("error_message") or "试跑失败"
        # 沉淀错题：本地 Agent 路径同样要能让项目的「踩坑库」越用越准
        lessons.record_failure(db, case, "script", f"{code}: {message}\n{log_tail[-1200:]}")
        db.upsert_authoring_state(
            int(case.id), project_id=int(case.project_id), last_error=message
        )
        record_event(
            db,
            case,
            "dry_run_failed",
            result.get("error_message") or "试跑失败",
            {"code": code, "source_hash": actual_hash},
        )
        return fail(
            code,
            result.get("error_message") or "试跑失败",
            source_hash=actual_hash,
            duration_ms=result.get("duration_ms"),
            log_tail=log_tail,
        )

    db.upsert_authoring_state(
        int(case.id),
        project_id=int(case.project_id),
        source_hash=actual_hash,
        stage=AuthoringStage.DRY_RUN_OK,
        dry_run_at=datetime.now(),
        last_error="",
    )
    record_event(db, case, "dry_run_passed", "试跑通过", {"source_hash": actual_hash})
    return {
        "ok": True,
        "stage": AuthoringStage.DRY_RUN_OK,
        "source_hash": actual_hash,
        "duration_ms": result.get("duration_ms"),
        "screenshots": result.get("screenshots") or [],
        "log_tail": log_tail[-1500:],
        "next": "script.submit",
    }


def _classify_dry_run(message: str, log: str) -> str:
    text = f"{message}\n{log}".lower()
    if "超过" in text and "秒被终止" in text:
        return "TIMEOUT"
    if "timeout" in text and ("exceeded" in text or "超时" in text):
        return "TIMEOUT"
    if "net::err" in text or "econnrefused" in text or "err_name_not_resolved" in text:
        return "ENV_INVALID"
    if "playwright install" in text or "executable doesn't exist" in text:
        return "ENV_INVALID"
    if "strict mode violation" in text or "not found" in text or "no element" in text:
        return "SELECTOR_NOT_FOUND"
    return "SCRIPT_ERROR" if "SCRIPT_ERROR" in contract.ERROR_FIX else "SELECTOR_NOT_FOUND"


# ===== 入库 =====


def _learn_from_submit(db, case, version: int) -> None:
    """本轮若「先失败、后通过」，把踩坑与结果合成一条修复样本。"""
    try:
        events = db.list_authoring_events(int(case.id), limit=200)
    except Exception:  # noqa: BLE001 - 错题库写入不能影响入库主链路
        return
    last_failed = None
    last_passed_id = 0
    for event in events:
        if event.kind == "dry_run_passed":
            last_passed_id = int(event.id or 0)
        elif event.kind == "dry_run_failed":
            last_failed = event
    if last_failed is None or int(last_failed.id or 0) > last_passed_id:
        return
    lessons.record_solution(
        db,
        case,
        "script",
        last_failed.message or "dry_run 失败",
        f"按 dry_run 反馈修复后首跑通过，脚本已入库 v{version}",
    )


def _asset_target(project_id: int, rel: str) -> Path:
    package, name = rel.split("/", 1)
    root = paths.pages_dir(project_id) if package == "pages" else paths.common_dir(project_id)
    return root / name


def _write_assets(project_id: int, files: dict[str, str], force: bool) -> tuple[list[dict], dict | None]:
    """写入 pages/common；先整体检查冲突，再落盘（覆盖前备份）。"""
    plan: list[tuple[str, Path, str, str | None]] = []
    for rel in sorted(files):
        if rel == contract.CASE_FILE:
            continue
        target = _asset_target(project_id, rel)
        content = files[rel]
        existing: str | None = None
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if existing == content:
                continue
            if not force:
                current = contract.source_hash({rel: existing})
                return [], fail(
                    "ASSET_CONFLICT",
                    f"资产 {rel} 已存在且内容不同（sha256={current[:12]}）",
                    asset=rel,
                    current_sha256=current,
                )
        plan.append((rel, target, content, existing))

    written: list[dict] = []
    for rel, target, content, existing in plan:
        if existing is not None:
            backup_dir = target.parent / "history"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f"{target.stem}_{datetime.now():%Y%m%d-%H%M%S-%f}.py"
            backup.write_text(existing, encoding="utf-8")
            written.append({"path": rel, "action": "overwritten", "backup": str(backup)})
        else:
            written.append({"path": rel, "action": "created"})
        target.write_text(content, encoding="utf-8")
    return written, None


def submit(
    db,
    case,
    files,
    expected_hash: str,
    expect_case_rev: str,
    expect_script_version: int,
    params_schema=None,
    force_assets: bool = False,
) -> dict:
    normalized, problems = contract.normalize_files(files)
    if problems:
        return fail(problems[0]["code"], problems[0]["message"], violations=problems)

    actual_hash = contract.source_hash(normalized)
    if expected_hash and expected_hash != actual_hash:
        return fail(
            "HASH_MISMATCH",
            f"source_hash 与 files 不一致：提交 {expected_hash[:12]}，实际 {actual_hash[:12]}",
        )

    lint = contract.validate_source(normalized, int(case.project_id), run_l2=False)
    if not lint["ok"]:
        first = lint["violations"][0]
        return fail(first["code"], first["message"], violations=lint["violations"])

    # 守卫 1：用例内容是否已被修改
    current_rev = contract.case_rev(case)
    if expect_case_rev and expect_case_rev != current_rev:
        return fail(
            "STALE_CASE",
            f"用例已被修改（case_rev={current_rev}），请重新 case.get 后生成脚本",
            case_rev=current_rev,
        )

    # 守卫 2：平台脚本版本是否已变化
    current_version = int(case.script_version or 0)
    if int(expect_script_version) != current_version:
        return fail(
            "SCRIPT_CONFLICT",
            f"平台脚本版本为 v{current_version}，与提交的 v{expect_script_version} 不一致",
            script_version=current_version,
        )

    # 守卫 3：试跑状态（状态机 + TTL）
    state = db.get_authoring_state(int(case.id))
    if (
        state is None
        or state.stage != AuthoringStage.DRY_RUN_OK
        or state.source_hash != actual_hash
        or state.dry_run_at is None
        or datetime.now() - state.dry_run_at > DRY_RUN_TTL
    ):
        return fail(
            "VALIDATION_REQUIRED",
            "当前 files 尚未通过 script.dry_run（24 小时内有效），请先试跑",
        )

    if case.status in (CaseStatus.GENERATING, CaseStatus.FIXING, CaseStatus.RUNNING):
        return fail("BUSY", "用例正在生成/执行中，请稍后再提交")

    project_id = int(case.project_id)
    written, asset_error = _write_assets(project_id, normalized, force_assets)
    if asset_error:
        if force_assets:
            # 已经覆盖了部分文件但后续失败：如实回报已写入的资产，便于人工核对
            asset_error["assets_written"] = written
        return asset_error

    # 写脚本：旧版本先归档，再原子覆盖
    target = paths.case_script(project_id, int(case.id))
    target.parent.mkdir(parents=True, exist_ok=True)
    old_version = current_version
    if target.exists() and old_version >= 1:
        archive = paths.case_history_path(project_id, int(case.id), old_version)
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, archive)
    target.write_text(normalized[contract.CASE_FILE], encoding="utf-8")
    new_version = old_version + 1

    fields = {
        "script_rel_path": paths.to_rel(target),
        "script_version": new_version,
        "script_hash": actual_hash,
        "status": CaseStatus.IMPLEMENTED,
        "source": CaseSource.LOCAL_AGENT,
        "authoring_by": "local_agent",
        "authoring_at": datetime.now(),
        "last_generated_at": datetime.now(),
        "last_error_category": None,
        "last_error_message": "",
    }
    if isinstance(params_schema, list) and params_schema:
        fields["params_schema_json"] = params_schema
        fields["params_updated_at"] = datetime.now()
    db.update_case(int(case.id), **fields)
    _learn_from_submit(db, case, new_version)
    db.upsert_authoring_state(
        int(case.id),
        project_id=project_id,
        stage=AuthoringStage.NONE,
        source_hash="",
        validated_at=None,
        dry_run_at=None,
        last_error="",
        lease_owner="",
        lease_until=None,
    )
    record_event(
        db,
        case,
        "submitted",
        f"脚本已入库 v{new_version}",
        {"script_version": new_version, "source_hash": actual_hash, "assets": written},
    )
    return {
        "ok": True,
        "case_id": int(case.id),
        "script_version": new_version,
        "source_hash": actual_hash,
        "script_path": fields["script_rel_path"],
        "assets_written": written,
        "message": f"已入库，脚本版本 v{new_version}",
    }
