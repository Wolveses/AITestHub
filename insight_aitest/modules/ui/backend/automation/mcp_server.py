# -*- coding: utf-8 -*-
"""平台 MCP 服务：把「契约 / 环境 / 用例 / 校验 / 试跑 / 入库」暴露给本地 Agent。

挂载点：``/mcp``（Bearer Token 鉴权，Token 由平台前端生成文案时创建）。
工具清单（与设计 v1.1 一致）：
- ``contract.get`` / ``env.get`` / ``case.get`` / ``example.get``
- ``script.validate`` / ``script.dry_run`` / ``script.submit``
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar

from logzero import logger
from mcp.server.mcpserver import MCPServer
from starlette.responses import JSONResponse

from insight_aitest.modules.ui.backend.automation import authoring_service as svc
from insight_aitest.modules.ui.backend.automation import contract, example_service, mcp_tokens
from insight_aitest.modules.ui.backend.automation.current_env import resolve_current_env
from insight_aitest.modules.ui.backend.automation.deps import get_automation_db

_current_project: ContextVar[int] = ContextVar("mcp_project_id", default=0)
_current_owner: ContextVar[str] = ContextVar("mcp_owner", default="")
_current_base: ContextVar[str] = ContextVar("mcp_base_url", default="")

_server: MCPServer | None = None


def _db():
    return get_automation_db()


def _project_id() -> int:
    pid = _current_project.get()
    if not pid:
        raise ValueError("PERMISSION_DENIED：未认证，请在 MCP 请求头携带 Authorization: Bearer <token>")
    return pid


def _owner() -> str:
    return _current_owner.get() or "anonymous"


def _case_or_none(case_id: int):
    db = _db()
    case = svc.resolve_case(db, case_id, _project_id())
    if case is None:
        return db, None, svc.fail(
            "CASE_NOT_FOUND", f"用例 {case_id} 不存在或不属于当前 Token 的项目"
        )
    return db, case, None


def _build_server() -> MCPServer:
    server = MCPServer(
        name="insight-aitest",
        title="Insight-AITest UI 自动化脚本契约",
        description=(
            "UI 自动化脚本「本地编写 + 平台校验入库」服务。"
            "务必按 contract.get → env.get → case.get → example.get → script.validate → "
            "script.dry_run → script.submit 的顺序调用。"
        ),
        version="1.0.0",
    )

    @server.tool(
        name="contract.get",
        description=(
            "【第一步】获取用例的编写契约：用例快照（含 case_rev）、现有脚本版本、当前环境摘要、"
            "项目已有 pages/common 资产清单，以及文件规则/import 白名单/错误码。"
            "开始写脚本前必须先调用，按 rules 编写。"
        ),
    )
    def contract_get(case_id: int) -> dict:
        db, case, err = _case_or_none(case_id)
        if err:
            return err
        env = resolve_current_env(db, int(case.project_id))
        payload = contract.contract_payload(case, env)
        payload["ok"] = True
        return payload

    @server.tool(
        name="env.get",
        description=(
            "【第二步】获取当前应用环境的详情与认证信息：base_url、entry_url、auth.mode、"
            "header 名称/值，以及一次性 storageState 下载地址（5 分钟有效、只能下载一次）。"
            "探索阶段用它给 Playwright MCP 注入登录态；脚本里不要写死 token。"
        ),
    )
    async def env_get(case_id: int) -> dict:
        db, case, err = _case_or_none(case_id)
        if err:
            return err
        payload = await asyncio.to_thread(svc.env_payload, db, case)
        base = _current_base.get()
        auth = payload.get("auth") or {}
        rel = auth.get("storage_state_url") or ""
        if payload.get("ok") and base and rel.startswith("/"):
            auth["storage_state_url"] = base + rel
        return payload

    @server.tool(
        name="case.get",
        description=(
            "【第三步】获取用例详情（标题/前置/步骤/预期/端/参数），以及 case_rev 与 script.version —— "
            "提交时分别作为 expect_case_rev / expect_script_version 原样传回。"
        ),
    )
    def case_get(case_id: int) -> dict:
        _, case, err = _case_or_none(case_id)
        if err:
            return err
        payload = svc.case_payload(case)
        payload["ok"] = True
        return payload

    @server.tool(
        name="example.get",
        description=(
            "【第四步】获取项目内可照抄的经验（只读，可多次调用）：硬规则 8 条、平台已验证的 UI 坑、"
            "本项目错题库（失败+解决方案）、同目录已验证脚本的动作片段、已知 hash 路由、"
            "pages/common 的类与方法签名、最小可运行骨架。"
            "在 case.get 之后、开始浏览器探索之前调用，优先复用其中路由与定位写法，再补充探索差异。"
            "输出已脱敏；无历史脚本时 examples 为空但 template 仍可用。"
        ),
    )
    def example_get(
        case_id: int, max_examples: int = 3, include_assets: bool = True
    ) -> dict:
        db, case, err = _case_or_none(case_id)
        if err:
            return err
        payload = example_service.build_example_payload(
            case, db, max_examples=max_examples, include_assets=include_assets
        )
        payload["ok"] = True
        return payload

    @server.tool(
        name="script.validate",
        description=(
            "【校验】提交完整文件集合做 L1（AST/白名单/硬编码/token）+ L2（pytest --collect-only）校验。"
            "files 为 [{path, content}]，path 只允许 case.py、pages/<name>.py、common/<name>.py。"
            "通过后返回 source_hash（30 分钟内可用于 dry_run/submit）；失败返回 violations[].code 与 fix。"
        ),
    )
    async def script_validate(case_id: int, files: list[dict]) -> dict:
        db, case, err = _case_or_none(case_id)
        if err:
            return err
        return await asyncio.to_thread(svc.validate, db, case, files)

    @server.tool(
        name="script.dry_run",
        description=(
            "【试跑】在平台 staging 目录用当前环境真实执行一次脚本（不污染正式资产、不写执行记录）。"
            "前置条件：对同一 files 调用过 script.validate 且 source_hash 一致（30 分钟内）。"
            "同一用例 60 秒内只允许一次。通过后 24 小时内可 submit。"
        ),
    )
    async def script_dry_run(case_id: int, files: list[dict], source_hash: str) -> dict:
        db, case, err = _case_or_none(case_id)
        if err:
            return err
        owner = _owner()
        if not svc.acquire_lease(db, case, owner):
            return svc.fail("BUSY", "该用例正被其他本地 Agent 操作，请稍后重试")
        try:
            return await asyncio.to_thread(svc.dry_run, db, case, files, source_hash)
        finally:
            svc.release_lease(db, case)

    @server.tool(
        name="script.submit",
        description=(
            "【入库】把已通过 dry_run 的脚本写入平台：归档旧版本、版本号 +1、更新用例状态为已实现。"
            "三守卫：files 的 source_hash、expect_case_rev（case.get 返回）、expect_script_version 必须与平台一致；"
            "pages/common 覆盖需 force_assets=true（覆盖前自动备份）。成功后用户可在平台直接执行。"
        ),
    )
    async def script_submit(
        case_id: int,
        files: list[dict],
        source_hash: str,
        expect_case_rev: str,
        expect_script_version: int,
        params_schema: list | None = None,
        force_assets: bool = False,
    ) -> dict:
        db, case, err = _case_or_none(case_id)
        if err:
            return err
        owner = _owner()
        if not svc.acquire_lease(db, case, owner):
            return svc.fail("BUSY", "该用例正被其他本地 Agent 操作，请稍后重试")
        try:
            return await asyncio.to_thread(
                svc.submit,
                db,
                case,
                files,
                source_hash,
                expect_case_rev,
                expect_script_version,
                params_schema,
                force_assets,
            )
        finally:
            svc.release_lease(db, case)

    return server


def get_mcp_server() -> MCPServer:
    global _server
    if _server is None:
        _server = _build_server()
    return _server


class BearerAuthMiddleware:
    """对 MCP 的 HTTP 请求做静态 Bearer Token 校验，并把项目上下文写入 ContextVar。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        raw = ""
        host = ""
        for key, value in scope.get("headers") or []:
            if key == b"authorization":
                raw = value.decode("latin-1")
            elif key == b"host":
                host = value.decode("latin-1")
        token = raw[7:].strip() if raw.lower().startswith("bearer ") else ""
        row = await asyncio.to_thread(mcp_tokens.verify_token, token) if token else None
        if row is None:
            logger.warning("MCP 请求被拒绝：缺少或无效的 Bearer Token")
            resp = JSONResponse(
                {
                    "ok": False,
                    "code": "PERMISSION_DENIED",
                    "message": "缺少或无效的 Bearer Token；请在平台「本地 Agent 编写」中重新生成文案",
                },
                status_code=401,
            )
            await resp(scope, receive, send)
            return
        project_reset = _current_project.set(int(row.project_id))
        owner_reset = _current_owner.set(f"token:{row.id}")
        base_reset = _current_base.set(f"{scope.get('scheme', 'http')}://{host}" if host else "")
        try:
            await self.app(scope, receive, send)
        finally:
            _current_base.reset(base_reset)
            _current_owner.reset(owner_reset)
            _current_project.reset(project_reset)


class _RootPathShim:
    """把 ``/mcp`` 及任意子路径统一映射到内部 MCP 应用的 ``/``。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") in ("http", "websocket"):
            scope = dict(scope)
            scope["path"] = "/"
        await self.app(scope, receive, send)


def build_mcp_app():
    """返回 MCP ASGI 应用（内部路由为 ``/``）。

    平台可能通过 localhost / 局域网 IP / 反向代理访问，Host 头不固定；
    鉴权已由 Bearer Token 中间件负责，这里关闭 SDK 默认的 localhost DNS 重绑定保护。
    """
    from mcp.server.transport_security import TransportSecuritySettings

    inner = get_mcp_server().streamable_http_app(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return _RootPathShim(BearerAuthMiddleware(inner))


def mount_mcp(app) -> None:
    """挂载到 FastAPI：同时注册精确 ``/mcp`` 与子路径，避免 307 重定向。"""
    from starlette.routing import Mount, Route

    handler = build_mcp_app()
    # 精确路径（客户端通常配置 http://host:8001/mcp）
    app.router.routes.append(Route("/mcp", endpoint=handler))
    # 兼容带尾斜杠/子路径的客户端
    app.router.routes.append(Mount("/mcp", app=handler))
