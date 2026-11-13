# -*- coding: utf-8 -*-
"""本地 Agent 使用的 MCP Bearer Token 管理。

安全约定：
- 只存 sha256 哈希，明文仅在创建/生成文案时返回一次；
- 默认 30 天有效，可随时吊销；
- 日志与接口列表只回显前缀（``ins_xxxxxxxx••••``）。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from logzero import logger

from insight_aitest.modules.ui.backend.automation.deps import get_automation_db
from insight_aitest.modules.ui.backend.automation.models import McpToken

TOKEN_PREFIX = "ins_agent_"
DEFAULT_TTL_DAYS = 30


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").strip().encode("utf-8")).hexdigest()


def mask_token(token: str) -> str:
    token = token or ""
    return token[:14] + "••••" if len(token) > 14 else token


def create_token(project_id: int, name: str = "本地 Agent") -> tuple[str, McpToken]:
    """创建 Token，返回 (明文, 记录)。明文不会再次可查。"""
    plain = TOKEN_PREFIX + secrets.token_urlsafe(32)
    db = get_automation_db()
    row = db.create_mcp_token(
        project_id=int(project_id),
        name=name or "本地 Agent",
        token_hash=hash_token(plain),
        token_prefix=plain[:10],
        expires_at=datetime.now() + timedelta(days=DEFAULT_TTL_DAYS),
    )
    logger.info("已创建 MCP Token：project=%s id=%s", project_id, row.id)
    return plain, row


def verify_token(plain: str) -> McpToken | None:
    """校验 Bearer Token；无效/过期/吊销返回 None。"""
    if not plain or not plain.strip():
        return None
    db = get_automation_db()
    row = db.get_mcp_token_by_hash(hash_token(plain))
    if row is None:
        return None
    now = datetime.now()
    if row.revoked_at is not None:
        return None
    if row.expires_at is not None and row.expires_at < now:
        return None
    try:
        db.touch_mcp_token(int(row.id))
    except Exception:
        pass
    return row


def revoke_token(token_id: int, project_id: int) -> bool:
    return get_automation_db().revoke_mcp_token(int(token_id), int(project_id))


def list_tokens(project_id: int) -> list[dict]:
    now = datetime.now()
    out = []
    for row in get_automation_db().list_mcp_tokens(int(project_id)):
        expired = row.expires_at is not None and row.expires_at < now
        out.append(
            {
                "id": row.id,
                "name": row.name,
                "prefix": (row.token_prefix or "") + "••••",
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "revoked": row.revoked_at is not None,
                "expired": expired,
                "active": row.revoked_at is None and not expired,
            }
        )
    return out
