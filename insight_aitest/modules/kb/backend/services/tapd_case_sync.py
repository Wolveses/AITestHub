# -*- coding: utf-8 -*-
"""TAPD 测试用例同步进知识库（P0 + P1）。

与缺陷同步（tapd_sync.py）同构，但多一层目录树：
1. 全量拉取用例目录（/tcase_categories），按 parent_id 还原层级写入 kb_folders；
2. 按创建/修改时间窗口拉取用例（/tcases），一条用例 = 一个 Document（kind=case）= 一个 chunk；
3. 用例通过 category_id 挂到对应目录，目录缺失时置空（未分类），不丢数据。

增量策略：
- L1 水位：kb_tapd_sync_state 记录上次同步的最大 modified，下次按 modified 窗口拉取；
- L2 时间戳：本地 source_modified_at 与 TAPD modified 相同 → 直接跳过；
- L3 内容哈希：Markdown 哈希相同 → 只刷新元数据，不重建分块、不重新向量化；
- 删除差集：仅在「未做条数截断」的全量同步时比对，给消失的用例打 deleted-in-tapd 标签（不物理删除）。

日志与异常只包含 workspace_id / case_id / 阶段名，绝不包含凭证。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from insight_aitest.modules.kb.backend.services.tapd_sync import (
    _date_windows,
    _html_to_text,
    _safe_name,
    _s,
)
from insight_aitest.platform.services.kb.deps import (
    get_kb_db,
    get_llm,
    get_llm_config,
    get_vector_store,
)
from insight_aitest.platform.services.kb.ingest import process_text
from insight_aitest.platform.services.kb.models import CaseMeta, DocumentStatus
from insight_aitest.platform.services.tapd import TapdClient
from insight_aitest.platform.services.tapd.labels import TCASE_STATUS_LABELS, label

logger = logging.getLogger(__name__)

DELETED_TAG = "deleted-in-tapd"
_FOLDER_SOURCE = "tapd_case"

_progress = {
    "running": False,
    "phase": "",
    "folders_total": 0,
    "folders_done": 0,
    "total": 0,
    "done": 0,
    "created": 0,
    "updated": 0,
    "skipped": 0,
    "failed": 0,
    "message": "",
}
_lock = threading.Lock()


def case_progress() -> dict:
    """返回用例同步进度副本。"""
    with _lock:
        return dict(_progress)


def try_acquire_case_sync() -> bool:
    """原子抢占用例同步执行权（与缺陷同步各自独立，可并行）。"""
    with _lock:
        if _progress["running"]:
            return False
        _progress.update(
            {
                "running": True,
                "phase": "folders",
                "folders_total": 0,
                "folders_done": 0,
                "total": 0,
                "done": 0,
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "failed": 0,
                "message": "",
            }
        )
        return True


def _inc(field: str, n: int = 1) -> None:
    with _lock:
        _progress[field] += n


def _set(**kwargs: Any) -> None:
    with _lock:
        _progress.update(kwargs)


# ===== 文本构建 =====


def _steps_text(raw: Any) -> tuple[list[str], int]:
    """把 TAPD 的 steps（HTML 或纯文本）拆成有序步骤行，返回 (行列表, 有效步骤数)。"""
    text = _html_to_text(raw)
    if not text:
        return [], 0
    lines: list[str] = []
    for chunk in text.split("\n"):
        line = chunk.strip().lstrip("0123456789.、) ").strip()
        if line:
            lines.append(line)
    return lines, len(lines)


def _category_path(category_id: str, cat_map: dict[str, dict]) -> str:
    """沿 parent_id 向上回溯出目录全路径（根 → 叶）。"""
    cid = (category_id or "").strip()
    if not cid or cid in ("0", "-1") or cid not in cat_map:
        return ""
    names: list[str] = []
    seen: set[str] = set()
    while cid and cid not in ("0", "-1") and cid not in seen:
        seen.add(cid)
        node = cat_map.get(cid)
        if node is None:
            break
        name = _s(node.get("name"))
        if name:
            names.append(name)
        cid = _s(node.get("parent_id"))
    return " / ".join(reversed(names))


def _summary(case: dict) -> str:
    """Document.description 一行摘要：状态 · 优先级 · 类型 · 维护人（空项跳过）。"""
    parts = [
        label(TCASE_STATUS_LABELS, _s(case.get("status"))),
        _s(case.get("priority")),
        _s(case.get("type")),
        _s(case.get("modifier")),
    ]
    return " · ".join(p for p in parts if p)


def _build_markdown(case: dict, category_path: str) -> tuple[str, int]:
    """按固定模板生成用例 Markdown，返回 (正文, 步骤数)。"""
    case_id = _s(case.get("id"))
    title = _s(case.get("name")) or "未命名用例"
    status_cn = label(TCASE_STATUS_LABELS, _s(case.get("status")))
    steps, step_count = _steps_text(case.get("steps"))
    expectation = _html_to_text(case.get("expectation"))

    field_lines: list[str] = []

    def field_line(pairs: list[tuple[str, str]]) -> None:
        text = " | ".join(f"{k}: {v}" for k, v in pairs if v)
        if text:
            field_lines.append(f"- {text}")

    field_line([("状态", status_cn), ("优先级", _s(case.get("priority"))), ("类型", _s(case.get("type")))])
    field_line(
        [
            ("归属目录", category_path),
            ("维护人", _s(case.get("modifier"))),
            ("创建人", _s(case.get("creator"))),
        ]
    )
    field_line([("创建时间", _s(case.get("created"))), ("修改时间", _s(case.get("modified")))])

    lines = [
        f"# [用例 #{case_id}] {title}",
        "",
        *field_lines,
        "",
        "## 前置条件",
        "",
        _html_to_text(case.get("precondition")),
        "",
        "## 测试步骤",
        "",
    ]
    if steps:
        lines.extend(f"{i}. {line}" for i, line in enumerate(steps, 1))
    lines.extend(["", "## 预期结果", "", expectation])
    return "\n".join(lines).strip() + "\n", step_count


# ===== 目录同步 =====


def _sync_folders(
    db: Any,
    workspace_id: str,
    project_id: int,
    categories: list[dict],
) -> dict[str, int]:
    """把 TAPD 目录树写入 kb_folders，返回 {category_id: folder_id} 映射。"""
    cat_map: dict[str, dict] = {}
    for cat in categories:
        cid = _s(cat.get("id"))
        if cid:
            cat_map[cid] = cat

    # 按层级深度排序，保证父目录先落库
    def depth_of(cid: str) -> int:
        depth = 0
        seen: set[str] = set()
        cur = cid
        while cur and cur not in ("0", "-1") and cur not in seen:
            seen.add(cur)
            node = cat_map.get(cur)
            if node is None:
                break
            depth += 1
            cur = _s(node.get("parent_id"))
            if depth > 100:
                break
        return depth

    ordered = sorted(cat_map.values(), key=lambda c: depth_of(_s(c.get("id"))))
    _set(folders_total=len(ordered))

    mapping: dict[str, int] = {}
    for cat in ordered:
        cid = _s(cat.get("id"))
        name = _s(cat.get("name")) or "未命名目录"
        # external_id 带项目维度：同一 workspace 同步到不同项目时各自保留一棵树
        external_id = f"tapd:{workspace_id}:{project_id}:{cid}"
        parent_folder_id = mapping.get(_s(cat.get("parent_id")))

        existing = db.find_folder_by_external_id(external_id)
        if existing is None:
            folder = db.create_folder(
                name=name,
                parent_id=parent_folder_id,
                project_id=project_id,
                source_type=_FOLDER_SOURCE,
                external_id=external_id,
            )
            folder_id = folder.id
        else:
            folder_id = existing.id
            changed = existing.name != name or existing.parent_id != parent_folder_id
            if changed:
                db.update_folder(folder_id, name=name, parent_id=parent_folder_id)
        mapping[cid] = folder_id
        _inc("folders_done")
    return mapping


# ===== 用例同步 =====


def _mark_deleted(db: Any, doc: Any, deleted: bool) -> None:
    """给文档打/去 deleted-in-tapd 标签（软删除，保留执行历史与正文）。"""
    try:
        tags = json.loads(doc.tags) if getattr(doc, "tags", "") else []
        if not isinstance(tags, list):
            tags = []
    except (json.JSONDecodeError, TypeError):
        tags = []
    current = [str(t) for t in tags]
    has_tag = DELETED_TAG in current
    if deleted and not has_tag:
        current.append(DELETED_TAG)
    elif not deleted and has_tag:
        current = [t for t in current if t != DELETED_TAG]
    else:
        return
    db.update_document_meta(doc.id, tags=json.dumps(current, ensure_ascii=False))


def sync_tcase_workspace(
    workspace_id: str,
    project_id: int,
    backfill_days: int | None = None,
    max_cases: int | None = None,
    acquired: bool = False,
) -> dict:
    """同步指定 TAPD 工作空间的测试用例到知识库（同步阻塞，需在后台线程调用）。

    ``max_cases`` 用于首次小批量验证：截断时不做删除差集，避免误标。
    """
    client: TapdClient | None = None
    owned = acquired
    try:
        if not owned:
            if not try_acquire_case_sync():
                raise RuntimeError("TAPD 用例同步正在进行中")
            owned = True

        cfg = get_llm_config()
        client = TapdClient.from_config(cfg)
        if client is None:
            raise RuntimeError("TAPD 凭证未配置")

        db = get_kb_db()
        vector_store = get_vector_store()
        llm = get_llm()

        # 1. 目录全量对齐
        _set(phase="folders")
        categories = client.list_tcase_categories(workspace_id)
        cat_map = {_s(c.get("id")): c for c in categories if _s(c.get("id"))}
        folder_map = _sync_folders(db, workspace_id, project_id, categories)

        # 1.5 清理历史上已废弃的用例文档：水位增量同步不会回看旧用例，
        #     若不主动清理，早前入库的废弃用例会一直留在库里
        for doc_id in db.list_abandoned_case_doc_ids(workspace_id, project_id):
            try:
                vector_store.delete_document(doc_id)
            except Exception:  # noqa: BLE001
                logger.warning("清理已废弃用例向量失败 doc_id=%s", doc_id)
            db.delete_document(doc_id)

        # 2. 用例拉取（有水位走 modified 窗口，否则按创建时间回填）
        _set(phase="cases")
        end = date.today()
        watermark = db.get_tapd_watermark(workspace_id, project_id, "case") if max_cases is None else ""
        cases: dict[str, dict] = {}
        truncated = False
        if watermark:
            try:
                start_wm = datetime.strptime(watermark, "%Y-%m-%d %H:%M:%S") - timedelta(minutes=5)
                start = start_wm.date()
            except ValueError:
                start = end - timedelta(days=backfill_days or cfg.tapd_backfill_days)
            # 从最近的时间窗口往回拉，尽快凑满本次上限，减少无效请求
            for w_start, w_end in reversed(_date_windows(start, end)):
                remaining = None if max_cases is None else max(0, max_cases - len(cases))
                if remaining == 0:
                    truncated = True
                    break
                fetched = client.list_tcases(
                    workspace_id,
                    modified_from=w_start.isoformat(),
                    modified_to=w_end.isoformat(),
                    page_size=200,
                    limit=remaining,
                )
                for case in fetched:
                    cid = _s(case.get("id"))
                    if cid:
                        cases[cid] = case
                time.sleep(0.5)
        else:
            days = backfill_days or cfg.tapd_backfill_days
            start = end - timedelta(days=days)
            for w_start, w_end in reversed(_date_windows(start, end)):
                remaining = None if max_cases is None else max(0, max_cases - len(cases))
                if remaining == 0:
                    truncated = True
                    break
                fetched = client.list_tcases(
                    workspace_id,
                    created_from=w_start.isoformat(),
                    created_to=w_end.isoformat(),
                    page_size=200,
                    limit=remaining,
                )
                for case in fetched:
                    cid = _s(case.get("id"))
                    if cid:
                        cases[cid] = case
                if max_cases is not None and len(cases) >= max_cases:
                    truncated = True
                    break
                time.sleep(0.5)

        _set(total=len(cases))

        # 3. 逐条落库
        seen_external: set[str] = set()
        max_modified = ""
        for case_id, case in cases.items():
            try:
                external_id = f"tapd:{workspace_id}:{project_id}:{case_id}"
                seen_external.add(external_id)
                doc = db.find_by_external_id(external_id)

                # 已废弃用例不入库；此前已同步过的旧文档一并清理，避免继续被检索命中
                if _s(case.get("status")) == "abandon":
                    if doc is not None:
                        try:
                            vector_store.delete_document(doc.id)
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "清理已废弃用例向量失败 doc_id=%s case_id=%s",
                                doc.id,
                                case_id,
                            )
                        db.delete_document(doc.id)
                    _inc("skipped")
                    continue

                modified = _s(case.get("modified"))
                if modified > max_modified:
                    max_modified = modified

                if doc and doc.source_modified_at == modified:
                    _inc("skipped")
                    continue

                title = _s(case.get("name")) or "未命名用例"
                category_id = _s(case.get("category_id"))
                category_path = _category_path(category_id, cat_map)
                markdown, step_count = _build_markdown(case, category_path)
                content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
                filename = f"{case_id}_{_safe_name(title)}.md"
                summary = _summary(case)

                if doc and doc.content_hash == content_hash:
                    db.update_source_document(
                        doc.id,
                        filename=filename,
                        source_modified_at=modified,
                        description=summary,
                    )
                    _mark_deleted(db, doc, False)
                    _inc("skipped")
                    continue

                base_dir = Path(cfg.docs_dir) / "tapd_cases" / workspace_id
                base_dir.mkdir(parents=True, exist_ok=True)
                path = base_dir / filename
                if doc is not None and doc.storage_path:
                    old_path = Path(doc.storage_path)
                    if old_path.exists():
                        path = old_path
                tmp_path = path.with_name(path.name + ".tmp")
                tmp_path.write_text(markdown, encoding="utf-8")
                os.replace(tmp_path, path)

                source_url = (
                    f"https://www.tapd.cn/{workspace_id}/prong/testcases/view/{case_id}"
                )
                folder_id = folder_map.get(category_id)

                if doc is None:
                    doc_id = db.create_document(
                        filename=path.name,
                        storage_path=str(path),
                        content_hash=content_hash,
                        mime_type="text/markdown",
                        project_id=project_id,
                        folder_id=folder_id,
                        source_type="tapd",
                        source_url=source_url,
                        external_id=external_id,
                        source_modified_at=modified,
                        kind="case",
                    )
                    _inc("created")
                else:
                    doc_id = doc.id
                    db.update_source_document(
                        doc_id,
                        filename=path.name,
                        content_hash=content_hash,
                        source_modified_at=modified,
                        description=summary,
                    )
                    if folder_id:
                        db.move_document(doc_id, folder_id)
                    _mark_deleted(db, doc, False)
                    _inc("updated")

                db.upsert_case_meta(
                    CaseMeta(
                        document_id=doc_id,
                        workspace_id=workspace_id,
                        case_id=case_id,
                        title=title,
                        status=_s(case.get("status")),
                        priority=_s(case.get("priority")),
                        case_type=_s(case.get("type")),
                        category_id=category_id,
                        category_path=category_path,
                        owner=_s(case.get("modifier")),
                        creator=_s(case.get("creator")),
                        step_count=step_count,
                        created_at_ext=_s(case.get("created")),
                        modified_at_ext=modified,
                    )
                )

                # 一条用例 = 一个 chunk；超长由正文自身段落结构承载，不再二次切分
                process_text(doc_id, [markdown], db, vector_store, llm, cfg)
                processed = db.get_document(doc_id)
                if processed is not None and processed.status == DocumentStatus.EMBED_FAILED:
                    db.update_document_status(
                        doc_id,
                        DocumentStatus.NOT_VECTORIZED,
                        error_message=processed.error_message,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "TAPD 用例同步失败 workspace_id=%s case_id=%s error=%s",
                    workspace_id,
                    case_id,
                    type(exc).__name__,
                )
                _inc("failed")
            finally:
                _inc("done")

        # 4. 删除差集（仅首次全量且未截断时）
        # 水位增量只拉最近修改过的用例，seen_external 天然不全，不能据此判定删除
        if not truncated and not watermark:
            try:
                local_items = db.list_documents(project_id=project_id, kind="case")
                for item in local_items:
                    ext = _s(getattr(item, "external_id", ""))
                    if not ext.startswith(f"tapd:{workspace_id}:{project_id}:"):
                        continue
                    if ext not in seen_external and getattr(item, "source_type", "") == "tapd":
                        _mark_deleted(db, item, True)
            except Exception:
                logger.warning("TAPD 用例删除差集比对失败，已跳过 workspace_id=%s", workspace_id)

        # 5. 水位
        if max_modified:
            db.upsert_tapd_watermark(workspace_id, project_id, "case", max_modified)

        return {
            "workspace_id": workspace_id,
            "folders": len(folder_map),
            "total": _progress["total"],
            "created": _progress["created"],
            "updated": _progress["updated"],
            "skipped": _progress["skipped"],
            "failed": _progress["failed"],
        }
    finally:
        if client is not None:
            client.close()
        if owned:
            with _lock:
                _progress["running"] = False
                _progress["phase"] = "done"
                _progress["message"] = (
                    f"目录 {_progress['folders_done']} / 新增 {_progress['created']}"
                    f" / 更新 {_progress['updated']} / 跳过 {_progress['skipped']}"
                    f" / 失败 {_progress['failed']}"
                )
