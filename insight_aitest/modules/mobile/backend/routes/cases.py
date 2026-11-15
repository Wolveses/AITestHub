# -*- coding: utf-8 -*-
"""App 自动化用例资产、生成会话与手动回放 API。"""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from insight_aitest.modules.mobile.backend.automation import paths
from insight_aitest.modules.mobile.backend.automation.importer import import_cases, list_importable
from insight_aitest.modules.mobile.backend.automation.runner import MobileEnvError, run_script
from insight_aitest.modules.mobile.backend.automation.session_manager import (
    cancel_generation_session,
    list_step_screenshots,
    read_events,
    start_generation_session,
)
from insight_aitest.modules.mobile.backend.automation.validator import validate_script_source
from insight_aitest.modules.mobile.backend.deps import get_mobile_db
from insight_aitest.modules.mobile.backend.device_pool import DeviceBusyError, get_lease_manager
from insight_aitest.modules.mobile.backend.persistence.database import MobileDatabase
from insight_aitest.modules.mobile.backend.persistence.models import (
    CaseStatus,
    GenerationKind,
    MobilePlatform,
    RunStatus,
)

router = APIRouter(prefix="/automation/cases", tags=["mobile-automation"])


class ImportRequest(BaseModel):
    project_id: int
    document_ids: list[int]
    platform_map: dict[int, str] | None = None


class CasePatch(BaseModel):
    title: str | None = None
    precondition: str | None = None
    steps: list[str] | None = None
    expected: str | None = None
    platform: str | None = None
    default_app_id: int | None = None


class ParamsUpdate(BaseModel):
    values: dict[str, str | int | float | bool | None] = {}


class ScriptUpdate(BaseModel):
    content: str


class GenerationSessionCreate(BaseModel):
    device_id: str
    app_id: int | None = None
    kind: str = GenerationKind.GENERATE
    engine_detail: str = "remote_mcp"


class RunRequest(BaseModel):
    device_id: str
    app_id: int | None = None


def _case_out(case) -> dict:
    return {
        "id": case.id,
        "project_id": case.project_id,
        "kb_document_id": case.kb_document_id,
        "source_case_id": case.source_case_id,
        "source_workspace_id": case.source_workspace_id,
        "title": case.title,
        "precondition": case.precondition,
        "steps": list(case.steps or []),
        "expected": case.expected,
        "category_path": case.category_path,
        "kb_folder_id": case.kb_folder_id,
        "platform": case.platform,
        "default_app_id": case.default_app_id,
        "params": dict(case.params_json or {}),
        "params_schema": list(case.params_schema_json or []),
        "params_updated_at": case.params_updated_at.isoformat() if case.params_updated_at else None,
        "status": case.status,
        "script_version": case.script_version,
        "has_script": bool(case.script_rel_path),
        "last_error_category": case.last_error_category,
        "last_error_message": case.last_error_message,
        "last_run_id": case.last_run_id,
        "last_generated_at": case.last_generated_at.isoformat() if case.last_generated_at else None,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }


def _gen_out(gen) -> dict:
    return {
        "id": gen.id,
        "case_id": gen.mobile_case_id,
        "kind": gen.kind,
        "attempt": gen.attempt,
        "status": gen.status,
        "engine_type": gen.engine_type,
        "engine_detail": gen.engine_detail,
        "device_id": gen.device_id,
        "app_id": gen.app_id,
        "error_category": gen.error_category,
        "error_message": gen.error_message,
        "tool_calls": gen.tool_calls,
        "last_dry_run_passed": bool(gen.last_dry_run_passed),
        "started_at": gen.started_at.isoformat() if gen.started_at else None,
        "finished_at": gen.finished_at.isoformat() if gen.finished_at else None,
        "step_screenshots": list_step_screenshots(int(gen.mobile_case_id), int(gen.id)),
    }


def _get_or_404(case_id: int, db: MobileDatabase):
    case = db.get_case(case_id)
    if case is None:
        raise HTTPException(404, "App 自动化用例不存在")
    return case


