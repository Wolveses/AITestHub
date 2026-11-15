# -*- coding: utf-8 -*-
"""App 自动化本地 Agent 文案的唯一渲染器：REST 会话文案与 MCP prompts 共用。"""

from __future__ import annotations

WORKFLOW_CREATE_STEPS = [
    {"step": 1, "tool": "get_case_context", "required": True},
    {"step": 2, "tool": "mobile_launch_app", "required": True},
    {"step": 3, "tool": "mobile_snapshot / mobile_tap / mobile_input / mobile_swipe", "required": True},
    {"step": 4, "tool": "write_staging_file", "required": True},
    {"step": 5, "tool": "run_server_dry_run", "required": True},
    {"step": 6, "tool": "commit_staging_script", "required": True},
]

WORKFLOW_FIX_STEPS = [
    {"step": 1, "tool": "get_case_context", "required": True},
    {"step": 2, "tool": "read_staging_file", "required": True},
    {"step": 3, "tool": "mobile_launch_app / mobile_snapshot / mobile_tap / mobile_input", "required": True},
    {"step": 4, "tool": "write_staging_file", "required": True},
    {"step": 5, "tool": "run_server_dry_run", "required": True},
    {"step": 6, "tool": "commit_staging_script", "required": True},
]


def workflow_for_intent(intent: str) -> dict:
    is_fix = intent == "fix"
    return {
        "id": "mobile.fix@1" if is_fix else "mobile.create@1",
        "intent": "fix" if is_fix else "create",
        "steps": WORKFLOW_FIX_STEPS if is_fix else WORKFLOW_CREATE_STEPS,
    }


def _access_lines(*, mcp_url: str, token: str) -> list[str]:
    lines: list[str] = []
    if mcp_url:
        lines.append(f"- MCP: {mcp_url} (Streamable HTTP)")
    if token:
        lines.append(f"- Authorization: Bearer {token}")
    else:
        lines.append("- 连接: 沿用当前 MCP 会话（无需额外 Token）")
    return lines


def render_create_prompt(
    *,
    case_id: int | None = None,
    token: str = "",
    mcp_url: str = "",
) -> str:
    """新建脚本极简文案：用例、环境、规则与执行流程全部通过 MCP 协商。"""
    lines = [
        "使用 Insight-Mobile MCP 编写下列 App 自动化用例脚本："
        "先 get_case_context，按返回的 workflow 探索并试跑入库；"
        "未注入 instructions 时先读 insight://mobile/instructions；Token 勿写入脚本。"
    ]
    lines += _access_lines(mcp_url=mcp_url, token=token)
    if case_id:
        lines.append(f"- case_id: {case_id}")
    return "\n".join(lines)


def render_fix_prompt(
    *,
    case_id: int | None = None,
    token: str = "",
    mcp_url: str = "",
) -> str:
    """修复脚本极简文案：用例、失败原因、环境与规则全部通过 MCP 协商。"""
    lines = [
        "使用 Insight-Mobile MCP 修复下列 App 自动化用例脚本："
        "先 get_case_context 与 read_staging_file，按返回的 workflow 最小修复并试跑入库；"
        "未注入 instructions 时先读 insight://mobile/instructions；Token 勿写入脚本。"
    ]
    lines += _access_lines(mcp_url=mcp_url, token=token)
    if case_id:
        lines.append(f"- case_id: {case_id}")
    return "\n".join(lines)


def render_session_prompt(
    *,
    kind: str,
    case_id: int | None = None,
    token: str = "",
    mcp_url: str = "",
) -> str:
    fn = render_fix_prompt if kind == "fix" else render_create_prompt
    return fn(case_id=case_id, token=token, mcp_url=mcp_url)
