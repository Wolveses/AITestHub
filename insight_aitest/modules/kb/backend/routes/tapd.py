# -*- coding: utf-8 -*-
"""TAPD 缺陷同步路由。

提供：
1. GET /tapd: 查询配置状态与同步进度
2. POST /tapd/sync: 触发后台同步
3. GET /tapd/progress: 查询同步进度
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from insight_aitest.modules.kb.backend.services.tapd_sync import (
    sync_progress,
    sync_workspace,
    try_acquire_sync,
)
from insight_aitest.platform.services.kb.deps import get_llm_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tapd", tags=["kb-tapd"])


class SyncIn(BaseModel):
    workspace_id: str
    project_id: int
    backfill_days: int | None = None


@router.get("", response_model=dict[str, Any])
def get_tapd_status() -> dict[str, Any]:
    """TAPD 集成状态：是否已配置凭证、默认回溯天数与当前同步进度。"""
    cfg = get_llm_config()
    return {
        "configured": bool(cfg.tapd_auth_user and cfg.tapd_auth_pwd),
        "backfill_days": cfg.tapd_backfill_days,
        "progress": sync_progress(),
    }


@router.post("/sync", status_code=202, response_model=dict[str, Any])
def start_sync(body: SyncIn) -> dict[str, Any]:
    """启动 TAPD 缺陷同步（后台线程执行，立即返回）。"""
    workspace_id = (body.workspace_id or "").strip()
    if not workspace_id:
        raise HTTPException(400, "workspace_id 不能为空")
    cfg = get_llm_config()
    if not (cfg.tapd_auth_user and cfg.tapd_auth_pwd):
        raise HTTPException(400, "TAPD 凭证未配置")
    # 先原子抢占执行权，再起线程，避免并发 POST 同时通过检查
    if not try_acquire_sync():
        raise HTTPException(409, "TAPD 同步正在进行中")

    threading.Thread(
        target=sync_workspace,
        args=(workspace_id, body.project_id, body.backfill_days, True),
        daemon=True,
    ).start()
    return {"started": True}


@router.get("/progress", response_model=dict[str, Any])
def get_progress() -> dict[str, Any]:
    return sync_progress()
