# -*- coding: utf-8 -*-
"""TAPD 缺陷同步进知识库（P0）。

流程：按创建时间窗口分页拉取缺陷 → 转 Markdown → 写文件 → 注册 Document（kind=defect）
→ 写 DefectMeta → 分块并向量化（process_text）。

增量策略：
1. TAPD ``modified`` 与本地 ``source_modified_at`` 相同 → 直接跳过（省掉评论请求）；
2. 内容哈希相同 → 仅刷新文件名/修改时间/摘要，不重新向量化。

日志与异常消息只包含 workspace_id / bug_id / HTTP 状态码，绝不包含凭证。
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from insight_aitest.platform.services.kb.deps import (
    get_kb_db,
    get_llm,
    get_llm_config,
    get_vector_store,
)
from insight_aitest.platform.services.kb.ingest import process_text
from insight_aitest.platform.services.kb.models import DefectMeta, DocumentStatus
from insight_aitest.platform.services.tapd import TapdClient
from insight_aitest.platform.services.tapd.labels import (
    PRIORITY_LABELS,
    SEVERITY_LABELS,
    STATUS_LABELS,
    label,
)

logger = logging.getLogger(__name__)

_progress = {
    "running": False,
    "phase": "",  # scan=扫描源数据 / sync=写入需更新条目 / done=结束
    "scanned": 0,  # 扫描阶段已拉取条目数（此时总量未知）
    "total": 0,  # 需更新条目数（新增 + 源已变更），作进度分母
    "done": 0,
    "created": 0,
    "updated": 0,
    "skipped": 0,
    "failed": 0,
    "message": "",
}
_lock = threading.Lock()

_ILLEGAL_PATH_CHARS = re.compile(r'[\\/:*?"<>|]')
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_P_END_RE = re.compile(r"</p\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def sync_progress() -> dict:
    """返回同步进度副本。"""
    with _lock:
        return dict(_progress)


def try_acquire_sync() -> bool:
    """原子抢占同步执行权：已在运行返回 False，否则置位并清空计数。

    路由在启动线程前调用，避免「检查 running → 线程内置位」之间的竞态窗口。
    """
    with _lock:
        if _progress["running"]:
            return False
        _progress.update(
            {
                "running": True,
                "phase": "scan",
                "scanned": 0,
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


def _s(value: Any) -> str:
    """字段值转字符串，None 一律空串（避免正文出现 "None"）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _names(value: Any) -> str:
    """TAPD 多处理人用 ';' 分隔（常带尾分号），统一成中文顿号并去掉空项。"""
    raw = _s(value)
    if not raw:
        return ""
    return "、".join(p.strip() for p in raw.split(";") if p.strip())


def _safe_name(name: str) -> str:
    """清洗 Windows 非法文件名字符并截断，避免 Path 把 / 解析成目录。"""
    cleaned = _ILLEGAL_PATH_CHARS.sub("_", _s(name))
    cleaned = cleaned.strip().rstrip(" .")
    return (cleaned or "未命名")[:80]


