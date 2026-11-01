# -*- coding: utf-8 -*-
"""UI 自动化任务管理路由。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from insight_aitest.modules.ui.backend.automation.deps import get_automation_db
from insight_aitest.modules.ui.backend.automation.models import CaseStatus
from insight_aitest.modules.ui.backend.automation.task_models import (
    TaskStatus,
    TriggerType,
    UiTask,
    UiTaskRun,
)
from insight_aitest.modules.ui.backend.automation.task_runner import execute_task, is_task_running
from insight_aitest.modules.ui.backend.scheduler.manager import _parse_cron, get_ui_scheduler_manager

router = APIRouter(prefix="/automation/tasks", tags=["ui-tasks"])


class CreateTaskRequest(BaseModel):
    project_id: int
    name: str = Field(min_length=1, max_length=100)
    env_id: int
    description: str = ""
    cron_expression: str = ""
    cron_enabled: bool = False


class UpdateTaskRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    env_id: int | None = None
    description: str | None = None
    cron_expression: str | None = None
    cron_enabled: bool | None = None


class ImportCasesRequest(BaseModel):
    case_ids: list[int]


def _task_dict(task: UiTask, case_count: int, env_name: str) -> dict[str, Any]:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "name": task.name,
        "description": task.description,
        "env_id": task.env_id,
        "env_name": env_name,
        "cron_expression": task.cron_expression,
        "cron_enabled": task.cron_enabled,
        "case_count": case_count,
        "last_status": "running" if (task.id and is_task_running(task.id)) else task.last_status,
        "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
        "last_run_id": task.last_run_id,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def _run_dict(run: UiTaskRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "task_id": run.task_id,
        "project_id": run.project_id,
        "env_id": run.env_id,
        "trigger_type": run.trigger_type,
        "status": run.status,
        "total_cases": run.total_cases,
        "passed_cases": run.passed_cases,
        "failed_cases": run.failed_cases,
        "duration_ms": run.duration_ms,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


@router.get("")
def list_tasks(project_id: int = Query(...)) -> list[dict[str, Any]]:
    """获取指定项目下的所有 UI 自动化任务。"""
    db = get_automation_db()
    tasks = db.list_tasks(project_id)
    case_counts = db.get_task_case_counts(project_id)
    envs = {e.id: e.name for e in db.list_envs(project_id)}

    return [
        _task_dict(t, case_counts.get(int(t.id), 0), envs.get(t.env_id, f"环境 #{t.env_id}"))
        for t in tasks
    ]


@router.post("", status_code=201)
def create_task(req: CreateTaskRequest) -> dict[str, Any]:
    """创建新任务。"""
    db = get_automation_db()
    # 校验环境有效性
    env = db.get_env(req.env_id)
    if env is None or env.project_id != req.project_id:
        raise HTTPException(400, "选定的环境不存在或不属于该项目")

    # 校验 cron 语法
    cron_expr = req.cron_expression.strip()
    if req.cron_enabled:
        if not cron_expr:
            raise HTTPException(400, "启用定时调度时必须输入 Cron 表达式")
        try:
            _parse_cron(cron_expr)
        except ValueError as e:
            raise HTTPException(400, f"无效的 Cron 表达式：{e}")

    task = db.create_task(
        project_id=req.project_id,
        name=req.name,
        env_id=req.env_id,
        description=req.description,
        cron_expression=cron_expr,
        cron_enabled=req.cron_enabled,
    )

    if task.cron_enabled and cron_expr and task.id:
        get_ui_scheduler_manager().add_task_job(task.id, cron_expr)

    return _task_dict(task, 0, env.name)


@router.get("/{task_id}")
def get_task(task_id: int) -> dict[str, Any]:
    """获取任务详情。"""
    db = get_automation_db()
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    count = db.count_task_cases(task_id)
    env = db.get_env(task.env_id)
    env_name = env.name if env else f"环境 #{task.env_id}"
    return _task_dict(task, count, env_name)


@router.put("/{task_id}")
def update_task(task_id: int, req: UpdateTaskRequest) -> dict[str, Any]:
    """修改任务配置。"""
    db = get_automation_db()
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")

    fields: dict[str, Any] = {}
    if req.name is not None:
        fields["name"] = req.name.strip()
    if req.description is not None:
        fields["description"] = req.description.strip()
    if req.env_id is not None:
        env = db.get_env(req.env_id)
        if env is None or env.project_id != task.project_id:
            raise HTTPException(400, "选定的环境不存在或不属于该项目")
        fields["env_id"] = req.env_id

    cron_expr = req.cron_expression.strip() if req.cron_expression is not None else task.cron_expression
    cron_enabled = req.cron_enabled if req.cron_enabled is not None else task.cron_enabled

    if cron_enabled:
        if not cron_expr:
            raise HTTPException(400, "启用定时调度时必须输入 Cron 表达式")
        try:
            _parse_cron(cron_expr)
        except ValueError as e:
            raise HTTPException(400, f"无效的 Cron 表达式：{e}")

    if req.cron_expression is not None:
        fields["cron_expression"] = cron_expr
    if req.cron_enabled is not None:
        fields["cron_enabled"] = cron_enabled

    updated = db.update_task(task_id, **fields)
    if updated is None:
        raise HTTPException(404, "更新失败，任务不存在")

    # 同步定时器
    scheduler = get_ui_scheduler_manager()
    if updated.cron_enabled and updated.cron_expression:
        scheduler.add_task_job(task_id, updated.cron_expression)
    else:
        scheduler.remove_task_job(task_id)

    count = db.count_task_cases(task_id)
    env = db.get_env(updated.env_id)
    env_name = env.name if env else f"环境 #{updated.env_id}"
    return _task_dict(updated, count, env_name)


@router.delete("/{task_id}")
def delete_task(task_id: int) -> dict[str, bool]:
    """删除任务。"""
    db = get_automation_db()
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    get_ui_scheduler_manager().remove_task_job(task_id)
    db.delete_task(task_id)
    return {"ok": True}


@router.get("/{task_id}/cases")
def list_task_cases(task_id: int) -> list[dict[str, Any]]:
    """获取任务已关联的用例列表。"""
    db = get_automation_db()
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")

    pairs = db.get_task_cases(task_id)
    return [
        {
            "id": tc.id,
            "case_id": c.id,
            "title": c.title,
            "category": c.category_path or "未分类",
            "category_path": c.category_path or "",
            "site": c.site,
            "status": c.status,
            "order_no": tc.order_no,
            "created_at": tc.created_at.isoformat(),
        }
        for tc, c in pairs
    ]


@router.get("/{task_id}/importable-cases")
def get_importable_cases(task_id: int, project_id: int = Query(...)) -> dict[str, Any]:
    """获取可导入到该任务的用例列表。

    规则：
    1. 仅展示同项目下 status == 'implemented'（已实现）的用例；
    2. 按分类/目录组织，空目录（不含已实现用例）不展示；
    3. 标记已被该任务导入的用例，前端置灰禁止重复导入。
    """
    db = get_automation_db()
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")

    # 查同项目下所有已实现的用例
    all_implemented, _ = db.list_cases(project_id=project_id, status=CaseStatus.IMPLEMENTED, page_size=200)
    already_ids = db.get_task_case_ids(task_id)

    # 按 category_path 聚合（空目录自然不会被添加）
    categories_map: dict[str, list[dict[str, Any]]] = {}
    for c in all_implemented:
        cat = c.category_path.strip() if c.category_path and c.category_path.strip() else "未分类"
        if cat not in categories_map:
            categories_map[cat] = []
        categories_map[cat].append(
            {
                "id": c.id,
                "title": c.title,
                "site": c.site,
                "category": cat,
                "category_path": cat,
                "status": c.status,
                "already_imported": c.id in already_ids,
            }
        )

    categories = [
        {"name": cat, "cases": case_list}
        for cat, case_list in sorted(categories_map.items(), key=lambda x: (x[0] == "未分类", x[0]))
    ]

    return {
        "categories": categories,
        "total_implemented": len(all_implemented),
        "already_imported_count": len(already_ids),
    }


@router.post("/{task_id}/cases/import")
def import_cases_to_task(task_id: int, req: ImportCasesRequest) -> dict[str, Any]:
    """导入用例到任务（同一任务、同一用例防重）。"""
    db = get_automation_db()
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")

    imported = db.import_cases_to_task(task_id, req.case_ids)
    return {"imported_count": imported, "total_cases": db.count_task_cases(task_id)}


@router.delete("/{task_id}/cases/{case_id}")
def remove_case_from_task(task_id: int, case_id: int) -> dict[str, bool]:
    """从任务中移除指定用例。"""
    db = get_automation_db()
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")

    removed = db.remove_task_case(task_id, case_id)
    return {"ok": removed}


@router.post("/{task_id}/run")
def trigger_task_run(task_id: int) -> dict[str, Any]:
    """手动立即触发任务执行。"""
    try:
        run = execute_task(task_id, trigger_type=TriggerType.MANUAL)
        return {"run_id": run.id, "status": run.status}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.get("/{task_id}/runs")
def list_task_runs(task_id: int, limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
    """获取任务的历史执行记录。"""
    db = get_automation_db()
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    runs = db.list_task_runs(task_id, limit=limit)
    return [_run_dict(r) for r in runs]


@router.get("/runs/{run_id}/report")
def get_task_run_report(run_id: int) -> dict[str, Any]:
    """获取指定任务执行批次的测试报告。"""
    db = get_automation_db()
    run = db.get_task_run(run_id)
    if run is None:
        raise HTTPException(404, "执行记录不存在")

    task = db.get_task(run.task_id)
    env = db.get_env(run.env_id)

    try:
        summary_items = json.loads(run.summary_json) if run.summary_json else []
    except Exception:
        summary_items = []

    return {
        "run": _run_dict(run),
        "task_name": task.name if task else f"任务 #{run.task_id}",
        "env_name": env.name if env else f"环境 #{run.env_id}",
        "summary": summary_items,
    }
