# -*- coding: utf-8 -*-
"""AI 自动化用例资产 API：导入 / 列表 / 详情 / 编辑 / 生成 / 修复 / 执行 / 产物。"""

from __future__ import annotations

import shutil
import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from insight_aitest.modules.ui.backend.automation import concurrency, paths
from insight_aitest.modules.ui.backend.automation.database import UIAutomationDatabase
from insight_aitest.modules.ui.backend.automation.deps import get_automation_db
from insight_aitest.modules.ui.backend.automation.generator import start_job
from insight_aitest.modules.ui.backend.automation.importer import import_cases, list_importable
from insight_aitest.modules.ui.backend.automation.models import (
    CaseStatus,
    GenerationKind,
    Site,
)
from insight_aitest.modules.ui.backend.automation.runner import EnvMissingError, record_run, run_script

router = APIRouter(prefix="/automation/cases", tags=["ui-automation"])


class ImportRequest(BaseModel):
    project_id: int
    document_ids: list[int]
    site_map: dict[int, str] | None = None


class CasePatch(BaseModel):
    title: str | None = None
    precondition: str | None = None
    steps: list[str] | None = None
    expected: str | None = None
    site: str | None = None


def _case_out(case, db: UIAutomationDatabase) -> dict:
    progress = concurrency.get_progress(case.id)
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
        "site": case.site,
        "status": case.status,
        "script_version": case.script_version,
        "has_script": bool(case.script_rel_path),
        "last_error_category": case.last_error_category,
        "last_error_message": case.last_error_message,
        "last_run_id": case.last_run_id,
        "last_generated_at": case.last_generated_at.isoformat() if case.last_generated_at else None,
        "progress": progress,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }


def _get_or_404(case_id: int, db: UIAutomationDatabase):
    case = db.get_case(case_id)
    if case is None:
        raise HTTPException(404, "自动化用例不存在")
    return case


