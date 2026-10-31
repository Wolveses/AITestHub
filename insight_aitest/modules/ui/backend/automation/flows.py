# -*- coding: utf-8 -*-
"""流程资产（ui_flows）：同目录同操作流程的用例复用一套脚本，差异走参数。

设计要点：
- 归属按用例库目录 id（``kb_folder_id``）匹配，目录改名不影响复用关系；
- 流程脚本是纯业务逻辑 ``run(page, params)``，模块级 ``FLOW`` 字面量声明元数据
  （key/title/route/keywords/params），读取时只用 ``ast.literal_eval``，不执行脚本；
- 复用打分 = 关键词 0.5 + 路由 0.3 + 动作动词 0.2；≥0.65 直接复用，
  0.40~0.65 交给一次纯文本分类调用（不拉浏览器工具），<0.40 新建流程。
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from insight_aitest.modules.ui.backend.automation import paths
from insight_aitest.modules.ui.backend.automation.models import UiFlow, UiFlowStatus

# 复用判定阈值
AUTO_THRESHOLD = 0.65
GRAY_LOW = 0.40

# 动作动词词典：用于判断「同一个操作流程」而不是「同一个页面」
ACTION_VERBS = (
    "新增",
    "添加",
    "创建",
    "新建",
    "编辑",
    "修改",
    "更新",
    "删除",
    "移除",
    "查询",
    "搜索",
    "筛选",
    "导入",
    "导出",
    "上传",
    "下载",
    "登录",
    "登出",
    "启用",
    "停用",
    "分配",
    "授权",
    "重置",
    "批量",
    "审批",
    "提交",
    "保存",
    "复制",
    "排序",
    "分页",
    "详情",
    "查看",
    "配置",
    "绑定",
    "解绑",
)

_FLOW_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_ROUTE_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9]{2,}")
_ROUTE_STOP_WORDS = {"manage", "index", "home", "login", "static", "assets", "api"}

PARAM_TYPES = ("str", "int", "bool", "select")


def normalize_params(schema: Any) -> list[dict]:
    """归一化参数结构，丢弃无名项，补齐默认字段（前端表格直接可用）。"""
    out: list[dict] = []
    for item in schema or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        kind = str(item.get("type") or "str").strip()
        options = item.get("options")
        out.append(
            {
                "name": name,
                "label": str(item.get("label") or name),
                "type": kind if kind in PARAM_TYPES else "str",
                "required": bool(item.get("required", False)),
                "default": item.get("default"),
                "example": str(item.get("example") or ""),
                "desc": str(item.get("desc") or ""),
                "unique": bool(item.get("unique", False)),
                "options": [str(o) for o in options] if isinstance(options, list) else [],
            }
        )
    return out


def read_flow_meta(source: str) -> dict | None:
    """从流程脚本里读取模块级 ``FLOW`` 字面量（AST 静态解析，不执行代码）。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(t, ast.Name) and t.id == "FLOW" for t in targets):
            continue
        value = node.value
        try:
            meta = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            continue
        if not isinstance(meta, dict):
            return None
        meta = dict(meta)
        meta["key"] = str(meta.get("key") or "").strip()
        meta["title"] = str(meta.get("title") or "").strip()
        meta["route"] = str(meta.get("route") or "").strip()
        kws = meta.get("keywords")
        meta["keywords"] = [str(k).strip() for k in kws if str(k).strip()] if isinstance(kws, list) else []
        meta["params"] = normalize_params(meta.get("params"))
        return meta
    return None


def case_text(case) -> str:
    """用例可匹配文本：标题 + 前置 + 步骤 + 预期 + 目录路径。"""
    parts = [
        str(getattr(case, "title", "") or ""),
        str(getattr(case, "precondition", "") or ""),
        "\n".join(str(s) for s in (getattr(case, "steps", None) or [])),
        str(getattr(case, "expected", "") or ""),
        str(getattr(case, "category_path", "") or ""),
    ]
    return "\n".join(parts).lower()


def _verbs_in(text: str) -> set[str]:
    return {v for v in ACTION_VERBS if v in text}


def _route_tokens(route: str) -> set[str]:
    tokens = {t.lower() for t in _ROUTE_TOKEN_RE.findall(route or "")}
    return {t for t in tokens if t not in _ROUTE_STOP_WORDS}


def score_flow(flow, case) -> tuple[float, dict]:
    """关键词 0.5 + 路由 0.3 + 动作动词 0.2（各项归一到 0~1）。"""
    text = case_text(case)
    keywords = [str(k).lower() for k in (flow.keywords or []) if str(k).strip()]
    if keywords:
        keyword_score = sum(1 for k in keywords if k in text) / len(keywords)
    else:
        keyword_score = 0.0

    route_tokens = _route_tokens(flow.route or "")
    route_score = 1.0 if route_tokens and any(t in text for t in route_tokens) else 0.0

    flow_verbs = _verbs_in(str(flow.title or "") + "".join(keywords))
    action_score = (
        len(flow_verbs & _verbs_in(text)) / len(flow_verbs) if flow_verbs else 0.0
    )

    total = 0.5 * keyword_score + 0.3 * route_score + 0.2 * action_score
    detail = {
        "keyword": round(keyword_score, 3),
        "route": round(route_score, 3),
        "action": round(action_score, 3),
    }
    return round(min(total, 1.0), 3), detail


