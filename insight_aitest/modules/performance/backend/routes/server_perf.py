# -*- coding: utf-8 -*-
"""服务端 JMeter 性能测试路由（脚本管理、AI 智能生成、预览、调试、下载、任务组合与执行报告）。"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from logzero import logger
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
from insight_aitest.modules.performance.backend.services.jmx_parser import JmxParser

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
    plan_description: Optional[str] = None
    jmx_content: Optional[str] = None
    config: Optional[dict] = None


class ScriptDebugIn(BaseModel):
    jmx_content: str
    base_url: str = ""
    global_vars: dict = {}


class ScriptRunIn(BaseModel):
    engine_type: str = "jmeter_cli"
    env_id: Optional[int] = None
    env_base_url: str = ""
    exec_mode: str = "local"
    slave_hosts: str = ""


class TaskCreateIn(BaseModel):
    project_id: int
    name: str
    description: str = ""
    strategy_type: str = "duration"
    duration_seconds: int = 60
    loop_count: int = 1
    concurrency: int = 10
    ramp_up_seconds: int = 5
    engine_type: str = "jmeter_cli"
    exec_mode: str = "local"
    slave_hosts: str = ""
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
    exec_mode: Optional[str] = None
    slave_hosts: Optional[str] = None
    script_items: Optional[list[dict]] = None


class SlaveNodeIn(BaseModel):
    name: str
    host: str
    port: int = 1099
    project_id: Optional[int] = None
    description: str = ""


class SlaveNodeTestPingIn(BaseModel):
    host: str
    port: int = 1099


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
    config = dict(body.config or {})
    if body.jmx_content and not config.get("steps"):
        try:
            parsed = JmxParser.parse(body.jmx_content)
            config["steps"] = parsed.get("steps", [])
            if "concurrency" not in config:
                config["concurrency"] = parsed.get("concurrency", 1)
            if "duration" not in config:
                config["duration"] = parsed.get("duration", 60)
        except Exception as exc:
            logger.warning(f"自动解析 JMX 链路失败: {exc}")

    script = PerfScript(
        project_id=body.project_id,
        name=body.name,
        description=body.description,
        plan_description=body.plan_description,
        config=config,
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

    config = dict(s.config or {})
    steps = config.get("steps") or []
    if not steps and s.jmx_content:
        try:
            parsed = JmxParser.parse(s.jmx_content)
            steps = parsed.get("steps", [])
            config["steps"] = steps
            if "concurrency" not in config:
                config["concurrency"] = parsed.get("concurrency", 1)
            if "duration" not in config:
                config["duration"] = parsed.get("duration", 60)
            db.update_script(s.id, config=config)
        except Exception as exc:
            logger.warning(f"获取脚本详情时解析 JMX 失败: {exc}")

    return {
        "id": s.id,
        "project_id": s.project_id,
        "name": s.name,
        "description": s.description,
        "plan_description": s.plan_description,
        "config": config,
        "parsed_steps": steps,
        "jmx_content": s.jmx_content,
        "asset_ids": s.asset_ids,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


@router.put("/scripts/{script_id}")
def update_script(
    script_id: int, body: ScriptUpdateIn, db: PerfDatabase = Depends(get_perf_db)
) -> dict:
    new_config = body.config
    if body.jmx_content:
        try:
            parsed = JmxParser.parse(body.jmx_content)
            cfg = dict(new_config or {})
            cfg["steps"] = parsed.get("steps", [])
            if "concurrency" not in cfg:
                cfg["concurrency"] = parsed.get("concurrency", 1)
            if "duration" not in cfg:
                cfg["duration"] = parsed.get("duration", 60)
            new_config = cfg
        except Exception as exc:
            logger.warning(f"更新脚本解析 JMX 失败: {exc}")

    s = db.update_script(
        script_id,
        name=body.name,
        description=body.description,
        plan_description=body.plan_description,
        jmx_content=body.jmx_content,
        config=new_config,
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
    raw_name = (s.name or f"script_{script_id}").strip()
    safe_filename = f"{raw_name}.jmx"
    quoted_name = quote(safe_filename)
    content_bytes = (s.jmx_content or "").encode("utf-8")
    return Response(
        content=content_bytes,
        media_type="application/xml; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="script_{script_id}.jmx"; filename*=UTF-8\'\'{quoted_name}',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.post("/scripts/{script_id}/run")
async def run_script(
    script_id: int,
    body: Optional[ScriptRunIn] = None,
    db: PerfDatabase = Depends(get_perf_db),
) -> dict:
    """启动单个性能测试场景运行，按照脚本原生配置执行并实时产出控制台日志与 JTL 报告。"""
    script = db.get_script(script_id)
    if not script:
        raise HTTPException(404, "脚本不存在")

    engine_type = body.engine_type if body else "jmeter_cli"
    exec_mode = body.exec_mode if body else "local"
    slave_hosts = (body.slave_hosts if body else "") or ""
    env_base_url = (body.env_base_url.strip() if body and body.env_base_url else "")
    if not env_base_url and body and body.env_id:
        try:
            from insight_aitest.modules.ui.backend.automation.deps import get_automation_db

            auto_db = get_automation_db()
            env_obj = auto_db.get_env(body.env_id)
            if env_obj and env_obj.base_url:
                env_base_url = env_obj.base_url.strip()
        except Exception:
            pass

    actual_concurrency = 1
    if script.config and isinstance(script.config, dict):
        actual_concurrency = script.config.get("concurrency", 1)

    run = PerfRun(
        task_id=0,
        script_id=script_id,
        project_id=script.project_id,
        status="running",
        engine_used=engine_type,
        exec_mode=exec_mode,
        slave_hosts=slave_hosts,
        concurrency_actual=actual_concurrency,
    )
    run_id = db.create_run(run)

    executor_mgr = get_executor_manager()
    asyncio.create_task(
        executor_mgr.execute_script(
            script_id=script_id,
            run_id=run_id,
            perf_db=db,
            engine_type=engine_type,
            env_base_url=env_base_url,
            exec_mode=exec_mode,
            slave_hosts=slave_hosts,
        )
    )
    return {"ok": True, "run_id": run_id}


@router.get("/scripts/{script_id}/runs")
def list_script_runs(
    script_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: PerfDatabase = Depends(get_perf_db),
) -> dict:
    """获取指定场景的历史执行记录列表。"""
    items, total = db.list_runs(script_id=script_id, page=page, page_size=page_size)
    return {
        "items": [
            {
                "id": r.id,
                "script_id": r.script_id,
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
        exec_mode=body.exec_mode,
        slave_hosts=body.slave_hosts,
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
                "exec_mode": getattr(t, "exec_mode", "local") or "local",
                "slave_hosts": getattr(t, "slave_hosts", "") or "",
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
        "exec_mode": getattr(t, "exec_mode", "local") or "local",
        "slave_hosts": getattr(t, "slave_hosts", "") or "",
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
        exec_mode=body.exec_mode,
        slave_hosts=body.slave_hosts,
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
async def execute_task(task_id: int, db: PerfDatabase = Depends(get_perf_db)) -> dict:
    """启动性能测试任务。"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    run = PerfRun(
        task_id=task.id,
        project_id=task.project_id,
        status="running",
        engine_used=task.engine_type,
        exec_mode=getattr(task, "exec_mode", "local") or "local",
        slave_hosts=getattr(task, "slave_hosts", "") or "",
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
    """终止正在执行的测试场景或压测任务。"""
    executor_mgr = get_executor_manager()
    success = executor_mgr.stop_run(run_id)
    if not success:
        db.update_run_metrics(run_id, status="stopped")
    return {"ok": True}


