# -*- coding: utf-8 -*-
"""反面样本（错题库）：把失败日志 / 踩过的坑 / 解决方案沉淀成可注入的语料。

体积控制（持续积累时必须守住）：
- 单条正文截断 ≤ 700 字；
- 每项目上限 300 条，超出按「命中次数最少 + 最久未更新」淘汰；
- 每次注入 top 5，总量 ≤ 2500 字。
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import re

logger = logging.getLogger(__name__)

MAX_ENTRY_CHARS = 700
MAX_ENTRIES_PER_PROJECT = 300
MAX_INJECT = 5
MAX_INJECT_CHARS = 2500

_CATEGORY_LABEL = {
    "environment": "环境",
    "case_info": "用例信息",
    "model": "模型",
    "script": "脚本",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _truncate(text: str, limit: int = MAX_ENTRY_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 12] + "\n…（已截断）"


def _fingerprint(category: str, text: str) -> str:
    norm = _normalize(text)[:MAX_ENTRY_CHARS]
    return hashlib.sha256(f"{category}|{norm}".encode("utf-8")).hexdigest()[:32]


def _first_line(text: str) -> str:
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "")


def _case_text(case) -> str:
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


def record_failure(db, case, category: str, message: str) -> None:
    """把一次生成/执行失败沉淀成反面样本（同内容按指纹去重，不重复膨胀）。"""
    try:
        body = _truncate(message)
        if not body:
            return
        title = f"[{_CATEGORY_LABEL.get(category, category or '未知')}] {_first_line(body)[:80]}"
        db.upsert_lesson(
            int(case.project_id), _fingerprint(category, body), category or "", title, body
        )
        db.trim_lessons(int(case.project_id), MAX_ENTRIES_PER_PROJECT)
    except Exception:  # noqa: BLE001 - 错题库只是增强手段，写失败不能影响生成主链路
        logger.exception("写入反面样本失败 case=%s", getattr(case, "id", "?"))


def record_solution(db, case, category: str, failure: str, solution: str) -> None:
    """失败后修复通过：把「踩的坑 + 解决方案」合成一条样本。"""
    try:
        body = _truncate(f"失败：{_first_line(failure) or failure}\n解决方案：{solution}")
        if not body:
            return
        title = f"[{_CATEGORY_LABEL.get(category, category or '未知')}] 首跑失败后修复通过"
        db.upsert_lesson(
            int(case.project_id), _fingerprint(category, body), category or "", title, body
        )
        db.trim_lessons(int(case.project_id), MAX_ENTRIES_PER_PROJECT)
    except Exception:  # noqa: BLE001
        logger.exception("写入修复样本失败 case=%s", getattr(case, "id", "?"))


def relevant_lessons(case, db) -> str:
    """按用例文本相似度 + 历史命中次数挑 top 5 注入；无样本时返回空串。"""
    try:
        entries = db.list_lessons(int(case.project_id), MAX_ENTRIES_PER_PROJECT)
    except Exception:  # noqa: BLE001
        return ""
    if not entries:
        return ""

    base = _case_text(case)
    ranked: list[tuple[float, object]] = []
    for entry in entries:
        text = f"{entry.title} {entry.content}"
        score = difflib.SequenceMatcher(None, base, text).ratio()
        score += min(int(entry.hits or 0), 10) * 0.02
        ranked.append((score, entry))
    ranked.sort(key=lambda row: row[0], reverse=True)

    blocks: list[str] = []
    picked: list[int] = []
    used = 0
    for _, entry in ranked:
        if len(blocks) >= MAX_INJECT:
            break
        label = _CATEGORY_LABEL.get(entry.category, entry.category or "经验")
        body = _truncate(entry.content)
        block = f"- 【{label}】{entry.title}\n  " + body.replace("\n", "\n  ")
        if used + len(block) > MAX_INJECT_CHARS:
            break
        used += len(block)
        blocks.append(block)
        picked.append(int(entry.id))
    if not blocks:
        return ""
    try:
        db.bump_lesson_hits(picked)
    except Exception:  # noqa: BLE001 - 计数失败不影响本次注入
        pass
    return "\n".join(blocks)
