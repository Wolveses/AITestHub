# -*- coding: utf-8 -*-
"""同目录参考片段：只喂「动作级」代码，避免整份脚本挤占上下文预算。

检索策略：同项目同目录（category_path）优先，不足时退化为同端（site）；
把已验证通过的脚本切成 5~15 行的动作片段（跳转/点击/输入/断言/选择/上传），
按「去重 + 用例相似度」排序，取前若干条，总量不超过 TOTAL_CHAR_LIMIT。
"""

from __future__ import annotations

import difflib
import re
import textwrap

from insight_aitest.modules.ui.backend.automation import paths

MAX_SNIPPETS = 10
MAX_PER_SOURCE = 3
TOTAL_CHAR_LIMIT = 4000
SNIPPET_LINES = 15
SNIPPET_CHAR_LIMIT = 900
# 老流程机制生成的脚本是 flows.* 的薄包装，参考价值低且会诱导模型写不可用的 import
_LEGACY_FLOW_RE = re.compile(r"^\s*(?:from|import)\s+flows", re.MULTILINE)

# 动作类型：片段按「动作 + 真实代码」组织，比整份脚本更容易被模型就地沿用
_ACTION_PATTERNS = (
    ("跳转", re.compile(r"\.goto\(")),
    ("点击", re.compile(r"\.click\(")),
    ("输入", re.compile(r"\.(?:fill|type)\(")),
    ("选择", re.compile(r"\.select_option\(")),
    ("上传", re.compile(r"\.set_input_files\(")),
    ("下载", re.compile(r"expect_download|\.download")),
    ("断言", re.compile(r"expect\(")),
    ("定位", re.compile(r"get_by_(?:role|label|text|testid)")),
)


def _text(case) -> str:
    steps = " ".join(str(s) for s in (getattr(case, "steps", None) or []))
    return " ".join(
        part
        for part in (
            str(getattr(case, "title", "") or ""),
            str(getattr(case, "precondition", "") or ""),
            steps,
            str(getattr(case, "expected", "") or ""),
        )
        if part
    )


def _action_of(line: str) -> str:
    for name, pattern in _ACTION_PATTERNS:
        if pattern.search(line):
            return name
    return ""


def _snippets(source: str) -> list[tuple[str, str]]:
    """把脚本切成动作片段：以动作行为锚点，向前 2 行、向后共 15 行。"""
    lines = source.splitlines()
    blocks: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        action = _action_of(line)
        if not action:
            continue
        start = max(0, index - 2)
        end = min(len(lines), index + SNIPPET_LINES - 2)
        # 片段太短说明后面紧跟着空行/函数结束，向前补足 5 行保证上下文完整
        if end - start < 5:
            start = max(0, end - 5)
            end = min(len(lines), start + 5)
        block = textwrap.dedent("\n".join(lines[start:end]).rstrip())
        if len(block.strip()) < 3:
            continue
        blocks.append((action, block[:SNIPPET_CHAR_LIMIT]))
    return blocks


def reference_snippets(case, db, limit: int = TOTAL_CHAR_LIMIT) -> str:
    """返回可直接拼进提示词的参考片段；无可用参考时返回空串。"""
    try:
        items, _ = db.list_cases(project_id=int(case.project_id), page_size=200)
    except Exception:  # noqa: BLE001 - 参考片段只是加速手段，取失败不影响生成
        return ""

    base = _text(case)
    folder = str(getattr(case, "category_path", "") or "")
    site = str(getattr(case, "site", "") or "")
    ranked: list[tuple[float, object, tuple[str, str]]] = []
    for other in items:
        if int(other.id) == int(case.id) or not other.script_rel_path:
            continue
        same_folder = str(other.category_path or "") == folder
        same_site = str(other.site or "") == site
        if not same_folder and not same_site:
            continue
        path = paths.resolve_rel(other.script_rel_path)
        if not path.exists():
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _LEGACY_FLOW_RE.search(source):
            continue
        case_score = difflib.SequenceMatcher(None, base, _text(other)).ratio()
        for action, block in _snippets(source):
            score = difflib.SequenceMatcher(None, base, block).ratio()
            score += case_score + (0.25 if same_folder else 0.0)
            ranked.append((score, other, (action, block)))
    if not ranked:
        return ""

    ranked.sort(key=lambda row: row[0], reverse=True)
    seen: set[str] = set()
    per_source: dict[int, int] = {}
    blocks: list[str] = []
    used = 0
    for _, other, (action, block) in ranked:
        if len(blocks) >= MAX_SNIPPETS:
            break
        key = re.sub(r"\s+", " ", block).strip()
        if key in seen:
            continue
        source_id = int(other.id)
        if per_source.get(source_id, 0) >= MAX_PER_SOURCE:
            continue
        header = (
            f"【参考片段】动作：{action}｜来源《{other.title}》"
            f"（目录：{other.category_path or '未分类'}）"
        )
        text = f"{header}\n```python\n{block}\n```"
        if used + len(text) > limit:
            break
        seen.add(key)
        per_source[source_id] = per_source.get(source_id, 0) + 1
        used += len(text)
        blocks.append(text)
    return "\n\n".join(blocks)
