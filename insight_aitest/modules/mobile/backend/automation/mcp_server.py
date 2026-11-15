# -*- coding: utf-8 -*-
"""Mobile MCP Server（基于官方 mcp>=2.0.0 MCPServer Streamable HTTP 实现）。

挂载点：``/api/modules/mobile/mcp``（含简写别名 ``/api/mobile/mcp``），
使用 ``Authorization: Bearer <session_token>``（或 ``?token=``）鉴权并绑定会话租约。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Callable
from contextvars import ContextVar
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from insight_aitest.modules.mobile.backend.automation import prompt_builder
from insight_aitest.modules.mobile.backend.automation import session_manager as sm
from insight_aitest.modules.mobile.backend.automation.validator import (
    _FORBIDDEN_ATTR_CALLS,
    _FORBIDDEN_BUILTINS,
    _FORBIDDEN_MODULES,
)
from insight_aitest.modules.mobile.backend.deps import get_mobile_db
from insight_aitest.platform.mcp_http import build_streamable_mcp_app, mount_streamable_mcp

logger = logging.getLogger(__name__)

_current_runtime: ContextVar[sm.SessionRuntime | None] = ContextVar(
    "mobile_mcp_runtime", default=None
)
_current_base: ContextVar[str] = ContextVar("mobile_mcp_base_url", default="")

_server: MCPServer | None = None

INSTRUCTIONS = """Insight-AITest App 自动化「真机探索 + 暂存试跑 + 固化入库」MCP 服务。
- 认证与边界：请求头携带 Authorization: Bearer <token>，Token 绑定单个生成会话与真机租约；Token 与密码勿写入脚本或仓库；仅读写当前暂存区 case.py 与 pages/*.py。
- 标准路径：create = get_case_context → mobile_launch_app → (mobile_snapshot / mobile_screenshot / mobile_tap / mobile_input / mobile_swipe / mobile_back / mobile_handle_alert) → write_staging_file → run_server_dry_run → commit_staging_script；fix = get_case_context → read_staging_file('case.py') → 真机复现 → write_staging_file → run_server_dry_run → commit_staging_script。
- 修复约束：以现有脚本为基线做最小修复，不改无关步骤，禁止为通过而删除或放宽断言。
- 定位规范：优先采用工具返回的 recommended_locator（accessibility_id / resource-id / android_uiautomator / xpath），禁止绝对像素坐标 driver.tap([(x, y)])。
- 脚本契约：入口函数为 def test_case(driver, params, app_env):，直接使用脚手架注入的 driver fixture，禁止自行调用 webdriver.Remote。
- 试跑守卫：write_staging_file 写入或修改 case.py 后，必须通过 run_server_dry_run 真机试跑通过，才能调用 commit_staging_script 入库并释放设备锁。
- 失败处理：isError=true 时先读 JSON 中的 code / fix / required_next；收到 DRY_RUN_REQUIRED 时先调用 run_server_dry_run，不要反复写入相同内容；同一错误码连续 3 次无进展则停止并汇报。
- 兜底：客户端未注入本说明或未展示 structuredContent 时，可先读 insight://mobile/instructions、insight://mobile/rules 与 insight://mobile/template。"""

_MINIMAL_TEMPLATE = '''# -*- coding: utf-8 -*-
"""Mobile App 自动化用例最小可运行骨架。"""

from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def test_case(driver, params, app_env):
    wait = WebDriverWait(driver, 15)
    # 1. [步骤] 使用推荐定位器定位并交互（禁止使用 driver.tap([(x, y)])）
    # el = wait.until(EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, "示例入口")))
    # el.click()
    # 2. [断言] 校验目标界面元素已呈现
    assert driver.current_package == app_env["app_package"]
'''


# ---- 返回契约：声明稳定字段并保留 extra="allow" ----


class ToolPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    ok: bool = True


class CaseContextPayload(ToolPayload):
    intent: str = "create"
    workflow: dict = Field(default_factory=dict)
    case: dict = Field(default_factory=dict)
    app: dict = Field(default_factory=dict)
    device_id: str = ""
    existing_pages: list = Field(default_factory=list)
    lessons: list = Field(default_factory=list)
    scaffold_rules: list[str] = Field(default_factory=list)


class ActionPayload(ToolPayload):
    device_id: str = ""
    ref: str = ""
    direction: str = ""
    action: str = ""
    recommended_locator: dict | None = None


class SnapshotPayload(ToolPayload):
    activity: str = ""
    raw_nodes: int = 0
    kept_nodes: int = 0
    snapshot: str = ""


class ScreenshotPayload(ToolPayload):
    filename: str = ""
    bytes: int = 0


class StagingFilePayload(ToolPayload):
    exists: bool | None = None
    path: str = ""
    content: str = ""
    bytes: int = 0
    sha256: str = ""


class DryRunPayload(ToolPayload):
    passed: bool = False
    stage: str = ""
    run_id: int | None = None
    duration_ms: int | None = None
    error: str = ""
    stdout_tail: str = ""
    logcat_tail: str = ""
    screenshots: list[str] = Field(default_factory=list)


class CommitPayload(ToolPayload):
    committed: bool = False
    case_id: int = 0
    script_version: int = 0


_READ = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
_DEVICE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)
_WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
_COMMIT = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
)


def _require_runtime() -> sm.SessionRuntime:
    rt = _current_runtime.get()
    if rt is None:
        raise ToolError("PERMISSION_DENIED：未认证，请在 MCP 请求头携带 Authorization: Bearer <token>")
    return rt


def _mcp_url() -> str:
    base = _current_base.get()
    return f"{base}/api/modules/mobile/mcp" if base else ""


def _error(payload: dict[str, Any] | str) -> CallToolResult:
    """业务失败：isError=true，错误体只走 text（structuredContent 不填）。"""
    body = (
        payload
        if isinstance(payload, dict)
        else {
            "ok": False,
            "code": "TOOL_ERROR",
            "message": payload,
            "fix": "",
            "retryable": True,
            "required_next": None,
        }
    )
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(body, ensure_ascii=False, default=str))],
        is_error=True,
    )


def _result(summary: str, data: dict[str, Any]) -> CallToolResult:
    """参照 UI MCP：content 仅放简洁摘要，完整结构化数据走 structuredContent，避免大 JSON 传两遍。"""
    payload = {"ok": True, **data}
    return CallToolResult(
        content=[TextContent(type="text", text=summary.strip())],
        structured_content=payload,
        is_error=False,
    )


async def _run_in_session(
    name: str, args: dict[str, Any], fn: Callable[[sm.SessionRuntime], Any]
) -> tuple[bool, Any]:
    """在会话互斥锁内同步执行工具逻辑（放到线程池避免阻塞事件循环）。"""
    rt = _require_runtime()

    def _work() -> tuple[bool, Any]:
        with rt.lock:
            rt.tool_calls += 1
            get_mobile_db().update_generation(rt.generation_id, tool_calls=rt.tool_calls)
            sm.append_event(rt.case_id, rt.generation_id, "tool_call", tool=name, args=args)
            try:
                return True, fn(rt)
            except sm.MobileToolError as e:
                sm.append_event(
                    rt.case_id,
                    rt.generation_id,
                    "tool_error",
                    tool=name,
                    code=e.code,
                    error=e.message,
                )
                return False, e.to_payload()
            except Exception as e:
                sm.append_event(
                    rt.case_id, rt.generation_id, "tool_error", tool=name, error=str(e)
                )
                return False, {
                    "ok": False,
                    "code": type(e).__name__.upper(),
                    "message": str(e),
                    "fix": "",
                    "retryable": True,
                    "required_next": None,
                }

    return await asyncio.to_thread(_work)


def _launch_app(rt: sm.SessionRuntime, clear_data: bool) -> dict[str, Any]:
    drv = sm._ensure_driver(rt, clear_data=clear_data)
    app = get_mobile_db().get_app(rt.app_id)
    if app and app.app_package:
        try:
            if drv.current_package != app.app_package:
                drv.activate_app(app.app_package)
        except Exception:
            pass
    return {"ok": True, "device_id": rt.device_id}


def _press_back(rt: sm.SessionRuntime) -> dict[str, Any]:
    drv = sm._ensure_driver(rt)
    drv.back()
    return {"ok": True}


def _handle_alert(rt: sm.SessionRuntime, action: str) -> dict[str, Any]:
    drv = sm._ensure_driver(rt)
    act = action or "accept"
    if act == "dismiss":
        drv.switch_to.alert.dismiss()
    else:
        drv.switch_to.alert.accept()
    return {"ok": True, "action": act}


def _build_rules_text() -> str:
    mods = ", ".join(sorted(_FORBIDDEN_MODULES))
    builtins = ", ".join(sorted(_FORBIDDEN_BUILTINS))
    attrs = ", ".join(f"{a}.{b}()" for a, b in sorted(_FORBIDDEN_ATTR_CALLS))
    return "\n".join(
        [
            "# Mobile App 自动化脚本规范",
            "1. 入口签名：def test_case(driver, params, app_env):（或 def test_*(driver, ...):）。",
            "2. 禁止在脚本中调用 webdriver.Remote，直接使用脚手架注入的 driver fixture。",
            "3. 禁止使用绝对像素点击 driver.tap([(x, y)])；优先使用 AppiumBy.ACCESSIBILITY_ID / ID / ANDROID_UIAUTOMATOR / XPATH。",
            f"4. 禁止导入系统模块：{mods}。",
            f"5. 禁止调用危险内建/系统函数：{builtins}、{attrs}。",
            "6. 可复用页面封装可写入 pages/<name>.py 并由 case.py 导入。",
        ]
    )


def _build_server() -> MCPServer:
    server = MCPServer(
        name="insight-mobile-mcp",
        title="Insight-AITest App 自动化",
        description="基于平台真机直连的 App 自动化探索、暂存试跑与固化入库 MCP 服务",
        instructions=INSTRUCTIONS,
        version="1.1.0",
    )

    @server.tool(
        name="get_case_context",
        title="读取用例与环境上下文",
        description="获取当前手机自动化用例详情（含失败原因）、workflow、App 环境、已有 pages 索引、错题经验与脚手架规则。",
        annotations=_READ,
    )
    async def get_case_context() -> CaseContextPayload:
        ok, res = await _run_in_session("get_case_context", {}, sm.tool_get_case_context)
        if not ok:
            return _error(res)
        case_info = res.get("case") or {}
        app_info = res.get("app") or {}
        workflow = res.get("workflow") or {}
        flow = " → ".join(s.get("tool", "") for s in (workflow.get("steps") or []))
        summary = "\n".join(
            [
                f"【用例上下文】case_id={case_info.get('id')} intent={res.get('intent')} script_version={case_info.get('script_version')}",
                f"标题：{case_info.get('title')} · 步骤={len(case_info.get('steps') or [])} · 设备={res.get('device_id')} · App={app_info.get('app_package')} ({app_info.get('platform')})",
                f"workflow={workflow.get('id')}: {flow}",
                f"已有 pages={len(res.get('existing_pages') or [])} · lessons={len(res.get('lessons') or [])}",
                "用例详情、App 配置、pages 索引与规则见 structuredContent；规则见 insight://mobile/rules，骨架见 insight://mobile/template",
            ]
        )
        return _result(summary, res)

    @server.tool(
        name="mobile_launch_app",
        title="启动被测 App",
        description="在平台主机直连设备上启动被测 App，支持选择是否清空应用数据冷启动。",
        annotations=_DEVICE,
    )
    async def mobile_launch_app(
        clear_data: Annotated[bool, Field(description="是否清除数据后冷启动（noReset=false）")] = False,
    ) -> ActionPayload:
        ok, res = await _run_in_session(
            "mobile_launch_app",
            {"clear_data": clear_data},
            lambda rt: _launch_app(rt, clear_data),
        )
        if not ok:
            return _error(res)
        return _result(
            f"已启动被测 App（device={res.get('device_id')} clear_data={clear_data}）；请调用 mobile_snapshot 采集控件树",
            res,
        )

    @server.tool(
        name="mobile_snapshot",
        title="采集控件树快照",
        description="获取当前手机界面裁剪后的控件树文本及短引用 [ref=eN]。",
        annotations=_READ,
    )
    async def mobile_snapshot(
        compact: Annotated[bool, Field(description="是否开启紧凑模式（仅保留可交互/带文本的核心控件）")] = False,
    ) -> SnapshotPayload:
        ok, res = await _run_in_session(
            "mobile_snapshot",
            {"compact": compact},
            lambda rt: sm.tool_snapshot(rt, compact=compact),
        )
        if not ok:
            return _error(res)
        header = (
            f"【控件快照】activity={res.get('activity') or '-'} "
            f"nodes={res.get('kept_nodes')}/{res.get('raw_nodes')}"
        )
        snap_text = res.get("snapshot") or ""
        return _result(f"{header}\n{snap_text}", res)

    @server.tool(
        name="mobile_screenshot",
        title="截取当前屏幕",
        description="截取当前手机屏幕图像并返回，同时同步保存过程截图供平台前端实时预览。",
        annotations=_DEVICE,
    )
    async def mobile_screenshot(
        label: Annotated[str, Field(description="可选截图标签（用于命名过程截图文件）")] = "",
    ) -> ScreenshotPayload:
        ok, res = await _run_in_session(
            "mobile_screenshot",
            {"label": label},
            lambda rt: sm.tool_screenshot(rt, label=label),
        )
        if not ok:
            return _error(res)
        png_bytes, filename = res
        b64 = base64.b64encode(png_bytes).decode("ascii")
        return CallToolResult(
            content=[
                TextContent(type="text", text=f"已保存过程截图: {filename} ({len(png_bytes)} bytes)"),
                ImageContent(type="image", data=b64, mime_type="image/png"),
            ],
            structured_content={"ok": True, "filename": filename, "bytes": len(png_bytes)},
            is_error=False,
        )

    @server.tool(
        name="mobile_tap",
        title="点击指定控件",
        description="点击 mobile_snapshot 返回的指定 ref 控件，并返回推荐的 Appium 定位写法。",
        annotations=_DEVICE,
    )
    async def mobile_tap(
        ref: Annotated[str, Field(description="mobile_snapshot 返回的控件短引用，例如 e4", min_length=1)],
    ) -> ActionPayload:
        ok, res = await _run_in_session(
            "mobile_tap", {"ref": ref}, lambda rt: sm.tool_tap(rt, ref)
        )
        if not ok:
            return _error(res)
        loc = res.get("recommended_locator") or {}
        return _result(
            f"已点击 {ref}；推荐定位：{loc.get('snippet') or loc.get('value') or '见 structuredContent'}",
            res,
        )

    @server.tool(
        name="mobile_input",
        title="向控件输入文本",
        description="向指定 ref 输入框输入文本，并返回推荐的 Appium 定位写法。",
        annotations=_DEVICE,
    )
    async def mobile_input(
        ref: Annotated[str, Field(description="mobile_snapshot 返回的输入框短引用，例如 e7", min_length=1)],
        text: Annotated[str, Field(description="待输入的文本内容")],
        clear_first: Annotated[bool, Field(description="输入前是否先清空原有文本")] = True,
        hide_keyboard: Annotated[bool, Field(description="输入后是否尝试收起软键盘")] = False,
    ) -> ActionPayload:
        ok, res = await _run_in_session(
            "mobile_input",
            {
                "ref": ref,
                "text": text,
                "clear_first": clear_first,
                "hide_keyboard": hide_keyboard,
            },
            lambda rt: sm.tool_input(
                rt, ref, text, clear_first=clear_first, hide_keyboard=hide_keyboard
            ),
        )
        if not ok:
            return _error(res)
        loc = res.get("recommended_locator") or {}
        return _result(
            f"已向 {ref} 输入文本；推荐定位：{loc.get('snippet') or loc.get('value') or '见 structuredContent'}",
            res,
        )

    @server.tool(
        name="mobile_swipe",
        title="滑动屏幕",
        description="按屏幕比例向指定方向滑动（up/down/left/right）。",
        annotations=_DEVICE,
    )
    async def mobile_swipe(
        direction: Annotated[
            Literal["up", "down", "left", "right"],
            Field(description="滑动方向：up / down / left / right"),
        ],
        distance_ratio: Annotated[
            float, Field(description="滑动距离占屏幕对应维度的比例（0.15 ~ 0.85）", ge=0.15, le=0.85)
        ] = 0.5,
    ) -> ActionPayload:
        ok, res = await _run_in_session(
            "mobile_swipe",
            {"direction": direction, "distance_ratio": distance_ratio},
            lambda rt: sm.tool_swipe(rt, direction=direction, distance_ratio=distance_ratio),
        )
        if not ok:
            return _error(res)
        return _result(f"已向 {direction} 滑动（比例 {distance_ratio}）", res)

    @server.tool(
        name="mobile_back",
        title="按返回键",
        description="按下 Android 系统返回键。",
        annotations=_DEVICE,
    )
    async def mobile_back() -> ActionPayload:
        ok, res = await _run_in_session("mobile_back", {}, _press_back)
        if not ok:
            return _error(res)
        return _result("已触发系统返回键", res)

    @server.tool(
        name="mobile_handle_alert",
        title="处理系统弹窗",
        description="处理当前系统权限或确认弹窗（accept 或 dismiss）。",
        annotations=_DEVICE,
    )
    async def mobile_handle_alert(
        action: Annotated[
            Literal["accept", "dismiss"],
            Field(description="弹窗处理动作：accept（允许/确定）或 dismiss（拒绝/取消）"),
        ] = "accept",
    ) -> ActionPayload:
        ok, res = await _run_in_session(
            "mobile_handle_alert",
            {"action": action},
            lambda rt: _handle_alert(rt, action),
        )
        if not ok:
            return _error(res)
        return _result(f"已处理系统弹窗: {action}", res)

    @server.tool(
        name="read_staging_file",
        title="读取暂存区文件",
        description="读取当前生成会话暂存区内的脚本或页面对象文件（仅允许 case.py 或 pages/*.py）。",
        annotations=_READ,
    )
    async def read_staging_file(
        rel_path: Annotated[str, Field(description="相对暂存区的路径，例如 case.py 或 pages/home_page.py", min_length=1)],
    ) -> StagingFilePayload:
        ok, res = await _run_in_session(
            "read_staging_file",
            {"rel_path": rel_path},
            lambda rt: sm.tool_read_staging_file(rt, rel_path),
        )
        if not ok:
            return _error(res)
        exists = bool(res.get("exists"))
        size = len((res.get("content") or "").encode("utf-8"))
        summary = (
            f"【暂存文件】{rel_path}（{size} bytes），源码见 structuredContent"
            if exists
            else f"【暂存文件】{rel_path} 尚不存在"
        )
        return _result(summary, res)

    @server.tool(
        name="write_staging_file",
        title="写入暂存区文件",
        description="写入当前生成会话暂存区文件（仅允许 case.py 或 pages/*.py）。",
        annotations=_WRITE,
    )
    async def write_staging_file(
        rel_path: Annotated[str, Field(description="相对暂存区的路径，例如 case.py 或 pages/<name>.py", min_length=1)],
        content: Annotated[str, Field(description="文件完整 UTF-8 源码内容")],
    ) -> StagingFilePayload:
        ok, res = await _run_in_session(
            "write_staging_file",
            {"rel_path": rel_path, "content": content},
            lambda rt: sm.tool_write_staging_file(rt, rel_path, content),
        )
        if not ok:
            return _error(res)
        return _result(
            f"已写入 {rel_path}（{res.get('bytes')} bytes, sha256={str(res.get('sha256') or '')[:12]}）；"
            "完成后请调用 run_server_dry_run 试跑验证",
            res,
        )

    @server.tool(
        name="run_server_dry_run",
        title="服务端真机试跑验真",
        description="在平台主机对暂存区 case.py 执行 AST 安全校验与真实 pytest 试跑；失败返回 isError=true 与修复指引，通过后可调用 commit_staging_script。",
        annotations=_DEVICE,
    )
    async def run_server_dry_run() -> DryRunPayload:
        ok, res = await _run_in_session("run_server_dry_run", {}, sm.tool_run_server_dry_run)
        if not ok:
            return _error(res)
        return _result(
            f"【试跑通过】run_id={res.get('run_id')} duration_ms={res.get('duration_ms')} "
            f"screenshots={len(res.get('screenshots') or [])}；"
            "日志与详情见 structuredContent，下一步调用 commit_staging_script 入库",
            res,
        )

    @server.tool(
        name="commit_staging_script",
        title="固化脚本入库",
        description="校验暂存区最新试跑结果后，将脚本与页面对象原子固化入库并释放设备租约锁；未通过试跑时返回 DRY_RUN_REQUIRED。",
        annotations=_COMMIT,
    )
    async def commit_staging_script() -> CommitPayload:
        ok, res = await _run_in_session("commit_staging_script", {}, sm.tool_commit_staging_script)
        if not ok:
            return _error(res)
        return _result(
            f"【已入库】case_id={res.get('case_id')} script_version=v{res.get('script_version')}，设备租约已释放",
            res,
        )

    @server.resource(
        "insight://mobile/instructions",
        name="运行规范",
        title="App 自动化 Agent 操作规范",
        description="真机探索流程、定位器规范、脚本契约与试跑守卫要求。",
        mime_type="text/plain",
    )
    def instructions_resource() -> str:
        return INSTRUCTIONS

    @server.resource(
        "insight://mobile/rules",
        name="脚手架与安全规则",
        title="App 自动化脚本校验规则",
        description="入口签名、禁用系统模块/调用以及定位器 AST 校验约束。",
        mime_type="text/markdown",
    )
    def rules_resource() -> str:
        return _build_rules_text()

    @server.resource(
        "insight://mobile/template",
        name="最小脚本骨架",
        title="Mobile pytest 脚本最小可运行骨架",
        description="接收 driver, params, app_env 的最小可运行 Appium pytest 用例模板。",
        mime_type="text/x-python",
    )
    def template_resource() -> str:
        return _MINIMAL_TEMPLATE

    @server.prompt(
        name="mobile.create",
        title="新建 App 自动化脚本",
        description="按真机探索 → 编写脚本 → 服务端试跑 → 固化入库流程生成新用例脚本。",
    )
    def prompt_create(
        token: Annotated[str, Field(description="平台会话 Bearer Token；客户端已认证时可省略")] = "",
    ) -> list[dict]:
        rt = _current_runtime.get()
        content = prompt_builder.render_create_prompt(
            case_id=rt.case_id if rt else None,
            token=token,
            mcp_url=_mcp_url(),
        )
        return [{"role": "user", "content": content}]

    @server.prompt(
        name="mobile.fix",
        title="修复 App 自动化脚本",
        description="读取当前暂存区脚本并在真机上复现定位问题后最小修复、试跑入库。",
    )
    def prompt_fix(
        token: Annotated[str, Field(description="平台会话 Bearer Token；客户端已认证时可省略")] = "",
    ) -> list[dict]:
        rt = _current_runtime.get()
        content = prompt_builder.render_fix_prompt(
            case_id=rt.case_id if rt else None,
            token=token,
            mcp_url=_mcp_url(),
        )
        return [{"role": "user", "content": content}]

    return server


def get_mcp_server() -> MCPServer:
    global _server
    if _server is None:
        _server = _build_server()
    return _server


class MobileBearerAuthMiddleware:
    """校验 Mobile 会话 Bearer Token（或 query ?token=），并注入 SessionRuntime 与客户端 base URL。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        auth_header = ""
        host = ""
        forwarded_host = ""
        forwarded_proto = ""
        for key, value in scope.get("headers") or []:
            if key == b"authorization":
                auth_header = value.decode("latin-1")
            elif key == b"host":
                host = value.decode("latin-1")
            elif key == b"x-forwarded-host":
                forwarded_host = value.decode("latin-1")
            elif key == b"x-forwarded-proto":
                forwarded_proto = value.decode("latin-1")

        token = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        if not token:
            qs = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
            token = (qs.get("token") or [""])[0].strip()

        if not token:
            resp = JSONResponse(
                {"ok": False, "code": "PERMISSION_DENIED", "message": "缺少 MCP 会话 Bearer Token"},
                status_code=401,
            )
            await resp(scope, receive, send)
            return

        try:
            rt, _ = await asyncio.to_thread(sm.authenticate_session, token)
        except PermissionError as e:
            logger.warning("Mobile MCP 请求被拒绝: %s", e)
            resp = JSONResponse(
                {"ok": False, "code": "PERMISSION_DENIED", "message": str(e)},
                status_code=401,
            )
            await resp(scope, receive, send)
            return

        effective_host = forwarded_host.split(",")[0].strip() if forwarded_host else host
        effective_scheme = (forwarded_proto.split(",")[0].strip() if forwarded_proto else "") or scope.get("scheme", "http")
        base_url = f"{effective_scheme}://{effective_host}" if effective_host else ""

        reset_tok = _current_runtime.set(rt)
        base_reset = _current_base.set(base_url)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_base.reset(base_reset)
            _current_runtime.reset(reset_tok)


def build_mcp_app() -> Any:
    """构建带会话 Bearer 鉴权的 Mobile MCP Streamable HTTP ASGI 应用。"""
    return build_streamable_mcp_app(get_mcp_server(), MobileBearerAuthMiddleware)


def mount_mobile_mcp(app: Any) -> None:
    """将 Mobile MCP 挂载到 FastAPI（同时支持完整模块路径与短路径别名，避免 307 重定向）。"""
    mount_streamable_mcp(
        app,
        ("/api/modules/mobile/mcp", "/api/mobile/mcp"),
        build_mcp_app(),
    )