@router.get("")
def list_cases(
    project_id: int | None = None,
    status: str | None = Query(None),
    category_path: str | None = Query(None),
    keyword: str | None = Query(None),
    page: int = 1,
    page_size: int = 50,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    items, total = db.list_cases(
        project_id=project_id,
        status=status,
        category_path=category_path,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [_case_out(c, db) for c in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/importable")
def get_importable(
    project_id: int = Query(...),
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    return {"items": list_importable(project_id, db)}


@router.post("/import")
def do_import(
    body: ImportRequest,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    if not body.document_ids:
        raise HTTPException(400, "请选择要导入的用例")
    return import_cases(body.project_id, body.document_ids, db, body.site_map)


@router.get("/{case_id}")
def get_case(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    return _case_out(_get_or_404(case_id, db), db)


@router.patch("/{case_id}")
def patch_case(
    case_id: int,
    body: CasePatch,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    case = _get_or_404(case_id, db)
    if case.status in (CaseStatus.GENERATING, CaseStatus.FIXING, CaseStatus.RUNNING):
        raise HTTPException(409, "用例正在生成/执行中，请稍后再修改")
    fields = body.model_dump(exclude_none=True)
    if not fields:
        return _case_out(case, db)
    if "site" in fields and fields["site"] != case.site:
        if fields["site"] not in Site.ALL:
            raise HTTPException(400, "端只能是 frontend 或 backend")
        # 换端会改变入口地址，旧脚本不再可用：归档到 history 后清空指针，需重新生成
        if case.script_rel_path:
            src = paths.resolve_rel(case.script_rel_path)
            version = int(case.script_version or 0)
            if src.exists() and version >= 1:
                archive = paths.case_history_path(int(case.project_id), case_id, version)
                archive.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, archive)
            fields.update(
                script_rel_path="",
                script_version=0,
                script_hash="",
                last_error_category=None,
                last_error_message=None,
            )
    # 用例信息变更后脚本与用例可能不再匹配：回到未实现，保留已有脚本供修复
    fields["status"] = CaseStatus.NOT_IMPLEMENTED
    db.update_case(case_id, **fields)
    return _case_out(db.get_case(case_id), db)


@router.delete("/{case_id}")
def delete_case(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    case = _get_or_404(case_id, db)
    if case.status in (CaseStatus.GENERATING, CaseStatus.FIXING, CaseStatus.RUNNING):
        raise HTTPException(409, "用例正在生成/执行中，无法删除")
    db.delete_case(case_id)
    return {"deleted": case_id}


@router.get("/{case_id}/script")
def get_script(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    case = _get_or_404(case_id, db)
    if not case.script_rel_path:
        return {"content": "", "version": 0}
    p = paths.resolve_rel(case.script_rel_path)
    if not p.exists():
        raise HTTPException(404, "脚本文件不存在（可能未同步到本机）")
    return {"content": p.read_text(encoding="utf-8"), "version": case.script_version}


def _start_generate(case_id: int, kind: str, db: UIAutomationDatabase) -> dict:
    case = _get_or_404(case_id, db)
    if kind == GenerationKind.FIX and not case.script_rel_path:
        raise HTTPException(400, "该用例还没有脚本，无法自动修复，请先生成脚本")
    project_id = int(case.project_id)
    if not concurrency.acquire(project_id):
        raise HTTPException(409, "该项目已有任务在执行（生成/修复/运行），请稍后重试")
    concurrency.set_progress(case_id, "排队", "任务已提交")
    try:
        start_job(case_id, kind)
    except Exception:
        concurrency.release(project_id)
        raise
    return {"accepted": True, "case_id": case_id, "kind": kind}


@router.post("/{case_id}/generate")
def generate(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    return _start_generate(case_id, GenerationKind.GENERATE, db)


@router.post("/{case_id}/fix")
def fix(case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)) -> dict:
    return _start_generate(case_id, GenerationKind.FIX, db)


def _run_worker(case_id: int) -> None:
    db = get_automation_db()
    case = db.get_case(case_id)
    if case is None:
        return
    project_id = int(case.project_id)
    prev_status = case.status
    run_id = None
    try:
        db.update_case(case_id, status=CaseStatus.RUNNING)
        concurrency.set_progress(case_id, "执行中", "运行固化脚本")
        env = db.default_env(project_id)
        result = run_script(case, env)
        run_id = record_run(case, env, result)
        concurrency.set_progress(
            case_id,
            "完成" if result.get("run_status") == "passed" else "失败",
            result.get("error_message") or "执行完成",
        )
    except EnvMissingError as e:
        db.update_case(case_id, status=prev_status)
        concurrency.set_progress(case_id, "失败", str(e))
    except Exception as e:  # 执行器异常不能把用例卡在 running
        db.update_case(case_id, status=prev_status)
        concurrency.set_progress(case_id, "失败", f"执行器异常：{type(e).__name__}: {e}")
    finally:
        current = db.get_case(case_id)
        if current is not None and current.status == CaseStatus.RUNNING:
            db.update_case(
                case_id,
                status=CaseStatus.IMPLEMENTED if current.script_version >= 1 else CaseStatus.NOT_IMPLEMENTED,
            )
        concurrency.release(project_id)


@router.post("/{case_id}/run")
def run_case(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    case = _get_or_404(case_id, db)
    if not case.script_rel_path:
        raise HTTPException(400, "请先生成并固化脚本")
    project_id = int(case.project_id)
    if not concurrency.acquire(project_id):
        raise HTTPException(409, "该项目已有任务在执行（生成/修复/运行），请稍后重试")
    threading.Thread(
        target=_run_worker, args=(case_id,), daemon=True, name=f"ui-run-{case_id}"
    ).start()
    return {"accepted": True, "case_id": case_id}


@router.get("/{case_id}/runs")
def list_runs(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> list[dict]:
    _get_or_404(case_id, db)
    return db.list_script_runs(case_id)


@router.get("/{case_id}/runs/{run_id}/artifact/{filename}")
def get_artifact(
    case_id: int,
    run_id: int,
    filename: str,
    db: UIAutomationDatabase = Depends(get_automation_db),
):
    _get_or_404(case_id, db)
    run = db.get_script_run(run_id)
    if run is None or not run["artifacts_rel_path"]:
        raise HTTPException(404, "执行产物不存在")
    base = paths.resolve_rel(run["artifacts_rel_path"]).resolve()
    target = (base / filename).resolve()
    if not target.is_relative_to(base) or not target.exists() or not target.is_file():
        raise HTTPException(404, "产物文件不存在")
    return FileResponse(target)


@router.get("/{case_id}/generations")
def list_generations(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> list[dict]:
    _get_or_404(case_id, db)
    return [
        {
            "id": g.id,
            "kind": g.kind,
            "attempt": g.attempt,
            "status": g.status,
            "error_category": g.error_category,
            "error_message": g.error_message,
            "tool_calls": g.tool_calls,
            "model": g.model,
            "log_rel_path": g.log_rel_path,
            "started_at": g.started_at.isoformat() if g.started_at else None,
            "finished_at": g.finished_at.isoformat() if g.finished_at else None,
        }
        for g in db.list_generations(case_id)
    ]


@router.get("/{case_id}/progress")
def get_progress(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    case = _get_or_404(case_id, db)
    return {"status": case.status, "progress": concurrency.get_progress(case_id)}


# 兼容：前端可能直接拼产物绝对名
@router.get("/{case_id}/runs/{run_id}/result")
def get_result(
    case_id: int,
    run_id: int,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    _get_or_404(case_id, db)
    run = db.get_script_run(run_id)
    if run is None or not run["artifacts_rel_path"]:
        raise HTTPException(404, "执行产物不存在")
    p = paths.resolve_rel(run["artifacts_rel_path"]) / "result.json"
    if not p.exists():
        return {}
    import json

    return json.loads(p.read_text(encoding="utf-8"))
