# -*- coding: utf-8 -*-
"""平台通用 Streamable HTTP MCP 挂载辅助工具。

封装 Host 重绑定放行、子路径归一与无 307 重定向挂载，供各业务模块复用。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Mount, Route


class RootPathShim:
    """将任意前缀/子路径统一改写为 ``/``，避免内部 StreamableHTTP 路由错配或 307 重定向。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") in ("http", "websocket"):
            scope = dict(scope)
            scope["path"] = "/"
        await self.app(scope, receive, send)


def build_streamable_mcp_app(
    server: MCPServer,
    wrap_middleware: Callable[[Any], Any],
    *,
    json_response: bool = False,
) -> Any:
    """构建带自定义鉴权中间件的 MCP Streamable HTTP ASGI 应用。"""
    inner = server.streamable_http_app(
        streamable_http_path="/",
        json_response=json_response,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return RootPathShim(wrap_middleware(inner))


def mount_streamable_mcp(app: Any, paths: Sequence[str], handler: Any) -> None:
    """将 MCP ASGI 应用同时挂载到精确路径与子路径前缀。"""
    for p in paths:
        norm = "/" + p.strip("/")
        app.router.routes.append(Route(norm, endpoint=handler))
        app.router.routes.append(Mount(norm, app=handler))
