# -*- coding: utf-8 -*-
"""知识库文档上传/列表/详情/删除/重建索引 + 预览/导出/编辑/标签/版本。

从 ai 模块迁移为独立 kb 模块。底层 KBDatabase/VectorStore 已是平台服务
（platform.services.kb），文档操作通过平台单例进行。

KB 升级新增：project_id/version_id 分类筛选 + 上传时关联项目 +
文档预览/导出/编辑 + 标签与元数据管理 + 版本管理。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import uuid
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from insight_aitest.platform.services.llm.config import AIConfig
from insight_aitest.platform.services.kb.database import KBDatabase
from insight_aitest.platform.services.kb.models import DocumentStatus
from insight_aitest.platform.services.kb.loader import get_loader
from insight_aitest.platform.services.kb.loader.base import UnsupportedFormatError
from insight_aitest.platform.services.kb.ingest import process_document
from insight_aitest.platform.services.tapd.labels import (
    PRIORITY_LABELS,
    SEVERITY_LABELS,
    STATUS_LABELS,
    label,
)
from insight_aitest.modules.ai.backend.deps import get_config, get_kb_db, get_llm, get_vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["kb-documents"])


class DefectOut(BaseModel):
    """缺陷结构化摘要（来自 kb_defect_meta，列表页直接展示，无需解析正文）。"""

    defect_id: str = ""
    workspace_id: str = ""
    status: str = ""
    priority: str = ""
    severity: str = ""
    module: str = ""
    owner: str = ""
    created_at: str = ""
    modified_at: str = ""
    comment_count: int = 0


class DocumentOut(BaseModel):
    id: int
    filename: str
    status: str
    char_count: int
    chunk_count: int
    error_message: str | None
    project_id: int | None = None
    version_id: int | None = None
    folder_id: int | None = None
    tags: list[str] = []
    doc_type: str = ""
    description: str = ""
    source_type: str = "local"
    source_url: str = ""
    external_id: str = ""
    kind: str = "doc"
    defect: DefectOut | None = None
    created_at: str
    # 后台重解析进行中：内存标记，早于 status 变为 pending，供前端展示解析中并置灰操作
    reindexing: bool = False

    @classmethod
    def from_doc(cls, doc, defect: "DefectOut | None" = None) -> "DocumentOut":
        # tags 列存 JSON 数组字符串，解析为 list；解析失败降级空列表
        try:
            tags = json.loads(doc.tags) if getattr(doc, "tags", "") else []
            if not isinstance(tags, list):
                tags = []
        except (json.JSONDecodeError, TypeError):
            tags = []
        return cls(
            id=doc.id,
            filename=doc.filename,
            status=doc.status.value,
            char_count=doc.char_count,
            chunk_count=doc.chunk_count,
            error_message=doc.error_message,
            project_id=doc.project_id,
            version_id=doc.version_id,
            folder_id=getattr(doc, "folder_id", None),
            tags=[str(t) for t in tags],
            doc_type=getattr(doc, "doc_type", "") or "",
            description=getattr(doc, "description", "") or "",
            source_type=getattr(doc, "source_type", "local") or "local",
            source_url=getattr(doc, "source_url", "") or "",
            external_id=getattr(doc, "external_id", "") or "",
            kind=getattr(doc, "kind", "doc") or "doc",
            defect=defect,
            created_at=doc.created_at.isoformat(),
        )


def _doc_to_out(doc, defect: "DefectOut | None" = None) -> DocumentOut:
    out = DocumentOut.from_doc(doc, defect)
    out.reindexing = is_reindexing(doc.id)
    return out


def _defect_to_out(meta) -> DefectOut:
    return DefectOut(
        defect_id=meta.defect_id,
        workspace_id=meta.workspace_id,
        # 库里存 TAPD 原始枚举值，展示层统一转中文
        status=label(STATUS_LABELS, meta.status),
        priority=label(PRIORITY_LABELS, meta.priority),
        severity=label(SEVERITY_LABELS, meta.severity),
        module=meta.module,
        owner=meta.owner,
        created_at=meta.created_at_ext,
        modified_at=meta.modified_at_ext,
        comment_count=meta.comment_count,
    )


def resolve_storage_path(storage_path_str: str) -> Path:
    """解析文档物理文件路径，支持跨机器迁移环境自动回退。"""
    p = Path(storage_path_str)
    if p.exists():
        return p

    # 回退尝试 1：当前用户的 ~/.insight_eye/ai_docs/ 下
    base_docs_dir = Path.home() / ".insight_eye" / "ai_docs"
    fallback = base_docs_dir / p.name
    if fallback.exists():
        return fallback

    # 回退尝试 2：飞书同步子目录 ~/.insight_eye/ai_docs/feishu/ 下
    feishu_fallback = base_docs_dir / "feishu" / p.name
    if feishu_fallback.exists():
        return feishu_fallback

    return p


class MoveDocumentIn(BaseModel):
    folder_id: int | None = None


@router.get("", response_model=dict)
def list_documents(
    project_id: int | None = None,
    version_id: int | None = None,
    folder_id: int | None = None,
    source_type: str | None = None,
    kind: str | None = None,
    search: str | None = None,
    doc_type: str | None = None,
    tags: list[str] | None = None,
    page: int = 1,
    page_size: int = 20,
    db: KBDatabase = Depends(get_kb_db),
) -> dict:
    items, total = db.list_documents(
        project_id=project_id,
        version_id=version_id,
        folder_id=folder_id,
        source_type=source_type,
        kind=kind,
        search=search,
        doc_type=doc_type,
        tags=tags,
        page=page,
        page_size=page_size,
        return_total=True,
    )
    # 缺陷行直接带上结构化摘要，列表页无需再解析正文
    defect_map = db.list_defect_meta([d.id for d in items]) if items else {}
    return {
        "items": [
            _doc_to_out(d, _defect_to_out(defect_map[d.id]) if d.id in defect_map else None)
            for d in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/{doc_id}/move", response_model=DocumentOut)
def move_document(
    doc_id: int,
    body: MoveDocumentIn,
    db: KBDatabase = Depends(get_kb_db),
) -> DocumentOut:
    ok = db.move_document(doc_id, body.folder_id)
    if not ok:
        raise HTTPException(404, "文档不存在")
    return _doc_to_out(db.get_document(doc_id))


@router.post("", response_model=DocumentOut)
async def upload_document(
    file: UploadFile,
    project_id: int | None = None,
    version_id: int | None = None,
    folder_id: int | None = None,
    db: KBDatabase = Depends(get_kb_db),
    cfg: AIConfig = Depends(get_config),
) -> DocumentOut:
    # 1. 校验扩展名
    try:
        get_loader(file.filename or "")
    except UnsupportedFormatError:
        raise HTTPException(400, f"不支持的文件格式: {file.filename}")

    # 2. 读内容 + 校验大小
    content = await file.read()
    if len(content) > cfg.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"文件超过 {cfg.max_upload_mb}MB 限制")

    # 3~5. 去重 / 存原始文件 / 入库（同步 IO 统一放线程池，避免阻塞事件循环）
    def _store() -> tuple[int | None, DocumentOut]:
        content_hash = hashlib.sha256(content).hexdigest()
        existing = db.find_by_content_hash(content_hash)
        if existing:
            return None, _doc_to_out(existing)
        ext = Path(file.filename or "").suffix
        docs_dir = Path(cfg.docs_dir)
        docs_dir.mkdir(parents=True, exist_ok=True)
        storage_path = docs_dir / f"{uuid.uuid4().hex}{ext}"
        storage_path.write_bytes(content)
        doc_id = db.create_document(
            file.filename,
            str(storage_path),
            content_hash,
            file.content_type,
            project_id=project_id,
            version_id=version_id,
            folder_id=folder_id,
        )
        return doc_id, _doc_to_out(db.get_document(doc_id))

    doc_id, out = await asyncio.to_thread(_store)
    if doc_id is None:
        return out

    # 6. 后台线程处理
    def _bg():
        try:
            llm = get_llm()
            vs = get_vector_store()
            process_document(doc_id, db, vs, llm, cfg)
        except Exception as e:
            db.update_document_status(
                doc_id, DocumentStatus.PARSE_FAILED, error_message=f"处理异常: {e}"
            )

    threading.Thread(target=_bg, daemon=True).start()

    return out


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: KBDatabase = Depends(get_kb_db)) -> DocumentOut:
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    return _doc_to_out(doc)


@router.delete("/{doc_id}")
def delete_document(
    doc_id: int, db: KBDatabase = Depends(get_kb_db), vs=Depends(get_vector_store)
) -> dict:
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    # 删向量（必须先于删 chunks，因 vec0 不走 CASCADE）
    try:
        vs.delete_document(doc_id)
    except Exception:
        # 向量残留会导致已删文档继续被 RAG 引用，必须留痕
        logger.warning("删除文档 %s 的向量失败，可能残留脏向量", doc_id, exc_info=True)
    # 删原始文件
    try:
        Path(doc.storage_path).unlink(missing_ok=True)
    except Exception:
        pass
    db.delete_document(doc_id)
    return {"deleted": doc_id}


# 并发守护：同一文档同一时刻只允许一个重解析任务。
# 多用户同时点同一文档 / 批量与单文档交叉触发时，重复任务会重复清块、
# 重复调 embedding，并互相覆盖文档状态，因此在入口处占用槽位。
_reindex_lock = threading.Lock()
_reindex_inflight: set[int] = set()


def _reserve_reindex(doc_id: int) -> bool:
    """占用文档的重解析槽位；已被占用返回 False。"""
    with _reindex_lock:
        if doc_id in _reindex_inflight:
            return False
        _reindex_inflight.add(doc_id)
        return True


def _release_reindex(doc_id: int) -> None:
    with _reindex_lock:
        _reindex_inflight.discard(doc_id)


def is_reindexing(doc_id: int) -> bool:
    """文档当前是否有重解析任务在跑（供批量入口跳过）。"""
    with _reindex_lock:
        return doc_id in _reindex_inflight


@router.post("/{doc_id}/reindex", response_model=DocumentOut)
def reindex_document(doc_id: int, db: KBDatabase = Depends(get_kb_db), cfg=Depends(get_config)) -> DocumentOut:
    """重新索引（删旧向量与 chunks，后台重新解析向量化）。

    RAG 关闭时仍执行：清旧分块 → 重新解析分块 → 跳过向量化 → 状态 NOT_VECTORIZED。
    向量化表是否存在由 _reindex_in_bg 内部查表决定，不依赖 cfg.vector_enabled。
    """
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    if not _reserve_reindex(doc_id):
        raise HTTPException(409, "该文档正在重新解析中，请稍后再试")
    threading.Thread(target=_reindex_in_bg, args=(doc_id, db, True), daemon=True).start()
    return _doc_to_out(db.get_document(doc_id))


# ===== KB 升级：预览 / 导出 / 编辑 / 标签 / 版本 =====


def _reindex_in_bg(doc_id: int, db: KBDatabase, reserved: bool = False) -> None:
    """后台重新索引文档（删旧 chunks+向量 → 重新解析分块向量化）。复用 ingest 管线。

    reserved=True 表示调用方已占用 _reindex_inflight 槽位（单文档入口）；
    批量、编辑、版本回滚等入口在此尝试占用，已被占用则直接跳过，
    避免多用户重复触发同一文档的解析与向量化。
    """
    if not reserved and not _reserve_reindex(doc_id):
        logger.info("文档 %s 已在重新解析中，跳过重复任务", doc_id)
        return
    try:
        llm = get_llm()
        vs = get_vector_store()
        cfg = get_config()
        # 先清旧 chunks + 向量（与 reindex 端点同逻辑）
        conn = db.get_connection()
        chunk_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM chunks WHERE document_id = ?", (doc_id,)
            ).fetchall()
        ]
        # 清旧向量：表存在 → 临时 load vec0 扩展 → 清
        # 不依赖 db._vec_available（RAG 开关），否则关 RAG 期间 reindex 会残留孤儿向量
        has_vec_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_embeddings'"
        ).fetchone()
        if has_vec_table and db._ensure_vec_extension(conn):
            for cid in chunk_ids:
                conn.execute("DELETE FROM chunk_embeddings WHERE chunk_id = ?", (cid,))
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        conn.commit()
        db.update_document_status(doc_id, DocumentStatus.PENDING)
        process_document(doc_id, db, vs, llm, cfg)
    except Exception as e:
        logger.exception("重新索引失败 doc_id=%s", doc_id)
        db.update_document_status(
            doc_id, DocumentStatus.EMBED_FAILED, error_message=f"重新索引失败: {e}"
        )
    finally:
        _release_reindex(doc_id)


# ----- 预览 -----


@router.get("/{doc_id}/content")
def get_document_content(doc_id: int, db: KBDatabase = Depends(get_kb_db)) -> dict:
    """返回文档解析后的纯文本（拼接 chunks）。用于前端预览/编辑加载。"""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    text = db.get_document_content(doc_id)
    return {
        "document_id": doc_id,
        "filename": doc.filename,
        "mime_type": doc.mime_type,
        "text": text,
        "char_count": len(text),
    }


@router.get("/{doc_id}/chunks")
def list_document_chunks(doc_id: int, db: KBDatabase = Depends(get_kb_db)) -> dict:
    """返回文档的全部分块列表（只读，供前端诊断分块效果）。"""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    chunks = db.get_chunks_by_document(doc_id)
    items = [
        {
            "chunk_index": c.chunk_index,
            "text": c.text,
            "char_start": c.char_start,
            "char_end": c.char_end,
            "embed_status": c.embed_status.value if c.embed_status else None,
        }
        for c in chunks
    ]
    by_status: dict[str, int] = {}
    for it in items:
        key = it["embed_status"] or "pending"
        by_status[key] = by_status.get(key, 0) + 1
    return {"document_id": doc_id, "filename": doc.filename, "total": len(items), "by_status": by_status, "items": items}


# ----- 导出 -----


@router.get("/{doc_id}/raw")
def download_document_raw(doc_id: int, db: KBDatabase = Depends(get_kb_db)) -> FileResponse:
    """下载文档原始文件（保留原扩展名）。"""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    path = resolve_storage_path(doc.storage_path)
    if not path.exists():
        raise HTTPException(404, "原始文件不存在（可能已被删除）")
    return FileResponse(
        str(path), filename=doc.filename, media_type=doc.mime_type or "application/octet-stream"
    )


@router.get("/export/zip")
def export_documents_zip(
    project_id: int | None = None,
    version_id: int | None = None,
    db: KBDatabase = Depends(get_kb_db),
) -> StreamingResponse:
    """批量导出文档为 zip（按项目/版本过滤）。流式下载。"""
    docs = db.list_documents(project_id=project_id, version_id=version_id)
    if not docs:
        raise HTTPException(404, "没有可导出的文档")

    def _gen():
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for doc in docs:
                p = resolve_storage_path(doc.storage_path)
                if p.exists():
                    # 文件名去重：同名文件加 id 前缀
                    arcname = f"{doc.id}_{doc.filename}"
                    zf.write(str(p), arcname)
        buf.seek(0)
        yield from buf

    return StreamingResponse(
        _gen(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=kb_export.zip"},
    )


# ----- 编辑保存 -----


class DocumentContentUpdate(BaseModel):
    """编辑保存请求体。text 用于纯文本编辑；file 为二进制替换（FormData 走另一端点）。"""

    text: str
    note: str = ""  # 版本说明


@router.put("/{doc_id}/content", response_model=DocumentOut)
def update_document_content(
    doc_id: int,
    body: DocumentContentUpdate,
    db: KBDatabase = Depends(get_kb_db),
) -> DocumentOut:
    """编辑保存（纯文本）：保留旧版本快照 → 替换 chunks 文本 → 后台 reindex。

    适用 txt/md/html 等纯文本格式。二进制格式（docx/xlsx）用 /raw 下载编辑后走上传替换。
    """
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")

    # 1. 保留旧版本快照（旧 chunks 拼成的文本 → 新版本文件）
    old_text = db.get_document_content(doc_id)
    if old_text:
        old_path = Path(doc.storage_path)
        # 旧文本另存为版本文件
        version_dir = old_path.parent / "versions"
        version_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = version_dir / f"{doc_id}_v{uuid.uuid4().hex[:8]}{old_path.suffix}"
        snapshot_path.write_text(old_text, encoding="utf-8")
        db.create_version_snapshot(
            doc_id,
            str(snapshot_path),
            hashlib.sha256(old_text.encode()).hexdigest(),
            len(old_text),
            doc.chunk_count,
            note=body.note or "编辑前快照",
        )

    # 2. 替换 chunks 文本 + 同步原始文件
    db.replace_document_content(doc_id, body.text)
    # 同步写回原始文件（保持 storage_path 与内容一致）
    try:
        Path(doc.storage_path).write_text(body.text, encoding="utf-8")
    except Exception:
        # 写回失败意味着文件与 DB 内容分叉，预览/导出会拿到旧文本
        logger.warning("文档 %s 内容写回原始文件失败", doc_id, exc_info=True)

    # 3. 后台 reindex
    threading.Thread(target=_reindex_in_bg, args=(doc_id, db), daemon=True).start()
    return _doc_to_out(db.get_document(doc_id))


@router.put("/{doc_id}/file", response_model=DocumentOut)
async def update_document_file(
    doc_id: int,
    file: UploadFile,
    note: str = "二进制编辑保存",
    db: KBDatabase = Depends(get_kb_db),
    cfg: AIConfig = Depends(get_config),
) -> DocumentOut:
    """编辑保存（二进制文件 docx/xlsx）：保留旧版本快照 → 写新文件 → reindex。

    前端在线编辑器（SuperDoc/Univer）导出 Blob 后通过 FormData 上传到此端点。
    """
    doc = await asyncio.to_thread(db.get_document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")

    content = await file.read()
    if len(content) > cfg.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"文件超过 {cfg.max_upload_mb}MB 限制")

    # 1~2. 版本快照 + 写新文件 + 更新记录（同步 IO 统一放线程池）
    def _save() -> DocumentOut:
        old_path = Path(doc.storage_path)
        if old_path.exists():
            version_dir = old_path.parent / "versions"
            version_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = version_dir / f"{doc_id}_v{uuid.uuid4().hex[:8]}{old_path.suffix}"
            snapshot_path.write_bytes(old_path.read_bytes())
            db.create_version_snapshot(
                doc_id,
                str(snapshot_path),
                doc.content_hash,
                doc.char_count,
                doc.chunk_count,
                note=note,
            )

        # 保留原扩展名，写入新的 storage_path
        ext = Path(doc.filename).suffix
        new_path = old_path.parent / f"{uuid.uuid4().hex}{ext}"
        new_path.write_bytes(content)
        new_hash = hashlib.sha256(content).hexdigest()
        db.update_document_file(doc_id, str(new_path), new_hash)
        return _doc_to_out(db.get_document(doc_id))

    out = await asyncio.to_thread(_save)

    # 3. 后台 reindex
    threading.Thread(target=_reindex_in_bg, args=(doc_id, db), daemon=True).start()
    return out


# ----- 标签与元数据 -----


class DocumentMetaUpdate(BaseModel):
    tags: list[str] | None = None
    doc_type: str | None = None
    description: str | None = None


@router.put("/{doc_id}/meta", response_model=DocumentOut)
def update_document_meta(
    doc_id: int,
    body: DocumentMetaUpdate,
    db: KBDatabase = Depends(get_kb_db),
) -> DocumentOut:
    """更新文档标签/类型/描述。tags 存 JSON 数组字符串。"""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    tags_str = json.dumps(body.tags, ensure_ascii=False) if body.tags is not None else None
    db.update_document_meta(
        doc_id, tags=tags_str, doc_type=body.doc_type, description=body.description
    )
    return _doc_to_out(db.get_document(doc_id))


@router.get("/tags/all")
def list_all_tags(
    project_id: int | None = None, db: KBDatabase = Depends(get_kb_db)
) -> list[dict]:
    """聚合返回所有标签及计数（供标签云）。"""
    return db.list_tags(project_id=project_id)


# ----- 版本管理 -----


class VersionOut(BaseModel):
    id: int
    document_id: int
    version_no: int
    char_count: int
    chunk_count: int
    note: str
    is_current: int
    created_at: str

    @classmethod
    def from_version(cls, v) -> "VersionOut":
        return cls(
            id=v.id,
            document_id=v.document_id,
            version_no=v.version_no,
            char_count=v.char_count,
            chunk_count=v.chunk_count,
            note=v.note or "",
            is_current=v.is_current,
            created_at=v.created_at.isoformat(),
        )


@router.get("/{doc_id}/versions", response_model=list[VersionOut])
def list_document_versions(
    doc_id: int, db: KBDatabase = Depends(get_kb_db)
) -> list[VersionOut]:
    """列出文档的版本历史（按版本号降序）。"""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    return [VersionOut.from_version(v) for v in db.list_versions(doc_id)]


@router.get("/{doc_id}/versions/{version_no}/content")
def get_version_content(
    doc_id: int, version_no: int, db: KBDatabase = Depends(get_kb_db)
) -> dict:
    """读取指定历史版本的纯文本内容（用于版本对比）。"""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    v = db.get_version(doc_id, version_no)
    if v is None:
        raise HTTPException(404, "版本不存在")
    # 从快照文件读取
    path = Path(v.storage_path)
    text = ""
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            # 二进制快照无法直接读文本
            text = ""
    return {
        "document_id": doc_id,
        "version_no": version_no,
        "text": text,
        "char_count": v.char_count,
        "note": v.note,
        "created_at": v.created_at.isoformat(),
    }


@router.post("/{doc_id}/rollback/{version_no}", response_model=DocumentOut)
def rollback_to_version(
    doc_id: int, version_no: int, db: KBDatabase = Depends(get_kb_db)
) -> DocumentOut:
    """回滚到指定版本：当前内容另存快照 → 目标版本写回 → 后台 reindex。"""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    target = db.rollback_version(doc_id, version_no)
    if target is None:
        raise HTTPException(404, "版本不存在")
    # 后台 reindex
    threading.Thread(target=_reindex_in_bg, args=(doc_id, db), daemon=True).start()
    return _doc_to_out(db.get_document(doc_id))