def match_candidates(db, case) -> list[tuple[Any, float, dict]]:
    """同目录（按 kb_folder_id）下的 active 流程，按分数倒序。"""
    folder_id = int(getattr(case, "kb_folder_id", None) or 0)
    flows = db.list_flows(
        int(case.project_id), folder_id=folder_id, status=UiFlowStatus.ACTIVE
    )
    scored: list[tuple[Any, float, dict]] = []
    for flow in flows:
        if not flow.script_rel_path or not paths.resolve_rel(flow.script_rel_path).exists():
            continue
        score, detail = score_flow(flow, case)
        scored.append((flow, score, detail))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def classify_match(llm, case, candidates: list[tuple[Any, float, dict]]) -> Any | None:
    """灰区（0.40~0.65）的一次纯文本分类调用：不启动 MCP、不探索页面。"""
    if not candidates:
        return None
    lines = []
    for idx, (flow, _score, _detail) in enumerate(candidates):
        lines.append(
            f"{idx}. 流程「{flow.title}」 路由 {flow.route or '（未记录）'} "
            f"关键词：{'、'.join(str(k) for k in (flow.keywords or []))}"
        )
    prompt = (
        "你在判断 UI 自动化脚本能否复用。下面是待生成脚本的用例，以及同目录下已有的流程资产。\n"
        "复用条件：页面操作流程完全一致（同一页面、同样的操作顺序与字段），只有数据不同；\n"
        "若只是同一个页面但操作流程不同（如新增 vs 编辑、列表查询 vs 批量删除），则不复用。\n"
        "只输出 JSON：{\"index\": 0} 或 {\"index\": -1}，不要输出任何其他内容。\n\n"
        "用例：\n" + _case_brief_text(case) + "\n\n候选项：\n" + "\n".join(lines)
    )
    try:
        reply = llm.chat(
            [
                {"role": "system", "content": "你只输出一个 JSON 对象，不解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
    except Exception:
        return None
    data = _parse_json(reply)
    if not isinstance(data, dict):
        return None
    try:
        idx = int(data.get("index", -1))
    except (TypeError, ValueError):
        return None
    if 0 <= idx < len(candidates):
        return candidates[idx][0]
    return None


def _case_brief_text(case) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(case.steps or [], 1)) or "（无）"
    return (
        f"标题：{case.title}\n"
        f"前置：{case.precondition or '（无）'}\n"
        f"步骤：\n{steps}\n"
        f"预期：{case.expected or '（无）'}"
    )


def _parse_json(text: str) -> Any:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("\n") + 1 :] if "\n" in raw else raw
    decoder = json.JSONDecoder(strict=False)
    start = raw.find("{")
    while start >= 0:
        try:
            obj, _ = decoder.raw_decode(raw[start:])
            return obj
        except json.JSONDecodeError:
            start = raw.find("{", start + 1)
    return None


def validate_flow_key(flow_key: str) -> str:
    key = (flow_key or "").strip()
    if not _FLOW_KEY_RE.match(key):
        return "流程 key 必须是英文小写字母开头、仅含小写字母/数字/下划线的短标识（≤32 字符）"
    return ""


def flow_out(flow, case_count: int = 0, *include_source: bool) -> dict:
    """接口输出（默认不含脚本源码，详情接口再按需附带）。"""
    data = {
        "id": flow.id,
        "project_id": flow.project_id,
        "folder_id": flow.folder_id,
        "flow_key": flow.flow_key,
        "title": flow.title,
        "route": flow.route,
        "keywords": list(flow.keywords or []),
        "params_schema": normalize_params(flow.params_schema),
        "module": flow.module,
        "script_rel_path": flow.script_rel_path,
        "version": flow.version,
        "status": flow.status,
        "case_count": case_count,
        "updated_at": flow.updated_at.isoformat() if flow.updated_at else None,
        "created_at": flow.created_at.isoformat() if flow.created_at else None,
    }
    if include_source:
        p = paths.resolve_rel(flow.script_rel_path) if flow.script_rel_path else None
        data["source"] = p.read_text(encoding="utf-8") if p is not None and p.exists() else ""
    return data


def create_flow_record(
    db,
    *,
    project_id: int,
    folder_id: int,
    meta: dict,
    module: str,
    script_rel_path: str,
    version: int = 1,
) -> int:
    return db.create_flow(
        project_id=project_id,
        folder_id=int(folder_id or 0),
        flow_key=meta["key"],
        title=meta.get("title") or meta["key"],
        route=meta.get("route") or "",
        keywords=meta.get("keywords") or [],
        params_schema=meta.get("params") or [],
        module=module,
        script_rel_path=script_rel_path,
        version=int(version or 1),
        status=UiFlowStatus.ACTIVE,
    )
