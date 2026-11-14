# -*- coding: utf-8 -*-
"""本地 Agent 文案的唯一渲染器：REST 粘贴文案与 MCP prompts 共用。"""

from __future__ import annotations

from collections.abc import Iterable

BATCH_SIZE = 50


def parse_case_ids(raw: str) -> list[int]:
    """解析逗号分隔的 case_ids：忽略非法项、按出现顺序去重。"""
    out: list[int] = []
    seen: set[int] = set()
    for part in str(raw or "").replace(" ", "").split(","):
        if not part.isdigit():
            continue
        cid = int(part)
        if cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


def _access_lines(*, mcp_url: str, token: str) -> list[str]:
    lines: list[str] = []
    if mcp_url:
        lines.append(f"- MCP: {mcp_url} (Streamable HTTP)")
    if token:
        lines.append(f"- Authorization: Bearer {token}")
    else:
        # 原生 MCP prompt：客户端已持有连接，不要伪造 Token
        lines.append("- 连接: 沿用当前 MCP 会话（无需额外 Token）")
    return lines


def _id_lines(case_ids: Iterable[int]) -> list[str]:
    ids = list(case_ids)
    lines = ["- case_ids: " + ",".join(str(i) for i in ids)]
    if len(ids) > BATCH_SIZE:
        lines.append(f"- triage 分批: 每批最多 {BATCH_SIZE} 个")
    return lines


def render_auto_prompt(
    case_ids: Iterable[int], token: str = "", mcp_url: str = "", mode: str = "auto"
) -> str:
    """新建、修复、重新生成共用同一套本地 Agent 文案（由 ui.case.triage 自动分诊）。"""
    del mode  # 统一文案：ui.case.triage 已把通过/无失败的已实现用例自动分诊为 regenerate
    ids = list(case_ids)
    lines = [
        "使用 Insight-AITest MCP 处理下列 UI 自动化用例：先 ui.case.triage；"
        "按返回 action 与 ui.contract.get 的 workflow 逐例串行执行；"
        "未注入 instructions 时先读 insight://instructions；Token 勿写入脚本。"
    ]
    lines += _access_lines(mcp_url=mcp_url, token=token)
    lines += _id_lines(ids)
    return "\n".join(lines)


def render_create_prompt(case_ids: Iterable[int], token: str = "", mcp_url: str = "") -> str:
    ids = list(case_ids)
    lines = [
        "使用 Insight-AITest MCP 为下列用例编写脚本并入库：按 ui.contract.get 返回的 "
        "ui.create workflow 执行；规则见 rules / insight://rules；Token 勿写入脚本。"
    ]
    lines += _access_lines(mcp_url=mcp_url, token=token)
    lines += _id_lines(ids)
    return "\n".join(lines)


def render_regenerate_prompt(case_ids: Iterable[int], token: str = "", mcp_url: str = "") -> str:
    """重新生成与新建/修复共用同一套文案（保留函数名兼容旧调用点）。"""
    return render_auto_prompt(case_ids, token=token, mcp_url=mcp_url)


def render_fix_prompt(case_ids: Iterable[int], token: str = "", mcp_url: str = "") -> str:
    ids = list(case_ids)
    lines = [
        "使用 Insight-AITest MCP 修复下列用例并重新入库：先 ui.run.latest，再按 "
        "ui.contract.get 返回的 ui.fix workflow 执行；以现有脚本为基线最小修改，"
        "禁止删除或放宽断言；run=null 时按 create 流程；Token 勿写入脚本。"
    ]
    lines += _access_lines(mcp_url=mcp_url, token=token)
    lines += _id_lines(ids)
    return "\n".join(lines)
