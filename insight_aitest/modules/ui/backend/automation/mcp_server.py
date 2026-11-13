# -*- coding: utf-8 -*-
"""平台 MCP 服务：把「契约 / 环境 / 用例 / 校验 / 试跑 / 入库」暴露给本地 Agent。

挂载点：``/mcp``（Bearer Token 鉴权，Token 由平台前端生成文案时创建）。
工具清单：
- ``ui.contract.get`` / ``ui.env.get`` / ``ui.case.get`` / ``ui.case.triage`` / ``ui.example.get``
  / ``ui.run.latest``
- ``ui.script.validate`` / ``ui.script.dry_run`` / ``ui.script.submit``
附：prompts ``ui.create`` / ``ui.fix``，resources ``insight://rules`` / ``insight://template``。
"""

from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from typing import Annotated

from logzero import logger
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
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
        # ToolError 的 message 会原样到达客户端；ValueError 会被 SDK 脱敏成通用文案
        raise ToolError("PERMISSION_DENIED：未认证，请在 MCP 请求头携带 Authorization: Bearer <token>")
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


# ---- 返回契约：声明稳定字段，extra=allow 保留动态字段（不裁剪 structuredContent）----

class ToolPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    ok: bool = True


class ContractPayload(ToolPayload):
    contract_version: str = ""
    case: dict = Field(default_factory=dict)
    script: dict = Field(default_factory=dict)
    env: dict | None = None
    assets: list = Field(default_factory=list)
    rules: dict = Field(default_factory=dict)
    intent: str = "create"
    workflow: dict = Field(default_factory=dict)


class TriagePayload(ToolPayload):
    summary: dict = Field(default_factory=dict)
    items: list = Field(default_factory=list)


class EnvPayload(ToolPayload):
    env_id: int = 0
    name: str = ""
    base_url: str = ""
    entry_url: str = ""
    site: str = ""
    auth: dict = Field(default_factory=dict)
    auth_ready: bool = False
    message: str = ""


class CasePayload(ToolPayload):
    case_id: int = 0
    title: str = ""
    site: str = ""
    case_rev: str = ""
    script: dict = Field(default_factory=dict)


class ExamplePayload(ToolPayload):
    hard_rules: list = Field(default_factory=list)
    known_traps: list = Field(default_factory=list)
    lessons: list = Field(default_factory=list)
    known_routes: list = Field(default_factory=list)
    examples: list = Field(default_factory=list)
    assets: list = Field(default_factory=list)
    template: str = ""
    note: str = ""


class ValidatePayload(ToolPayload):
    stage: str = ""
    source_hash: str = ""
    violations: list = Field(default_factory=list)
    next: str = ""


class DryRunPayload(ToolPayload):
    stage: str = ""
    source_hash: str = ""
    duration_ms: int | None = None
    screenshots: list[str] = Field(default_factory=list)
    log_tail: str = ""
    next: str = ""


class SubmitPayload(ToolPayload):
    case_id: int = 0
    script_version: int = 0
    source_hash: str = ""
    script_path: str = ""
    message: str = ""


class RunLatestPayload(ToolPayload):
    run: dict | None = None
    recent: list = Field(default_factory=list)
    message: str = ""


_READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
_ENV = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
_DRY_RUN = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
_SUBMIT = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)

# ---- 入参模型：files 显式建模，避免 schema 退化成 additionalProperties: true ----

class FileItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(description="文件路径；仅允许 case.py、pages/<name>.py、common/<name>.py", min_length=1)
    content: str = Field(description="文件全文；单个文件不超过 512KB", min_length=1)


CaseId = Annotated[int, Field(description="平台用例 ID；必须是当前 Token 所属项目内的用例", ge=1)]
Files = Annotated[
    list[FileItem],
    Field(description="完整文件集合；最多 20 个，单个不超过 512KB，path 仅允许 case.py / pages/<name>.py / common/<name>.py", min_length=1, max_length=20),
]
SourceHash = Annotated[str, Field(description="ui.script.validate 返回的 source_hash；30 分钟内有效，且必须与本次 files 内容一致")]


def _file_dicts(files: list[FileItem]) -> list[dict]:
    return [item.model_dump() for item in files]

