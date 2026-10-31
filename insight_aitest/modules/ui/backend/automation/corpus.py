# -*- coding: utf-8 -*-
"""同目录参考脚本：把已验证通过的脚本源码喂给模型，压缩重复探索成本。

检索策略：同项目同目录（category_path）优先，不足时退化为同端（site），
再按「标题 + 前置条件 + 步骤 + 预期结果」的文本相似度排序，取前几个。
"""

from __future__ import annotations

import difflib
import re

from insight_aitest.modules.ui.backend.automation import paths

MAX_REFERENCES = 4
SCRIPT_CHAR_LIMIT = 6000
TOTAL_CHAR_LIMIT = 14000
# 老流程机制生成的脚本是 flows.* 的薄包装，参考价值低且会诱导模型写不可用的 import
_LEGACY_FLOW_RE = re.compile(r"^\s*(?:from|import)\s+flows", re.MULTILINE)


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


def reference_scripts(case, db, limit: int = TOTAL_CHAR_LIMIT) -> str:
    """返回可直接拼进提示词的参考脚本片段；无可用参考时返回空串。"""
    try:
        items, _ = db.list_cases(project_id=int(case.project_id), page_size=200)
    except Exception:  # noqa: BLE001 - 参考脚本只是加速手段，取失败不影响生成
        return ""

    base = _text(case)
    folder = str(getattr(case, "category_path", "") or "")
    site = str(getattr(case, "site", "") or "")
    ranked: list[tuple[float, object, object]] = []
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
        score = difflib.SequenceMatcher(None, base, _text(other)).ratio()
        ranked.append((score + (0.5 if same_folder else 0.0), other, path))
    if not ranked:
        return ""
    ranked.sort(key=lambda row: row[0], reverse=True)

    blocks: list[str] = []
    used = 0
    for _, other, path in ranked:
        if len(blocks) >= MAX_REFERENCES:
            break
        try:
            source = path.read_text(encoding="utf-8")[:SCRIPT_CHAR_LIMIT]
        except OSError:
            continue
        if _LEGACY_FLOW_RE.search(source):
            continue
        block = (
            f"【参考脚本】《{other.title}》（目录：{other.category_path or '未分类'}）\n"
            f"```python\n{source}\n```"
        )
        if used + len(block) > limit:
            break
        used += len(block)
        blocks.append(block)
    return "\n\n".join(blocks)
