# -*- coding: utf-8 -*-
"""服务端 JMeter 性能测试路由（脚本管理、AI 智能生成、预览、调试、下载、任务组合与执行报告）。"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from insight_aitest.modules.api.backend.deps import get_asset_db
from insight_aitest.modules.api.backend.persistence.asset_database import AssetDatabase
from insight_aitest.modules.performance.backend.deps import get_perf_db
from insight_aitest.modules.performance.backend.engine.manager import get_executor_manager
from insight_aitest.modules.performance.backend.persistence.database import PerfDatabase
from insight_aitest.modules.performance.backend.persistence.models import (
    PerfRun,
    PerfScript,
    PerfTask,
)
from insight_aitest.modules.performance.backend.services.ai_service import PerfAIService
from insight_aitest.modules.performance.backend.services.debugger import ScriptDebugger

router = APIRouter(prefix="/server", tags=["performance-server"])


# ===== Pydantic 请求/响应模型 =====
class ScriptGenerateIn(BaseModel):
    project_id: int
    plan_description: str
    concurrency: int = 10
    ramp_up: int = 5
    duration: int = 60


class ScriptSaveIn(BaseModel):
    project_id: int
    name: str
    description: str = ""
    plan_description: str = ""
    config: dict = {}
    jmx_content: str
    asset_ids: list[int] = []


class ScriptUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    jmx_content: Optional[str] = None
    config: Optional[dict] = None


class ScriptDebugIn(BaseModel):
    jmx_content: str
    base_url: str = ""
    global_vars: dict = {}


class TaskCreateIn(BaseModel):
    project_id: int
    name: str
    description: str = ""
    strategy_type: str = "duration"
    duration_seconds: int = 60
    loop_count: int = 1
    concurrency: int = 10
    ramp_up_seconds: int = 5
    engine_type: str = "builtin"
    script_items: list[dict]  # [{"script_id": 1, "weight": 100}]


class TaskUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    strategy_type: Optional[str] = None
    duration_seconds: Optional[int] = None
    loop_count: Optional[int] = None
    concurrency: Optional[int] = None
    ramp_up_seconds: Optional[int] = None
    engine_type: Optional[str] = None
    script_items: Optional[list[dict]] = None


# ===== 脚本管理 (Scripts) 端点 =====
@router.post("/scripts/generate-from-plan")
def generate_script_from_plan(
    body: ScriptGenerateIn,
    asset_db: AssetDatabase = Depends(get_asset_db),
) -> dict:
    """根据性能测试方案描述自动从当前项目 API 资产库匹配接口并编排生成 JMeter 脚本。"""
    llm = None
    try:
        from insight_aitest.modules.ai.backend.deps import get_llm

        llm = get_llm()
    except Exception:
        pass

    try:
        res = PerfAIService.generate_script_from_plan(
            project_id=body.project_id,
            plan_description=body.plan_description,
            asset_db=asset_db,
            llm=llm,
            target_concurrency=body.concurrency,
            ramp_up_seconds=body.ramp_up,
            duration_seconds=body.duration,
        )
        return {"ok": True, "data": res}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"生成失败: {exc}") from exc


@router.post("/scripts/debug")
async def debug_script_content(body: ScriptDebugIn) -> dict:
    """在线单步调试运行指定 JMX 脚本，回显详细响应与变量提取。"""
    try:
        res = await ScriptDebugger.debug(
            jmx_content=body.jmx_content,
            env_base_url=body.base_url,
            global_vars=body.global_vars,
        )
        return {"ok": True, "data": res}
    except Exception as exc:
        raise HTTPException(500, f"调试失败: {exc}") from exc


@router.post("/scripts")
def create_script(
    body: ScriptSaveIn,
    db: PerfDatabase = Depends(get_perf_db),
) -> dict:
    script = PerfScript(
        project_id=body.project_id,
        name=body.name,
        description=body.description,
        plan_description=body.plan_description,
        config=body.config,
        jmx_content=body.jmx_content,
        asset_ids=body.asset_ids,
    )
    sid = db.create_script(script)
    return {"ok": True, "id": sid}


@router.get("/scripts")
def list_scripts(
    project_id: Optional[int] = Query(None),
    keyword: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: PerfDatabase = Depends(get_perf_db),
) -> dict:
    items, total = db.list_scripts(
        project_id=project_id, keyword=keyword, page=page, page_size=page_size
    )
    return {
        "items": [
            {
                "id": s.id,
                "project_id": s.project_id,
                "name": s.name,
                "description": s.description,
                "plan_description": s.plan_description,
                "config": s.config,
                "asset_ids": s.asset_ids,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
            }
            for s in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/scripts/{script_id}")
def get_script(script_id: int, db: PerfDatabase = Depends(get_perf_db)) -> dict:
    s = db.get_script(script_id)
    if not s:
        raise HTTPException(404, "脚本不存在")
    return {
        "id": s.id,
        "project_id": s.project_id,
        "name": s.name,
        "description": s.description,
        "plan_description": s.plan_description,
        "config": s.config,
        "jmx_content": s.jmx_content,
        "asset_ids": s.asset_ids,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


@router.put("/scripts/{script_id}")
def update_script(
    script_id: int, body: ScriptUpdateIn, db: PerfDatabase = Depends(get_perf_db)
) -> dict:
    s = db.update_script(
        script_id,
        name=body.name,
        description=body.description,
        jmx_content=body.jmx_content,
        config=body.config,
    )
    if not s:
        raise HTTPException(404, "脚本不存在")
    return {"ok": True}


@router.delete("/scripts/{script_id}")
def delete_script(script_id: int, db: PerfDatabase = Depends(get_perf_db)) -> dict:
    if not db.delete_script(script_id):
        raise HTTPException(404, "脚本不存在")
    return {"ok": True}


@router.get("/scripts/{script_id}/download")
def download_script_jmx(script_id: int, db: PerfDatabase = Depends(get_perf_db)) -> Response:
    """以附件形式下载标准 .jmx 文件。"""
    s = db.get_script(script_id)
    if not s:
        raise HTTPException(404, "脚本不存在")
    filename = f"{s.name}.jmx"
    return Response(
        content=s.jmx_content,
        media_type="application/xml; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ===== 任务编排 (Tasks) 端点 =====
@router.post("/tasks")
def create_task(body: TaskCreateIn, db: PerfDatabase = Depends(get_perf_db)) -> dict:
    task = PerfTask(
        project_id=body.project_id,
        name=body.name,
        description=body.description,
        strategy_type=body.strategy_type,
        duration_seconds=body.duration_seconds,
        loop_count=body.loop_count,
        concurrency=body.concurrency,
        ramp_up_seconds=body.ramp_up_seconds,
        engine_type=body.engine_type,
    )
    tid = db.create_task(task, body.script_items)
    return {"ok": True, "id": tid}


@router.get("/tasks")
def list_tasks(
    project_id: Optional[int] = Query(None),
    keyword: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: PerfDatabase = Depends(get_perf_db),
) -> dict:
    items, total = db.list_tasks(
        project_id=project_id, keyword=keyword, page=page, page_size=page_size
    )
    out = []
    for t in items:
        scripts = db.get_task_scripts(t.id)
        out.append(
            {
                "id": t.id,
                "project_id": t.project_id,
                "name": t.name,
                "description": t.description,
                "strategy_type": t.strategy_type,
                "duration_seconds": t.duration_seconds,
                "loop_count": t.loop_count,
                "concurrency": t.concurrency,
                "ramp_up_seconds": t.ramp_up_seconds,
                "engine_type": t.engine_type,
                "last_status": t.last_status,
                "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
                "last_run_id": t.last_run_id,
                "script_count": len(scripts),
                "scripts": scripts,
            }
        )
    return {"items": out, "total": total, "page": page, "page_size": page_size}


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: PerfDatabase = Depends(get_perf_db)) -> dict:
    t = db.get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    scripts = db.get_task_scripts(task_id)
    return {
        "id": t.id,
        "project_id": t.project_id,
        "name": t.name,
        "description": t.description,
        "strategy_type": t.strategy_type,
        "duration_seconds": t.duration_seconds,
        "loop_count": t.loop_count,
        "concurrency": t.concurrency,
        "ramp_up_seconds": t.ramp_up_seconds,
        "engine_type": t.engine_type,
        "last_status": t.last_status,
        "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
        "last_run_id": t.last_run_id,
        "scripts": scripts,
    }


@router.put("/tasks/{task_id}")
def update_task(
    task_id: int, body: TaskUpdateIn, db: PerfDatabase = Depends(get_perf_db)
) -> dict:
    t = db.update_task(
        task_id=task_id,
        name=body.name,
        description=body.description,
        strategy_type=body.strategy_type,
        duration_seconds=body.duration_seconds,
        loop_count=body.loop_count,
        concurrency=body.concurrency,
        ramp_up_seconds=body.ramp_up_seconds,
        engine_type=body.engine_type,
        script_items=body.script_items,
    )
    if not t:
        raise HTTPException(404, "任务不存在")
    return {"ok": True}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: PerfDatabase = Depends(get_perf_db)) -> dict:
    if not db.delete_task(task_id):
        raise HTTPException(404, "任务不存在")
    return {"ok": True}


@router.post("/tasks/{task_id}/execute")
def execute_task(task_id: int, db: PerfDatabase = Depends(get_perf_db)) -> dict:
    """启动性能测试任务。"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    run = PerfRun(
        task_id=task.id,
        project_id=task.project_id,
        status="running",
        engine_used=task.engine_type,
        concurrency_actual=task.concurrency,
    )
    run_id = db.create_run(run)
    db.update_task_status(task_id, "running", run_id)

    # 异步加入事件循环后台执行
    executor_mgr = get_executor_manager()
    asyncio.create_task(executor_mgr.execute_task(task_id, run_id, db))

    return {"ok": True, "run_id": run_id}


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: int, db: PerfDatabase = Depends(get_perf_db)) -> dict:
    """终止正在执行的压测任务。"""
    executor_mgr = get_executor_manager()
    success = executor_mgr.stop_run(run_id)
    db.update_run_metrics(run_id, status="stopped")
    return {"ok": success}


