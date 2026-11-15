# -*- coding: utf-8 -*-
"""Remote Mobile MCP HTTP 端点（Streamable HTTP / JSON-RPC 2.0）。"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, Response

from insight_aitest.modules.mobile.backend.automation.mcp_server import dispatch_mcp_message

router = APIRouter(tags=["mobile-mcp"])


def _extract_bearer(authorization: str | None, query_token: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return (query_token or "").strip()


@router.get("/mcp")
def mcp_info() -> dict:
    return {
        "name": "insight-mobile-mcp",
        "transport": "streamable-http",
        "protocolVersion": "2024-11-05",
    }


@router.post("/mcp")
async def mcp_endpoint(
    request: Request,
    authorization: str | None = Header(default=None),
    token: str | None = None,
):
    session_token = _extract_bearer(authorization, token)
    if not session_token:
        raise HTTPException(401, "缺少 MCP 会话 Bearer Token")

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(400, f"无效的 JSON-RPC 请求体: {e}") from e

    try:
        res = dispatch_mcp_message(payload, session_token)
    except PermissionError as e:
        raise HTTPException(401, str(e)) from e

    if res is None:
        return Response(status_code=202)
    return res