@router.get("")
def list_cases(
    project_id: int | None = None,
    status: str | None = Query(None),
    platform: str | None = Query(None),
    category_path: str | None = Query(None),
    keyword: str | None = Query(None),
    page: int = 1,
    page_size: int = 50,
    db: MobileDatabase = Depends(get_mobile_db),
) -> dict:
    items, total = db.list_cases(
        project_id=project_id,
        status=status,
        platform=platform,
        category_path=category_path,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [_case_out(c) for c in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/importable")
def get_importable(
    project_id: int = Query(...),
    search: str = "",
    category_path: str = "",
    page: int = 1,
    page_size: int = 200,
    db: MobileDatabase = Depends(get_mobile_db),
) -> dict:
    return list_importable(
        project_id,
        db,
        search=search,
        category_path=category_path,
        page=page,
        page_size=page_size,
    )


@router.post("/import")
def do_import(
    body: ImportRequest,
    db: MobileDatabase = Depends(get_mobile_db),
) -> dict:
    if not body.document_ids:
        raise HTTPException(400, "请选择要导入的用例")
    return import_cases(body.project_id, body.document_ids, db, body.platform_map)


@router.get("/generations/{gen_id}")
def get_generation_detail(gen_id: int, db: MobileDatabase = Depends(get_mobile_db)) -> dict:
    gen = db.get_generation(gen_id)
    if gen is None:
        raise HTTPException(404, "生成会话不存在")
    out = _gen_out(gen)
    out["events"] = read_events(int(gen.mobile_case_id), int(gen.id))
    return out


@router.get("/generations/{gen_id}/steps/{filename}")
def get_generation_step_image(
    gen_id: int, filename: str, db: MobileDatabase = Depends(get_mobile_db)
):
    gen = db.get_generation(gen_id)
    if gen is None:
        raise HTTPException(404, "生成会话不存在")
    safe_name = Path(filename).name
    target = paths.generation_steps_dir(int(gen.mobile_case_id), gen_id) / safe_name
    if not target.exists():
        raise HTTPException(404, "过程截图不存在")
    return FileResponse(target, media_type="image/png")


@router.get("/{case_id}")
def get_case(case_id: int, db: MobileDatabase = Depends(get_mobile_db)) -> dict:
    return _case_out(_get_or_404(case_id, db))


@router.patch("/{case_id}")
def patch_case(
    case_id: int,
    body: CasePatch,
    db: MobileDatabase = Depends(get_mobile_db),
) -> dict:
    case = _get_or_404(case_id, db)
    if case.status in (CaseStatus.GENERATING, CaseStatus.FIXING, CaseStatus.RUNNING):
        raise HTTPException(409, "用例正在生成或执行中，请稍后再修改")
    fields = body.model_dump(exclude_none=True)
    if not fields:
        return _case_out(case)
    if "platform" in fields and fields["platform"] not in MobilePlatform.ALL:
        raise HTTPException(400, "platform 仅支持 android 或 ios")
    if any(k in fields for k in ("title", "precondition", "steps", "expected", "platform")):
        fields["status"] = CaseStatus.NOT_IMPLEMENTED
    db.update_case(case_id, **fields)
    return _case_out(db.get_case(case_id))


@router.delete("/{case_id}")
def delete_case(case_id: int, db: MobileDatabase = Depends(get_mobile_db)) -> dict:
    case = _get_or_404(case_id, db)
    if case.status in (CaseStatus.GENERATING, CaseStatus.FIXING, CaseStatus.RUNNING):
        raise HTTPException(409, "用例正在生成或执行中，无法删除")
    db.delete_case(case_id)
    return {"deleted": case_id}


@router.put("/{case_id}/params")
def put_case_params(
    case_id: int,
    body: ParamsUpdate,
    db: MobileDatabase = Depends(get_mobile_db),
) -> dict:
    case = _get_or_404(case_id, db)
    if case.status in (CaseStatus.GENERATING, CaseStatus.FIXING, CaseStatus.RUNNING):
        raise HTTPException(409, "用例正在生成或执行中，请稍后再修改参数")
    merged = dict(case.params_json or {})
    merged.update(body.values)
    db.update_case(case_id, params_json=merged, params_updated_at=datetime.now())
    return _case_out(db.get_case(case_id))


@router.get("/{case_id}/script")
def get_script(case_id: int, db: MobileDatabase = Depends(get_mobile_db)) -> dict:
    case = _get_or_404(case_id, db)
    if not case.script_rel_path:
        return {"content": "", "version": 0}
    p = paths.resolve_rel(case.script_rel_path)
    if not p.exists():
        raise HTTPException(404, "脚本文件不存在")
    return {"content": p.read_text(encoding="utf-8"), "version": case.script_version}


@router.put("/{case_id}/script")
def put_script(
    case_id: int,
    body: ScriptUpdate,
    db: MobileDatabase = Depends(get_mobile_db),
) -> dict:
    case = _get_or_404(case_id, db)
    if case.status in (CaseStatus.GENERATING, CaseStatus.FIXING, CaseStatus.RUNNING):
        raise HTTPException(409, "用例正在生成或执行中，不能修改脚本")
    err = validate_script_source(body.content, require_test_entry=True)
    if err:
        raise HTTPException(400, err)

    dst = paths.case_script_path(int(case.project_id), case_id)
    new_ver = int(case.script_version or 0) + 1
    if dst.exists() and int(case.script_version or 0) > 0:
        hist = paths.case_history_dir(int(case.project_id), case_id) / f"case_v{case.script_version}.py"
        hist.write_text(dst.read_text(encoding="utf-8"), encoding="utf-8")
    dst.write_text(body.content, encoding="utf-8")
    digest = hashlib.sha256(body.content.encode("utf-8")).hexdigest()
    db.update_case(
        case_id,
        status=CaseStatus.IMPLEMENTED,
        script_rel_path=paths.to_rel(dst),
        script_version=new_ver,
        script_hash=digest,
    )
    return {"version": new_ver, "script_hash": digest}


# ===== 本地 Agent 生成会话 =====


@router.post("/{case_id}/generation-sessions")
def create_generation_session(
    case_id: int,
    body: GenerationSessionCreate,
    request: Request,
    db: MobileDatabase = Depends(get_mobile_db),
) -> dict:
    case = _get_or_404(case_id, db)
    app_id = body.app_id or case.default_app_id
    if not app_id:
        default_app = db.get_default_app(int(case.project_id), platform=case.platform)
        app_id = default_app.id if default_app else None
    if not app_id:
        raise HTTPException(400, "项目尚未配置 App 环境，请先在「设备与 App」中添加")

    base_url = str(request.base_url).rstrip("/")
    try:
        return start_generation_session(
            case_id,
            device_id=body.device_id,
            app_id=int(app_id),
            kind=body.kind,
            engine_detail=body.engine_detail,
            base_url=base_url,
        )
    except DeviceBusyError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/{case_id}/cancel-generate")
def cancel_generate(case_id: int, db: MobileDatabase = Depends(get_mobile_db)) -> dict:
    _get_or_404(case_id, db)
    ok = cancel_generation_session(case_id)
    return {"cancelled": ok, "case_id": case_id}


@router.get("/{case_id}/generations")
def list_generations(case_id: int, db: MobileDatabase = Depends(get_mobile_db)) -> list[dict]:
    _get_or_404(case_id, db)
    return [_gen_out(g) for g in db.list_generations(case_id)]


# ===== 手动回放执行 =====


@router.post("/{case_id}/run")
def run_case(
    case_id: int,
    body: RunRequest,
    db: MobileDatabase = Depends(get_mobile_db),
) -> dict:
    case = _get_or_404(case_id, db)
    if not case.script_rel_path:
        raise HTTPException(400, "该用例尚未固化脚本，请先完成生成")
    if case.status in (CaseStatus.GENERATING, CaseStatus.FIXING, CaseStatus.RUNNING):
        raise HTTPException(409, "用例当前正在生成或执行中")

    app_id = body.app_id or case.default_app_id
    if not app_id:
        default_app = db.get_default_app(int(case.project_id), platform=case.platform)
        app_id = default_app.id if default_app else None
    app = db.get_app(int(app_id)) if app_id else None
    if app is None:
        raise HTTPException(400, "未找到可用的 App 环境配置")

    lease_mgr = get_lease_manager()
    try:
        _, raw_token = lease_mgr.acquire(
            body.device_id, holder_type="run", case_id=case_id, ttl_seconds=660
        )
    except DeviceBusyError as e:
        raise HTTPException(409, str(e)) from e

    run_id = db.create_run(
        case_id=case_id,
        project_id=case.project_id,
        app_id=app.id,
        case_title=case.title,
        case_snapshot={"title": case.title, "steps": list(case.steps or []), "expected": case.expected},
        status=RunStatus.RUNNING,
        runner="script",
        device_id=body.device_id,
        script_version=case.script_version,
    )
    db.update_case(case_id, status=CaseStatus.RUNNING, last_run_id=run_id)

    def _worker() -> None:
        try:
            res = run_script(case, app, body.device_id)
            passed = res["status"] == "passed"
            db.update_run(
                run_id,
                status=RunStatus.PASSED if passed else RunStatus(res["run_status"]),
                duration_ms=res["duration_ms"],
                error=res["error_message"] or None,
                artifacts_rel_path=res["artifacts_rel_path"],
                finished_at=datetime.now(),
            )
            db.update_case(
                case_id,
                status=CaseStatus.IMPLEMENTED,
                last_error_category=None if passed else res["error_category"],
                last_error_message=None if passed else res["error_message"],
            )
        except MobileEnvError as e:
            db.update_run(
                run_id,
                status=RunStatus.ERROR,
                error=str(e),
                finished_at=datetime.now(),
            )
            db.update_case(
                case_id,
                status=CaseStatus.IMPLEMENTED,
                last_error_category="environment",
                last_error_message=str(e),
            )
        except Exception as e:
            db.update_run(
                run_id,
                status=RunStatus.ERROR,
                error=f"{type(e).__name__}: {e}",
                finished_at=datetime.now(),
            )
            db.update_case(
                case_id,
                status=CaseStatus.IMPLEMENTED,
                last_error_category="script",
                last_error_message=str(e),
            )
        finally:
            lease_mgr.release(body.device_id, token=raw_token, force=True)

    threading.Thread(target=_worker, daemon=True, name=f"mobile-run-{case_id}-{run_id}").start()
    return {"accepted": True, "run_id": run_id, "case_id": case_id, "device_id": body.device_id}