# ===== 执行报告 (Runs) 端点 =====
@router.get("/runs")
def list_runs(
    project_id: Optional[int] = Query(None),
    task_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: PerfDatabase = Depends(get_perf_db),
) -> dict:
    items, total = db.list_runs(
        project_id=project_id, task_id=task_id, page=page, page_size=page_size
    )
    return {
        "items": [
            {
                "id": r.id,
                "task_id": r.task_id,
                "project_id": r.project_id,
                "status": r.status,
                "engine_used": r.engine_used,
                "concurrency": r.concurrency_actual,
                "total_samples": r.total_samples,
                "failed_samples": r.failed_samples,
                "error_rate": r.error_rate,
                "avg_tps": r.avg_tps,
                "avg_rt_ms": r.avg_rt_ms,
                "p90_rt_ms": r.p90_rt_ms,
                "p95_rt_ms": r.p95_rt_ms,
                "p99_rt_ms": r.p99_rt_ms,
                "started_at": r.started_at.isoformat(),
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "error_message": r.error_message,
            }
            for r in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/runs/{run_id}")
def get_run_report(run_id: int, db: PerfDatabase = Depends(get_perf_db)) -> dict:
    r = db.get_run(run_id)
    if not r:
        raise HTTPException(404, "报告记录不存在")
    return {
        "id": r.id,
        "task_id": r.task_id,
        "project_id": r.project_id,
        "status": r.status,
        "engine_used": r.engine_used,
        "concurrency": r.concurrency_actual,
        "total_samples": r.total_samples,
        "failed_samples": r.failed_samples,
        "error_rate": r.error_rate,
        "avg_tps": r.avg_tps,
        "avg_rt_ms": r.avg_rt_ms,
        "p90_rt_ms": r.p90_rt_ms,
        "p95_rt_ms": r.p95_rt_ms,
        "p99_rt_ms": r.p99_rt_ms,
        "timeline_metrics": r.timeline_metrics,
        "sampler_summary": r.sampler_summary,
        "started_at": r.started_at.isoformat(),
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "error_message": r.error_message,
    }