INSTRUCTIONS = """Insight-AITest：UI 自动化脚本「本地编写 + 平台校验入库」服务。
- 认证：请求头 Authorization: Bearer <token>，Token 绑定项目；不要写入脚本、不要提交仓库。
- 流程：不预设固定顺序，只以 ui.contract.get 返回的 workflow 为准；返回体的 intent 表示新建还是修复。
- 批量处理：先调用 ui.case.triage 判定每个用例该 create / fix / skip，skip 的用例不要改动。
- 规则优先级：本次 ui.contract.get 的 rules > ui.example.get 的 lessons/known_traps > 通用经验；与实测页面冲突时以实测为准。
- 失败处理：isError=true 时读 code/fix/required_next 再决定是否重试；同一错误码连续 3 次不推进就停止并说明原因。
- 终止条件：PERMISSION_DENIED / CASE_NOT_FOUND / ENV_NOT_CONFIGURED / ENV_NOT_ALLOWED 立即停止。
- 只操作当前 Token 项目内的用例，不要修改其他用例或平台资产。"""


def _error(payload: dict) -> CallToolResult:
    """业务失败：isError=true，错误体只走 text。

    structuredContent 不填：严格客户端会用成功态的 outputSchema 校验它，
    反而把真正的 fix 提示变成校验异常。
    """
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))],
        is_error=True,
    )


def _result(summary: str, payload: dict) -> CallToolResult:
    """大返回：content 只放摘要，完整数据走 structuredContent，避免同一份 JSON 传两遍。"""
    return CallToolResult(
        content=[TextContent(type="text", text=summary.strip())],
        structured_content=payload,
        is_error=False,
    )


def _mcp_url() -> str:
    base = _current_base.get()
    return f"{base}/mcp" if base else "http://127.0.0.1:8001/mcp"


def _fix_prompt_text(case_id: int, token: str) -> str:
    db = _db()
    case = svc.resolve_case(db, case_id, _project_id())
    if case is None:
        raise ToolError(f"CASE_NOT_FOUND：用例 {case_id} 不存在或不属于当前 Token 的项目")
    info = svc.case_payload(case)
    run = svc.latest_run_summary(db, case, history=3)
    latest = run.get("run") or {}
    script = str((info.get("script") or {}).get("content") or "")[:12000]
    log_tail = str(latest.get("log_tail") or "")[-4000:]
    failure = latest.get("failure_point") or "（暂无执行记录或未记录失败原因）"
    return f"""你是资深 Playwright UI 自动化测试工程师。请通过 Insight-AITest 平台 MCP 服务，修复用例 {case_id} 的现有脚本并重新入库。

【MCP 接入】
- 服务地址：{_mcp_url()}（Streamable HTTP）
- 请求头：Authorization: Bearer {token or "<从平台生成的 Bearer Token>"}
- 可用工具：ui.run.latest / ui.contract.get / ui.case.get / ui.example.get / ui.script.validate / ui.script.dry_run / ui.script.submit
- Token 只在本会话使用；不要写入脚本、不要提交到仓库。

【用例】
- 标题：{info.get("title") or ""}
- case_rev：{info.get("case_rev") or ""}（入库时原样传回）
- 脚本版本：{(info.get("script") or {}).get("version")}

【最近一次执行】
- 状态：{latest.get("status") or "无记录"}
- 失败原因：{failure}
- 日志尾部：
{log_tail or "（无）"}

【修复要求】
1. 先调用 ui.run.latest(case_id={case_id}) 复核失败现场；再调用 ui.contract.get 与 ui.case.get 获取最新规则与用例快照。
2. 以现有脚本为基线做最小修改，不要重写整个用例、不要改动与失败无关的步骤。
3. 不允许为了通过而删除断言、放宽断言或注释掉步骤；确属用例本身问题时在最终回报中说明。
4. 保持日志规范：每个 test 函数至少 3 条 print，[步骤] 开头，断言前打印 [断言] 实际值与预期值。
5. 修改后依次调用 ui.script.validate → ui.script.dry_run → ui.script.submit，全部 ok 才算完成。
6. 同一错误码连续 3 次仍无法推进时停止并回报。

【现有脚本】
```python
{script}
```

【最终回报】
1. 根因 2. 改动点（文件+行为）3. 校验/试跑结果 4. 脚本版本 5. 未解决项与建议
"""


