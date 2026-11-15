# -*- coding: utf-8 -*-
"""App 自动化执行记录与产物（stdout.log / device.log / 截图）API。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

from insight_aitest.modules.mobile.backend.automation import paths
from insight_aitest.modules.mobile.backend.deps import get_mobile_db
from insight_aitest.modules.mobile.backend.persistence.database import MobileDatabase
from insight_aitest.modules.mobile.backend.persistence.models import RunStatus

router = APIRouter(prefix="/runs", tags=["mobile-runs"])


def _run_detail_dict(run) -> dict:
    art_dir = paths.resolve_rel(run.artifacts_rel_path) if run.artifacts_rel_path else None
    screenshots: list[str] = []
    has_log = False
    has_device_log = False
    if art_dir and art_dir.exists():
        screenshots = sorted(p.name for p in art_dir.glob("*.png"))
        has_log = (art_dir / "stdout.log").exists()
        has_device_log = (art_dir / "device.log").exists()
    return {
        "id": run.id,
        "case_id": run.case_id,
        "project_id": run.project_id,
        "app_id": run.app_id,
        "case_title": run.case_title,
        "status": run.status.value if isinstance(run.status, RunStatus) else str(run.status),
        "runner": run.runner,
        "device_id": run.device_id,
        "device_model": run.device_model,
        "os_version": run.os_version,
        "script_version": run.script_version,
        "duration_ms": run.duration_ms,
        "error": run.error,
        "screenshots": screenshots,
        "has_log": has_log,
        "has_device_log": has_device_log,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.get("")
def list_runs(
    case_id: int | None = Query(None),
    project_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: MobileDatabase = Depends(get_mobile_db),
) -> list[dict]:
    return db.list_runs(case_id=case_id, project_id=project_id, limit=limit)


@router.get("/{run_id}")
def get_run(run_id: int, db: MobileDatabase = Depends(get_mobile_db)) -> dict:
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(404, "执行记录不存在")
    return _run_detail_dict(run)


@router.get("/{run_id}/log")
def get_run_stdout(run_id: int, db: MobileDatabase = Depends(get_mobile_db)):
    run = db.get_run(run_id)
    if run is None or not run.artifacts_rel_path:
        raise HTTPException(404, "运行日志不存在")
    p = paths.resolve_rel(run.artifacts_rel_path) / "stdout.log"
    if not p.exists():
        return PlainTextResponse("")
    return PlainTextResponse(p.read_text(encoding="utf-8", errors="replace"))


@router.get("/{run_id}/device-log")
def get_run_device_log(run_id: int, db: MobileDatabase = Depends(get_mobile_db)):
    run = db.get_run(run_id)
    if run is None or not run.artifacts_rel_path:
        raise HTTPException(404, "设备日志不存在")
    p = paths.resolve_rel(run.artifacts_rel_path) / "device.log"
    if not p.exists():
        return PlainTextResponse("")
    return PlainTextResponse(p.read_text(encoding="utf-8", errors="replace"))


@router.get("/{run_id}/artifacts/{filename}")
def get_run_artifact(
    run_id: int, filename: str, db: MobileDatabase = Depends(get_mobile_db)
):
    run = db.get_run(run_id)
    if run is None or not run.artifacts_rel_path:
        raise HTTPException(404, "产物不存在")
    safe = Path(filename).name
    p = paths.resolve_rel(run.artifacts_rel_path) / safe
    if not p.exists():
        raise HTTPException(404, "产物文件不存在")
    media = "image/png" if safe.endswith(".png") else "application/octet-stream"
    return FileResponse(p, media_type=media)
