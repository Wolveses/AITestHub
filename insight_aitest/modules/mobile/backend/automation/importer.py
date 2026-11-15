# -*- coding: utf-8 -*-
"""从知识库用例文档（kind=case）导入手机 App 自动化用例快照。"""

from __future__ import annotations

import logging
import re

from insight_aitest.modules.mobile.backend.persistence.database import MobileDatabase
from insight_aitest.modules.mobile.backend.persistence.models import CaseStatus, MobilePlatform

logger = logging.getLogger(__name__)

_STEP_PREFIX = re.compile(r"^\s*(?:\d+[.、)）]|[-*])\s*")
IOS_KEYWORDS = ("ios", "iphone", "ipad", "apple", "苹果")


def classify_platform(title: str, category_path: str = "") -> str:
    text = f"{title or ''}\n{category_path or ''}".lower()
    if any(k in text for k in IOS_KEYWORDS):
        return MobilePlatform.IOS
    return MobilePlatform.ANDROID


def _clean(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", (text or "").strip())


def _section(body: str, name: str) -> str:
    m = re.search(rf"^##\s*{re.escape(name)}\s*$", body, re.M)
    if not m:
        return ""
    rest = body[m.end() :]
    nxt = re.search(r"^##\s+\S+", rest, re.M)
    return _clean(rest[: nxt.start()] if nxt else rest)


def _steps_of(body: str) -> list[str]:
    raw = _section(body, "测试步骤")
    steps = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        line = _STEP_PREFIX.sub("", line).strip()
        if line:
            steps.append(line)
    return steps


def parse_case_markdown(body: str) -> dict:
    title = ""
    m = re.search(r"^#\s+(?:\[用例\s*#[^\]]+\]\s*)?(.+)$", body or "", re.M)
    if m:
        title = m.group(1).strip()
    return {
        "title": title,
        "precondition": _section(body, "前置条件"),
        "steps": _steps_of(body),
        "expected": _section(body, "预期结果"),
    }


def list_importable(
    project_id: int,
    db: MobileDatabase,
    search: str = "",
    category_path: str = "",
    page: int = 1,
    page_size: int = 200,
) -> dict:
    from insight_aitest.platform.services.kb.deps import get_kb_db

    kb = get_kb_db()
    rows, total = kb.list_case_documents(
        project_id,
        search=search,
        category_path=category_path,
        page=page,
        page_size=page_size,
    )
    imported = db.imported_doc_ids(project_id)
    items = []
    for d, meta in rows:
        title = (meta.title or d.filename) or ""
        items.append(
            {
                "document_id": d.id,
                "title": title,
                "case_id": meta.case_id,
                "workspace_id": meta.workspace_id,
                "category_path": meta.category_path,
                "status": meta.status,
                "priority": meta.priority,
                "step_count": meta.step_count,
                "folder_id": getattr(d, "folder_id", None),
                "imported": d.id in imported,
                "suggested_platform": classify_platform(title, meta.category_path),
            }
        )
    folders = [
        {"path": path, "count": count}
        for path, count in kb.case_category_counts(project_id, search=search)
        if path
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "all_total": kb.count_case_documents(project_id, search=search),
        "folders": folders,
    }


def import_cases(
    project_id: int,
    document_ids: list[int],
    db: MobileDatabase,
    platform_map: dict[int, str] | None = None,
) -> dict:
    from insight_aitest.platform.services.kb.deps import get_kb_db

    kb = get_kb_db()
    created, skipped, failed = 0, 0, []
    for doc_id in document_ids:
        if db.get_case_by_doc(project_id, doc_id) is not None:
            skipped += 1
            continue
        doc = kb.get_document(doc_id)
        if doc is None or getattr(doc, "kind", "doc") != "case":
            failed.append({"document_id": doc_id, "reason": "不是知识库用例文档"})
            continue
        meta = kb.get_case_meta(doc_id)
        try:
            parsed = parse_case_markdown(kb.get_document_content(doc_id))
        except Exception as e:
            logger.warning("导入用例文档 %s 正文解析失败: %s", doc_id, e)
            parsed = {"title": "", "precondition": "", "steps": [], "expected": ""}

        title = parsed["title"] or (meta.title if meta else "") or doc.filename
        category_path = meta.category_path if meta else ""
        platform = (platform_map or {}).get(doc_id) or classify_platform(title, category_path)
        if platform not in MobilePlatform.ALL:
            platform = MobilePlatform.ANDROID
        db.create_case(
            project_id=project_id,
            kb_document_id=doc_id,
            source_case_id=meta.case_id if meta else "",
            source_workspace_id=meta.workspace_id if meta else "",
            title=title,
            precondition=parsed["precondition"],
            steps=parsed["steps"],
            expected=parsed["expected"],
            category_path=category_path,
            kb_folder_id=getattr(doc, "folder_id", None),
            platform=platform,
            status=CaseStatus.NOT_IMPLEMENTED,
        )
        created += 1
    return {"created": created, "skipped": skipped, "failed": failed}
