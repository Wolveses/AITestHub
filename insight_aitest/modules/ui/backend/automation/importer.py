# -*- coding: utf-8 -*-
"""从知识库用例文档（kind=case）导入自动化用例。

知识库用例正文是固定 Markdown 模板（tapd_case_sync._build_markdown）：
``# [用例 #id] 标题`` + ``## 前置条件`` / ``## 测试步骤`` / ``## 预期结果``。
导入时做字段快照，之后与源文档不同步（源用例更新不会覆盖本地修改）。
"""

from __future__ import annotations

import json
import logging
import re

from insight_aitest.modules.ui.backend.automation.database import UIAutomationDatabase
from insight_aitest.modules.ui.backend.automation.models import CaseStatus, Site

logger = logging.getLogger(__name__)

DELETED_TAG = "deleted-in-tapd"
_STEP_PREFIX = re.compile(r"^\s*(?:\d+[.、)）]|[-*])\s*")

# 端关键字词典：后台优先级更高（后台命名通常更明确），命中后台即归后台
BACKEND_KEYWORDS = ("后台", "管理", "配置", "日志")
FRONTEND_KEYWORDS = ("前台", "操作界面", "操作页面", "首页")


def classify_site(title: str, category_path: str = "") -> str:
    """按标题 + 目录路径推断端；未命中任何词典默认前台。"""
    text = f"{title or ''}\n{category_path or ''}"
    if any(k in text for k in BACKEND_KEYWORDS):
        return Site.BACKEND
    if any(k in text for k in FRONTEND_KEYWORDS):
        return Site.FRONTEND
    return Site.FRONTEND


def _clean(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", (text or "").strip())


def _section(body: str, name: str) -> str:
    """取 ``## name`` 到下一个 ``## `` 之间的正文。"""
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
    """把用例 Markdown 解析成 {title, precondition, steps, expected}。"""
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


def _has_deleted_tag(tags: str) -> bool:
    try:
        vals = json.loads(tags) if tags else []
        return isinstance(vals, list) and DELETED_TAG in [str(v) for v in vals]
    except (json.JSONDecodeError, TypeError):
        return False


def _case_rows(project_id: int):
    """返回 (documents, case_meta_map)；过滤源端已删除/废弃用例。"""
    from insight_aitest.platform.services.kb.deps import get_kb_db

    kb = get_kb_db()
    docs, _total = kb.list_documents(
        project_id=project_id, kind="case", page=1, page_size=500, return_total=True
    )
    docs = [d for d in docs if not _has_deleted_tag(getattr(d, "tags", "") or "")]
    meta_map = kb.list_case_meta([d.id for d in docs]) if docs else {}
    return docs, meta_map


def list_importable(project_id: int, db: UIAutomationDatabase) -> list[dict]:
    """知识库中可导入的用例（已导入的带 imported=True 标记，前端置灰）。"""
    docs, meta_map = _case_rows(project_id)
    imported = db.imported_doc_ids(project_id)
    rows = []
    for d in docs:
        meta = meta_map.get(d.id)
        rows.append(
            {
                "document_id": d.id,
                "title": (meta.title if meta and meta.title else d.filename) or "",
                "case_id": meta.case_id if meta else "",
                "workspace_id": meta.workspace_id if meta else "",
                "category_path": meta.category_path if meta else "",
                "status": meta.status if meta else "",
                "priority": meta.priority if meta else "",
                "step_count": meta.step_count if meta else 0,
                "folder_id": getattr(d, "folder_id", None),
                "imported": d.id in imported,
                # 端推断结果，导入弹窗的二次分类确认页直接使用
                "suggested_site": classify_site(
                    (meta.title if meta and meta.title else d.filename) or "",
                    meta.category_path if meta else "",
                ),
            }
        )
    rows.sort(key=lambda r: (r["category_path"], r["title"]))
    return rows


def import_cases(
    project_id: int,
    document_ids: list[int],
    db: UIAutomationDatabase,
    site_map: dict[int, str] | None = None,
) -> dict:
    """批量导入用例快照；已导入的跳过，返回 created/skipped/failed。

    site_map 来自导入向导的二次分类确认（document_id → frontend/backend），
    未提供的文档按关键字词典推断。
    """
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
        except Exception as e:  # 解析失败不阻断整批
            logger.warning("导入用例文档 %s 正文解析失败: %s", doc_id, e)
            parsed = {"title": "", "precondition": "", "steps": [], "expected": ""}

        title = parsed["title"] or (meta.title if meta else "") or doc.filename
        category_path = meta.category_path if meta else ""
        site = (site_map or {}).get(doc_id) or classify_site(title, category_path)
        if site not in Site.ALL:
            site = Site.FRONTEND
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
            site=site,
            status=CaseStatus.NOT_IMPLEMENTED,
        )
        created += 1
    return {"created": created, "skipped": skipped, "failed": failed}