def _html_to_text(raw: Any) -> str:
    """TAPD 富文本（HTML）转纯文本。"""
    text = _s(raw)
    if not text:
        return ""
    text = _SCRIPT_STYLE_RE.sub("", text)
    text = _IMG_RE.sub("[图片]", text)
    text = _BR_RE.sub("\n", text)
    text = _P_END_RE.sub("\n\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def _summary(bug: dict) -> str:
    """Document.description 一行摘要：状态 · 优先级 · 模块 · 处理人（空项跳过）。"""
    parts = [
        label(STATUS_LABELS, _s(bug.get("status"))),
        label(PRIORITY_LABELS, _s(bug.get("priority"))),
        _s(bug.get("module")),
        _names(bug.get("current_owner")),
    ]
    return " · ".join(p for p in parts if p)


def _title_line(bug_id: str, title: str) -> str:
    return f"# [缺陷 #{bug_id}] {title}"


def _field_line(pairs: list[tuple[str, str]]) -> str:
    """拼一行 "键: 值 | 键: 值"，空值字段直接省略，避免出现 "模块:  | 缺陷类型: "。"""
    return "- " + " | ".join(f"{k}: {v}" for k, v in pairs if v)


def _build_markdown(bug: dict, comments: list[dict]) -> str:
    """按固定模板生成缺陷 Markdown 正文（枚举值转中文，空字段省略）。"""
    bug_id = _s(bug.get("id"))
    title = _s(bug.get("title"))
    # TAPD 缺陷的「处理人」「创建人」分别是 current_owner / reporter；
    # module/iteration_id 未启用时为空或 "0"，一律不输出。
    iteration = _s(bug.get("iteration_id"))
    fields = [
        _field_line(
            [
                ("状态", label(STATUS_LABELS, _s(bug.get("status")))),
                ("优先级", label(PRIORITY_LABELS, _s(bug.get("priority")))),
                ("严重程度", label(SEVERITY_LABELS, _s(bug.get("severity")))),
            ]
        ),
        _field_line(
            [
                ("模块", _s(bug.get("module"))),
                ("缺陷类型", _s(bug.get("bugtype"))),
                ("处理人", _names(bug.get("current_owner"))),
                ("创建人", _names(bug.get("reporter"))),
            ]
        ),
        _field_line(
            [
                ("迭代", "" if iteration in ("", "0") else iteration),
                ("发现版本", _s(bug.get("version_report"))),
                ("修复版本", _s(bug.get("version_fix"))),
            ]
        ),
        _field_line(
            [
                ("创建时间", _s(bug.get("created"))),
                ("修改时间", _s(bug.get("modified"))),
            ]
        ),
    ]

    lines = [
        _title_line(bug_id, title),
        "",
        *[line for line in fields if line != "- "],
        "",
        "## 缺陷描述",
        "",
        _html_to_text(bug.get("description")),
        "",
        "## 评论历史",
        "",
    ]
    for c in comments:
        raw_text = c.get("description") or c.get("body") or ""
        text = re.sub(r"[ \t]*\n[ \t]*", " ", _html_to_text(raw_text)).strip()
        lines.append(f"- [{_s(c.get('created'))}] {_s(c.get('author'))}: {text}")
    return "\n".join(lines).strip() + "\n"


def _date_windows(start: date, end: date, span_days: int = 30) -> list[tuple[date, date]]:
    """把 [start, end] 切成不超过 span_days 天的窗口。"""
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        w_end = min(cursor + timedelta(days=span_days - 1), end)
        windows.append((cursor, w_end))
        cursor = w_end + timedelta(days=1)
    return windows


def sync_workspace(
    workspace_id: str,
    project_id: int,
    backfill_days: int | None = None,
    acquired: bool = False,
) -> dict:
    """同步指定 TAPD 工作空间的缺陷到知识库（同步阻塞，需在后台线程/线程池中调用）。

    acquired=True 表示调用方已通过 ``try_acquire_sync`` 抢占执行权（路由路径）。
    """
    client: TapdClient | None = None
    owned = acquired
    try:
        if not owned:
            if not try_acquire_sync():
                raise RuntimeError("TAPD 同步正在进行中")
            owned = True

        cfg = get_llm_config()
        client = TapdClient.from_config(cfg)
        if client is None:
            raise RuntimeError("TAPD 凭证未配置")

        db = get_kb_db()
        vector_store = get_vector_store()
        llm = get_llm()

        bugs: dict[str, dict] = {}
        if backfill_days is None:
            # 回填天数为空 → 全量同步：用极宽创建时间范围（接口要求带 created 过滤），一次翻页拉完
            for bug in client.list_bugs(
                workspace_id,
                "2000-01-01",
                date.today().isoformat(),
                on_page=lambda n: _set(scanned=n),
            ):
                bug_id = _s(bug.get("id"))
                if bug_id:
                    bugs[bug_id] = bug
            _set(scanned=len(bugs))
        else:
            end = date.today()
            start = end - timedelta(days=backfill_days)
            for w_start, w_end in _date_windows(start, end):
                for bug in client.list_bugs(workspace_id, w_start.isoformat(), w_end.isoformat()):
                    bug_id = _s(bug.get("id"))
                    if bug_id:
                        bugs[bug_id] = bug
                _set(scanned=len(bugs))

        # 预筛：只把「本地不存在」或「源修改时间已变化」的缺陷计入进度分母，
        # 顺带缓存已有文档，写循环不再重复查库。未变更的计入 skipped，口径与原来一致。
        targets: list[tuple[str, dict, Any]] = []
        unchanged = 0
        for bug_id, bug in bugs.items():
            external_id = f"tapd:{workspace_id}:{bug_id}"
            doc = db.find_by_external_id(external_id)
            if doc is not None and doc.source_modified_at == _s(bug.get("modified")):
                unchanged += 1
                continue
            targets.append((bug_id, bug, doc))
        _set(total=len(targets), done=0, skipped=unchanged, phase="sync")

        for bug_id, bug, doc in targets:
            try:
                external_id = f"tapd:{workspace_id}:{bug_id}"
                modified = _s(bug.get("modified"))

                try:
                    comments = client.list_comments(workspace_id, bug_id)
                except Exception as exc:
                    logger.warning(
                        "TAPD 评论拉取失败，降级为空 workspace_id=%s bug_id=%s error=%s",
                        workspace_id,
                        bug_id,
                        type(exc).__name__,
                    )
                    comments = []

                title = _s(bug.get("title"))
                markdown = _build_markdown(bug, comments)
                content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
                filename = f"{bug_id}_{_safe_name(title)}.md"
                summary = _summary(bug)

                if doc and doc.content_hash == content_hash:
                    db.update_source_document(
                        doc.id,
                        filename=filename,
                        source_modified_at=modified,
                        description=summary,
                    )
                    _inc("skipped")
                    continue

                base_dir = Path(cfg.docs_dir) / "tapd" / workspace_id
                base_dir.mkdir(parents=True, exist_ok=True)
                path = base_dir / filename
                # 标题变更会导致文件名变化；已有文档沿用原路径，避免 storage_path 悬空。
                if doc is not None and doc.storage_path:
                    old_path = Path(doc.storage_path)
                    if old_path.exists():
                        path = old_path
                tmp_path = path.with_name(path.name + ".tmp")
                tmp_path.write_text(markdown, encoding="utf-8")
                os.replace(tmp_path, path)

                source_url = (
                    f"https://www.tapd.cn/{workspace_id}/bugtrace/bugs/view?bug_id={bug_id}"
                )

                if doc is None:
                    doc_id = db.create_document(
                        filename=path.name,
                        storage_path=str(path),
                        content_hash=content_hash,
                        mime_type="text/markdown",
                        project_id=project_id,
                        source_type="tapd",
                        source_url=source_url,
                        external_id=external_id,
                        source_modified_at=modified,
                        kind="defect",
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
                    _inc("updated")

                db.upsert_defect_meta(
                    DefectMeta(
                        document_id=doc_id,
                        workspace_id=workspace_id,
                        defect_id=bug_id,
                        title=title,
                        status=_s(bug.get("status")),
                        priority=_s(bug.get("priority")),
                        severity=_s(bug.get("severity")),
                        module=_s(bug.get("module")),
                        bugtype=_s(bug.get("bugtype")),
                        owner=_names(bug.get("current_owner")),
                        creator=_names(bug.get("reporter")),
                        iteration_id=_s(bug.get("iteration_id")),
                        found_version=_s(bug.get("version_report")),
                        fix_version=_s(bug.get("version_fix")),
                        created_at_ext=_s(bug.get("created")),
                        modified_at_ext=modified,
                        comment_count=len(comments),
                    )
                )

                # 一条缺陷 = 一个 chunk（不再按 chunk_size 切分，避免同一缺陷被拆成多块）
                process_text(doc_id, [markdown], db, vector_store, llm, cfg)
                # 向量化不可用（模型缺失/额度问题）时降级为「未向量化」，与文档列表同一展示口径；
                # 失败原因仍保留在 error_message，便于排查和后续重新向量化。
                processed = db.get_document(doc_id)
                if processed is not None and processed.status == DocumentStatus.EMBED_FAILED:
                    db.update_document_status(
                        doc_id,
                        DocumentStatus.NOT_VECTORIZED,
                        error_message=processed.error_message,
                    )
            except Exception as exc:
                logger.error(
                    "TAPD 缺陷同步失败 workspace_id=%s bug_id=%s error=%s",
                    workspace_id,
                    bug_id,
                    type(exc).__name__,
                )
                _inc("failed")
            finally:
                _inc("done")
    finally:
        hits = int(getattr(client, "rate_limit_hits", 0) or 0)
        if client is not None:
            client.close()
        if owned:
            with _lock:
                _progress["running"] = False
                _progress["phase"] = "done"
                message = (
                    f"新增 {_progress['created']} / 更新 {_progress['updated']}"
                    f" / 跳过 {_progress['skipped']} / 失败 {_progress['failed']}"
                )
                if hits:
                    message += f"（限流重试 {hits} 次）"
                _progress["message"] = message

    return {
        "workspace_id": workspace_id,
        "total": _progress["total"],
        "created": _progress["created"],
        "updated": _progress["updated"],
        "skipped": _progress["skipped"],
        "failed": _progress["failed"],
    }