# ===== 执行报告 (Runs) 端点 =====
@router.get("/runs")
def list_runs(
    project_id: Optional[int] = Query(None),
    task_id: Optional[int] = Query(None),
    script_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: PerfDatabase = Depends(get_perf_db),
) -> dict:
    items, total = db.list_runs(
        project_id=project_id, task_id=task_id, script_id=script_id, page=page, page_size=page_size
    )
    return {
        "items": [
            {
                "id": r.id,
                "task_id": r.task_id,
                "script_id": r.script_id,
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
        "script_id": r.script_id,
        "project_id": r.project_id,
        "status": r.status,
        "engine_used": r.engine_used,
        "exec_mode": getattr(r, "exec_mode", "local") or "local",
        "slave_hosts": getattr(r, "slave_hosts", "") or "",
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
        "jtl_rows": r.jtl_rows or [],
        "jtl_tree": [
            node for node in (r.jtl_rows or [])
            if node.get("is_transaction") or not any(
                node in parent.get("children", []) for parent in (r.jtl_rows or []) if parent.get("is_transaction")
            )
        ] if any(row.get("children") for row in (r.jtl_rows or [])) else None,
        "jtl_content": r.jtl_content or "",
        "console_output": r.console_output or "",
        "started_at": r.started_at.isoformat(),
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "error_message": r.error_message,
    }


@router.get("/runs/{run_id}/stream")
async def stream_run_logs(run_id: int, db: PerfDatabase = Depends(get_perf_db)):
    """SSE 实时输出运行控制台日志流与完成状态。"""
    executor_mgr = get_executor_manager()
    existing_logs, q = executor_mgr.subscribe_logs(run_id)

    async def event_generator():
        try:
            for line in existing_logs:
                payload = json.dumps({"type": "log", "text": line}, ensure_ascii=False)
                yield f"data: {payload}\n\n"

            # 检查是否已在数据库中进入终态
            r = db.get_run(run_id)
            if r and r.status in ("completed", "failed", "stopped"):
                done_payload = json.dumps({
                    "type": "done",
                    "status": r.status,
                    "run_id": run_id,
                    "error": r.error_message,
                }, ensure_ascii=False)
                yield f"data: {done_payload}\n\n"
                return

            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=2.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") == "done":
                        break
                except asyncio.TimeoutError:
                    r_check = db.get_run(run_id)
                    if r_check and r_check.status in ("completed", "failed", "stopped"):
                        done_payload = json.dumps({
                            "type": "done",
                            "status": r_check.status,
                            "run_id": run_id,
                            "error": r_check.error_message,
                        }, ensure_ascii=False)
                        yield f"data: {done_payload}\n\n"
                        break
                    yield ": ping\n\n"
        finally:
            executor_mgr.unsubscribe_logs(run_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ===== 分布式 Slave 从机节点管理端点 =====
@router.get("/slave-nodes")
def list_slave_nodes_endpoint(
    project_id: Optional[int] = Query(None),
    db: PerfDatabase = Depends(get_perf_db),
) -> dict:
    nodes = db.list_slave_nodes(project_id=project_id)
    return {
        "items": [
            {
                "id": n.id,
                "project_id": n.project_id,
                "name": n.name,
                "host": n.host,
                "port": n.port,
                "status": n.status,
                "description": n.description,
                "last_heartbeat_at": n.last_heartbeat_at.isoformat() if n.last_heartbeat_at else None,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in nodes
        ]
    }


@router.post("/slave-nodes")
def create_slave_node_endpoint(
    body: SlaveNodeIn,
    db: PerfDatabase = Depends(get_perf_db),
) -> dict:
    import socket
    from datetime import datetime
    from insight_aitest.modules.performance.backend.persistence.models import PerfSlaveNode

    host = body.host.strip()
    port = body.port or 1099

    # 创建时同步进行一次 TCP 端口连通探测
    is_online = False
    try:
        with socket.create_connection((host, port), timeout=2.5):
            is_online = True
    except Exception:
        is_online = False

    node = PerfSlaveNode(
        project_id=body.project_id,
        name=body.name.strip(),
        host=host,
        port=port,
        status="online" if is_online else "offline",
        last_heartbeat_at=datetime.now() if is_online else None,
        description=body.description,
    )
    nid = db.create_slave_node(node)
    return {"ok": True, "id": nid, "status": node.status}


@router.delete("/slave-nodes/{node_id}")
def delete_slave_node_endpoint(
    node_id: int,
    db: PerfDatabase = Depends(get_perf_db),
) -> dict:
    if not db.delete_slave_node(node_id):
        raise HTTPException(404, "从机节点不存在")
    return {"ok": True}


@router.post("/slave-nodes/{node_id}/ping")
def ping_slave_node_endpoint(
    node_id: int,
    db: PerfDatabase = Depends(get_perf_db),
) -> dict:
    """连通性探测：尝试对从机 RMI 端口建立 TCP 连接。"""
    import socket

    node = db.get_slave_node(node_id)
    if not node:
        raise HTTPException(404, "从机节点不存在")

    host = node.host.strip()
    port = node.port or 1099
    is_online = False
    err_msg = ""

    try:
        with socket.create_connection((host, port), timeout=3.0):
            is_online = True
    except Exception as exc:
        is_online = False
        err_msg = str(exc)

    new_status = "online" if is_online else "offline"
    db.update_slave_node(
        node_id,
        status=new_status,
        last_heartbeat_at=datetime.now() if is_online else None,
    )

    return {
        "ok": is_online,
        "status": new_status,
        "host": host,
        "port": port,
        "error": err_msg,
    }


@router.post("/slave-nodes/test-ping")
def test_ping_slave_node_endpoint(
    body: SlaveNodeTestPingIn,
) -> dict:
    """对尚未保存或录入的从机 IP/端口进行实时连通性探测。"""
    import socket

    host = body.host.strip()
    port = body.port or 1099
    if not host:
        raise HTTPException(400, "主机地址不能为空")

    is_online = False
    err_msg = ""

    try:
        with socket.create_connection((host, port), timeout=3.0):
            is_online = True
    except Exception as exc:
        is_online = False
        err_msg = str(exc)

    return {
        "ok": is_online,
        "host": host,
        "port": port,
        "error": err_msg,
    }


@router.delete("/runs/{run_id}")
def delete_run_record(run_id: int, db: PerfDatabase = Depends(get_perf_db)) -> dict:
    if not db.delete_run(run_id):
        raise HTTPException(404, "记录不存在")
    return {"ok": True}