def _build_server() -> MCPServer:
    server = MCPServer(
        name="insight-aitest",
        title="Insight-AITest UI 自动化",
        description="UI 自动化脚本「本地编写 + 平台校验入库」服务",
        instructions=INSTRUCTIONS,
        version="1.2.0",
    )

    @server.tool(
        name="ui.contract.get",
        title="读取编写契约",
        description=(
            "读取用例编写契约：用例快照与 case_rev、现有脚本版本与源码、当前环境摘要、"
            "项目 pages/common 资产清单、文件与 import 规则、硬编码/日志约束、错误码表，"
            "以及本次应遵循的 workflow。契约是脚本编写的唯一事实来源。"
            "进度记录：调用后平台会把该用例标记为「生成中」，仅用于前端进度展示，"
            "不修改用例、脚本或项目资产。"
        ),
        annotations=_READ,
    )
    def contract_get(case_id: CaseId) -> ContractPayload:
        db, case, err = _case_or_none(case_id)
        if err:
            return _error(err)
        svc.mark_generating(db, case)
        env = resolve_current_env(db, int(case.project_id))
        payload = contract.contract_payload(case, env, intent=svc.case_intent(db, case))
        payload["ok"] = True
        case_info = payload.get("case") or {}
        script_info = payload.get("script") or {}
        summary = "\n".join(
            [
                f"【编写契约】contract_version={payload.get('contract_version')} intent={payload.get('intent')}",
                f"case_rev={case_info.get('case_rev')} script_version={script_info.get('version')} "
                f"assets={len(payload.get('assets') or [])}",
                f"workflow={(payload.get('workflow') or {}).get('id')}；"
                "完整 rules / env / assets / workflow 见 structuredContent",
            ]
        )
        return _result(summary, payload)

    @server.tool(
        name="ui.env.get",
        title="读取环境与登录态",
        description=(
            "读取用例所属环境的接入信息：base_url、entry_url、auth.mode、header 名/值，"
            "以及一次性 storageState 下载地址（5 分钟内有效、单张票据只能下载一次）。"
            "用于浏览器探索阶段注入登录态；凭证不要写入脚本或仓库。"
            "副作用：每次调用重新准备登录态并签发新票据，可能触发真实登录。"
        ),
        annotations=_ENV,
    )
    async def env_get(case_id: CaseId) -> EnvPayload:
        db, case, err = _case_or_none(case_id)
        if err:
            return _error(err)
        payload = await asyncio.to_thread(svc.env_payload, db, case)
        base = _current_base.get()
        auth = payload.get("auth") or {}
        rel = auth.get("storage_state_url") or ""
        if payload.get("ok") and base and rel.startswith("/"):
            auth["storage_state_url"] = base + rel
        return payload

    @server.tool(
        name="ui.case.get",
        title="读取用例详情",
        description=(
            "读取用例详情：标题、前置、步骤、预期、端、参数定义，以及 case_rev、script.version "
            "与 script.content（当前脚本全文，修复时作为基线）。"
            "case_rev 与 script.version 在入库时作为 expect_case_rev / expect_script_version 原样回传。"
        ),
        annotations=_READ,
    )
    def case_get(case_id: CaseId) -> CasePayload:
        _, case, err = _case_or_none(case_id)
        if err:
            return _error(err)
        payload = svc.case_payload(case)
        payload["ok"] = True
        return payload

    @server.tool(
        name="ui.case.triage",
        title="用例分诊",
        description=(
            "批量判定每个用例本轮该做什么：create（无脚本）、fix（最近执行失败）、"
            "skip（最近执行通过、执行中或无执行记录）。"
            "返回每个用例的状态、case_rev、脚本版本、最近一次执行摘要，以及 action 与 next_tool。"
            "只读，不写任何状态；skip 的用例不要调用其他工具或改动脚本。"
        ),
        annotations=_READ,
    )
    def case_triage(
        case_ids: Annotated[
            list[int],
            Field(description="要判定的用例 ID 列表；单次最多 50 个，且必须属于当前 Token 的项目", min_length=1, max_length=50),
        ],
    ) -> TriagePayload:
        project_id = _project_id()
        db = _db()
        cases = [c for c in (svc.resolve_case(db, cid, project_id) for cid in case_ids) if c is not None]
        if not cases:
            return _error(svc.fail("CASE_NOT_FOUND", "用例均不存在或不属于当前 Token 的项目"))
        result = svc.triage_cases(db, cases)
        result["ok"] = True
        summary = result.get("summary") or {}
        lines = [
            "【用例分诊】"
            + " ".join(f"{k}={v}" for k, v in summary.items()),
        ]
        for item in (result.get("items") or [])[:20]:
            lines.append(
                f"- {item.get('case_id')} {item.get('title') or ''} → {item.get('action')}"
                f"（{item.get('reason') or ''}）"
            )
        lines.append("逐例明细与 next_tool 见 structuredContent")
        return _result("\n".join(lines), result)

    @server.tool(
        name="ui.example.get",
        title="读取项目经验范例",
        description=(
            "读取本项目可复用的经验包：硬规则、平台已验证的 UI 坑、项目错题库（失败+解决方案）、"
            "同目录已验证脚本片段、已知 hash 路由、pages/common 的类与方法签名、最小可运行骨架。"
            "输出已脱敏；无历史脚本时 examples 为空但 template 仍可用。只读，可多次调用。"
        ),
        annotations=_READ,
    )
    def example_get(
        case_id: CaseId,
        max_examples: Annotated[int, Field(description="返回的脚本片段条数上限", ge=1, le=10)] = 3,
        include_assets: Annotated[bool, Field(description="是否包含 pages/common 的签名索引")] = True,
    ) -> ExamplePayload:
        db, case, err = _case_or_none(case_id)
        if err:
            return _error(err)
        payload = example_service.build_example_payload(
            case, db, max_examples=max_examples, include_assets=include_assets
        )
        payload["ok"] = True
        summary = "\n".join(
            [
                f"【项目经验】hard_rules={len(payload.get('hard_rules') or [])} "
                f"known_traps={len(payload.get('known_traps') or [])} "
                f"lessons={len(payload.get('lessons') or [])} "
                f"routes={len(payload.get('known_routes') or [])} "
                f"examples={len(payload.get('examples') or [])} "
                f"assets={len(payload.get('assets') or [])}",
                "片段、资产签名与最小骨架 template 见 structuredContent",
            ]
        )
        return _result(summary, payload)

    @server.tool(
        name="ui.script.validate",
        title="校验脚本文件",
        description=(
            "对一个用例的文件集合执行 L1 静态校验（AST、import 白名单、硬编码、凭证、执行日志）"
            "与 L2 pytest --collect-only。成功返回 source_hash（30 分钟内有效，供试跑与入库引用）；"
            "失败返回 isError=true 与 violations[]（每条含 code 与 fix）。"
            "文件路径仅允许 case.py、pages/<name>.py、common/<name>.py，最多 20 个、单个不超过 512KB。"
            "校验记录仅用于前端进度展示，不修改用例、脚本或项目资产。"
        ),
        annotations=_READ,
    )
    async def script_validate(case_id: CaseId, files: Files) -> ValidatePayload:
        db, case, err = _case_or_none(case_id)
        if err:
            return _error(err)
        result = await asyncio.to_thread(svc.validate, db, case, _file_dicts(files))
        return result if result.get("ok") else _error(result)

    @server.tool(
        name="ui.script.dry_run",
        title="平台试跑脚本",
        description=(
            "在平台 staging 目录用当前环境真实执行一次脚本，不写入正式资产、不计入执行记录。"
            "硬前置：同一 files 已通过 ui.script.validate 且 source_hash 未过期；"
            "同一用例 60 秒内只允许一次，单次上限 240 秒。会占用该用例 15 分钟独占租约。"
            "返回退出码、耗时、步骤日志尾部与截图；通过后 24 小时内可入库。"
        ),
        annotations=_DRY_RUN,
    )
    async def script_dry_run(case_id: CaseId, files: Files, source_hash: SourceHash) -> DryRunPayload:
        db, case, err = _case_or_none(case_id)
        if err:
            return _error(err)
        owner = _owner()
        if not svc.acquire_lease(db, case, owner):
            return _error(svc.fail("BUSY", "该用例正被其他本地 Agent 操作，请稍后重试"))
        try:
            result = await asyncio.to_thread(svc.dry_run, db, case, _file_dicts(files), source_hash)
            return result if result.get("ok") else _error(result)
        finally:
            svc.release_lease(db, case)

    @server.tool(
        name="ui.script.submit",
        title="提交脚本入库",
        description=(
            "把已通过试跑的脚本写入平台：归档旧版本、版本号 +1、用例状态置为「已实现」。"
            "硬前置：source_hash、expect_case_rev、expect_script_version 必须与平台一致；"
            "覆盖 pages/common 需 force_assets=true（覆盖前自动备份）。写入不可回滚。"
            "默认路径为版本化新增并归档旧版；仅当 force_assets=true 时才替换已有项目资产。"
        ),
        annotations=_SUBMIT,
    )
    async def script_submit(
        case_id: CaseId,
        files: Files,
        source_hash: SourceHash,
        expect_case_rev: Annotated[str, Field(description="ui.case.get 返回的 case_rev，原样回传用于乐观锁")],
        expect_script_version: Annotated[int, Field(description="ui.case.get 返回的 script.version，整数")],
        params_schema: Annotated[list | None, Field(description="可选用例参数定义；不传表示不修改")] = None,
        force_assets: Annotated[bool, Field(description="是否允许覆盖已存在的 pages/common 资产")] = False,
    ) -> SubmitPayload:
        db, case, err = _case_or_none(case_id)
        if err:
            return _error(err)
        owner = _owner()
        if not svc.acquire_lease(db, case, owner):
            return _error(svc.fail("BUSY", "该用例正被其他本地 Agent 操作，请稍后重试"))
        try:
            result = await asyncio.to_thread(
                svc.submit,
                db,
                case,
                _file_dicts(files),
                source_hash,
                expect_case_rev,
                expect_script_version,
                params_schema,
                force_assets,
            )
            return result if result.get("ok") else _error(result)
        finally:
            svc.release_lease(db, case)

    @server.tool(
        name="ui.run.latest",
        title="读取最近执行结果",
        description=(
            "返回用例最近一次脚本执行（可用 run_id 指定）的状态、耗时、失败阶段、失败原因、"
            "日志尾部、截图文件名、trace 路径，以及最近 N 次执行摘要。"
            "无执行记录时返回 ok=true 且 run=null。只读。"
        ),
        annotations=_READ,
    )
    def run_latest(
        case_id: CaseId,
        run_id: Annotated[int | None, Field(description="指定历史执行 ID；不传取最近一次", ge=1)] = None,
        history: Annotated[int, Field(description="返回的历史执行条数", ge=1, le=20)] = 5,
    ) -> RunLatestPayload:
        db, case, err = _case_or_none(case_id)
        if err:
            return _error(err)
        payload = svc.latest_run_summary(db, case, run_id=run_id, history=history)
        payload["ok"] = True
        run = payload.get("run") or {}
        if not run:
            summary = "【最近执行】无执行记录"
        else:
            summary = "\n".join(
                [
                    f"【最近执行】status={run.get('status')} run_id={run.get('id')} "
                    f"duration_ms={run.get('duration_ms')}",
                    f"失败原因：{(run.get('error') or '无')[:200]}",
                    "日志尾部、截图与历史记录见 structuredContent",
                ]
            )
        return _result(summary, payload)

    # ---- MCP prompts：把编写/修复文案交给客户端原生渲染，替代手工粘贴 ----

    @server.prompt(
        name="ui.create",
        title="本地 Agent 编写脚本",
        description="生成可直接交给本地 Agent 的编写指令；case_ids 为逗号分隔的用例 ID，token 为平台「本地 Agent 编写」生成的 Bearer Token。",
    )
    def ui_create_prompt(case_ids: str, token: str = "") -> list[dict]:
        from insight_aitest.modules.ui.backend.automation.routes.authoring import build_prompt

        ids = [int(x) for x in str(case_ids).replace(" ", "").split(",") if x.isdigit()]
        if not ids:
            raise ToolError("case_ids 至少包含一个数字用例 ID")
        text = build_prompt(ids, token or "<从平台生成的 Bearer Token>", _mcp_url())
        return [{"role": "user", "content": text}]

    @server.prompt(
        name="ui.fix",
        title="本地 Agent 修复脚本",
        description="基于现有脚本与最近一次执行失败生成修复指令；case_id 为用例 ID，token 为平台 Bearer Token。",
    )
    def ui_fix_prompt(case_id: str, token: str = "") -> list[dict]:
        if not str(case_id).isdigit():
            raise ToolError("case_id 必须是数字")
        return [{"role": "user", "content": _fix_prompt_text(int(case_id), token)}]

    # ---- MCP resources：静态规则与骨架，客户端可按 URI 直接读取 ----

    @server.resource(
        "insight://rules",
        name="编写规则",
        title="编写硬规则与错误码",
        description="L1/L2 校验规则、import 白名单、日志格式要求、错误码与修复建议。",
        mime_type="application/json",
    )
    def rules_resource() -> str:
        return json.dumps(contract.contract_rules(), ensure_ascii=False)

    @server.resource(
        "insight://template",
        name="最小骨架",
        title="最小可运行脚本骨架",
        description="包含 [步骤]/[断言] 日志的最小可运行 Playwright 脚本骨架。",
        mime_type="text/x-python",
    )
    def template_resource() -> str:
        return example_service.template()

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
