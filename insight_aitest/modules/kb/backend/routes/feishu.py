# -*- coding: utf-8 -*-
"""飞书知识库集成路由。

提供：
1. GET /spaces: 获取飞书知识库空间列表
2. POST /sync: 主动同步指定飞书知识库空间
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from insight_aitest.modules.kb.backend.services.feishu_sync import FeishuSyncService
from insight_aitest.platform.services.feishu import FeishuClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feishu", tags=["kb-feishu"])


class SyncSpaceIn(BaseModel):
    space_id: str
    project_id: int | None = None


@router.get("/spaces", response_model=list[dict[str, Any]])
async def list_spaces() -> list[dict[str, Any]]:
    """获取飞书应用有权限访问的知识库空间列表。"""
    client = FeishuClient()
    if not client.is_configured():
        # 未配置凭证时不再返回空列表（会被前端误判为"无已授权空间"）
        raise HTTPException(
            400,
            "尚未配置飞书应用凭证，请设置 feishu_app_id / feishu_app_secret"
            "（写入 ~/.insight_eye/llm_config.json，或设置环境变量"
            " INSIGHT_EYE_AI_FEISHU_APP_ID / INSIGHT_EYE_AI_FEISHU_APP_SECRET）",
        )
    try:
        return client.list_spaces()
    except Exception as e:
        logger.error(f"获取飞书知识库空间失败: {e}")
        raise HTTPException(500, f"获取飞书空间失败: {e}")


@router.post("/sync", response_model=dict[str, Any])
async def sync_space(body: SyncSpaceIn) -> dict[str, Any]:
    """主动同步飞书知识库空间到本地。"""
    client = FeishuClient()
    if not client.is_configured():
        raise HTTPException(400, "尚未配置飞书应用凭证 (feishu_app_id / feishu_app_secret)")

    sync_service = FeishuSyncService(client)
    try:
        result = sync_service.sync_space(body.space_id, project_id=body.project_id)
        return {"ok": True, "result": result}
    except Exception as e:
        logger.error(f"同步飞书知识库空间失败: {e}", exc_info=True)
        raise HTTPException(500, f"同步失败: {e}")

