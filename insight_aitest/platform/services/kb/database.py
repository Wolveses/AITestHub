# -*- coding: utf-8 -*-
"""平台知识库数据库（KBDatabase，spec P0-1 ORM 迁移）。

从 ai 模块上提：只管 documents/chunks/chunk_embeddings + 索引 + sqlite-vec。
ai 模块的 AIDatabase 瘦身为只管 conversations/messages。
独立 kb.db 文件（~/.insight_eye/kb.db）。

P0-1：documents/chunks 走平台 ORM（session_scope）；chunk_embeddings（vec0 虚拟表）
仍走原生 sqlite3 通道（sqlite-vec 扩展运行时加载，ORM 无法管理虚拟表）。
``get_connection()`` 保留——vector_store.py / retriever / documents 路由的原生 SQL
（含 vec0 + chunks/documents 三表 JOIN）依赖它，签名不变、内部透明。
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING

from sqlalchemy import select

from insight_aitest.platform.persistence import Base, get_engine, session_scope
from insight_aitest.platform.services.kb.models import (
    Chunk,
    Document,
    DocumentStatus,
    DocumentVersion,
    EmbedStatus,
    Folder,
)

# 模块级：确保同一 db_path 的 schema 迁移只跑一次（防止并发 KBDatabase() 时
# 多个线程同时执行 _ensure_document_meta_columns → duplicate column name）
_schema_ready: set[str] = set()
_schema_lock = threading.Lock()

logger = logging.getLogger(__name__)


def _is_windows_path(raw: str) -> bool:
    """判断是否为 Windows 风格路径（盘符 C:\\ / C:/ 或 UNC \\\\server）。"""
    return bool(re.match(r"^[A-Za-z]:[\\/]", raw)) or raw.startswith("\\\\")


def _to_posix(raw: str) -> str:
    """统一为 / 分隔的路径字符串（入库与跨平台比对统一使用）。

    Windows 的 str(Path) 产出反斜杠，而 Win32 API 与 pathlib 同时接受 /，
    因此库里统一存 / 后，跨机迁移只需一套前缀规则。
    Windows 文件名不允许含反斜杠，故在 Windows 上归一不会有歧义；
    POSIX 主机上非 Windows 风格路径由 PosixPath 原样保留（含反斜杠的文件名不受影响）。
    """
    if not raw:
        return raw
    if _is_windows_path(raw):
        return PureWindowsPath(raw).as_posix()
    return Path(raw).as_posix()



def _ensure_project_columns(db_path: str) -> None:
    """增量迁移：给旧 documents 表补 project_id/version_id 列（幂等）。

    sqlite < 3.35 无 ADD COLUMN IF NOT EXISTS，用 PRAGMA 检查列是否已存在。
    """
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        if "project_id" not in cols:
            conn.execute("ALTER TABLE documents ADD COLUMN project_id INTEGER")
        if "version_id" not in cols:
            conn.execute("ALTER TABLE documents ADD COLUMN version_id INTEGER")
        conn.commit()


def tokenize_for_fts(text: str) -> str:
    """为 FTS5 全文倒排索引构建分词：连续英文/数字/特殊符号保留原形，中文字符切为 2-gram（bigram）。

    无需外部 C/Rust 分词扩展，原生兼容 SQLite FTS5 unicode61 分词器。
    """
    if not text:
        return ""
    tokens: list[str] = []
    # 提取连续英文数字标识符（含型号、版本、IP、带下划线/星号/点的标记）与连续中文字符串
    segments = re.findall(r"[a-zA-Z0-9_\.\*\\:\-]+|[\u4e00-\u9fff]+", text)
    for seg in segments:
        if re.match(r"^[a-zA-Z0-9_\.\*\\:\-]+$", seg):
            tokens.append(seg.lower())
        else:
            if len(seg) == 1:
                tokens.append(seg)
            else:
                for i in range(len(seg) - 1):
                    tokens.append(seg[i : i + 2])
    return " ".join(tokens)


def _ensure_fts5_table(db_path: str) -> None:
    """增量迁移：创建并同步 SQLite FTS5 全文倒排索引表与级联触发器（幂等）。"""
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        # 1. 检查或创建 chunks_fts 虚拟表
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_id UNINDEXED,
                document_id UNINDEXED,
                project_id UNINDEXED,
                indexed_tokens,
                tokenize='unicode61'
            )
            """
        )

        # 2. 创建触发器：当 chunks 物理行被删除时，自动删除对应 chunks_fts
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_chunks_delete_fts AFTER DELETE ON chunks
            BEGIN
                DELETE FROM chunks_fts WHERE chunk_id = OLD.id;
            END;
            """
        )

        # 3. 存量数据检查与补全：若 chunks 有数据但 chunks_fts 为空，执行一次性增量补录
        has_chunks = conn.execute("SELECT 1 FROM chunks LIMIT 1").fetchone()
        if has_chunks:
            fts_count = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
            if fts_count == 0:
                rows = conn.execute(
                    """
                    SELECT c.id, c.document_id, d.project_id, c.text
                    FROM chunks c
                    LEFT JOIN documents d ON c.document_id = d.id
                    """
                ).fetchall()
                fts_inserts = [
                    (r[0], r[1], r[2], tokenize_for_fts(r[3] or ""))
                    for r in rows
                ]
                if fts_inserts:
                    conn.executemany(
                        "INSERT INTO chunks_fts (chunk_id, document_id, project_id, indexed_tokens) VALUES (?, ?, ?, ?)",
                        fts_inserts,
                    )
        conn.commit()


def _ensure_document_meta_columns(db_path: str) -> None:
    """增量迁移：给 documents 表补 tags/doc_type/description 列（KB 升级，幂等）。

    tags 存 JSON 数组字符串；doc_type/description 存纯文本。旧数据 NULL → 空串。
    """
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        if "tags" not in cols:
            conn.execute("ALTER TABLE documents ADD COLUMN tags TEXT DEFAULT ''")
        if "doc_type" not in cols:
            conn.execute("ALTER TABLE documents ADD COLUMN doc_type TEXT DEFAULT ''")
        if "description" not in cols:
            conn.execute("ALTER TABLE documents ADD COLUMN description TEXT DEFAULT ''")
        if "folder_id" not in cols:
            conn.execute("ALTER TABLE documents ADD COLUMN folder_id INTEGER")
        if "source_type" not in cols:
            conn.execute("ALTER TABLE documents ADD COLUMN source_type TEXT DEFAULT 'local'")
        if "source_url" not in cols:
            conn.execute("ALTER TABLE documents ADD COLUMN source_url TEXT DEFAULT ''")
        if "external_id" not in cols:
            conn.execute("ALTER TABLE documents ADD COLUMN external_id TEXT DEFAULT ''")
        if "source_modified_at" not in cols:
            conn.execute("ALTER TABLE documents ADD COLUMN source_modified_at TEXT DEFAULT NULL")
        
        # kb_folders 表补 source_type 与 external_id
        folder_cols = {row[1] for row in conn.execute("PRAGMA table_info(kb_folders)")}
        if "source_type" not in folder_cols:
            conn.execute("ALTER TABLE kb_folders ADD COLUMN source_type TEXT DEFAULT 'local'")
        if "external_id" not in folder_cols:
            conn.execute("ALTER TABLE kb_folders ADD COLUMN external_id TEXT DEFAULT ''")

        # 存量迁移：上传时 vector_enabled=False 的文档 status=ready 但 chunks 全 pending
        #   → 改 status='not_vectorized'（新语义更准确，前端显示"未向量化"而非"已入库"）
        try:
            has_chunks = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'"
            ).fetchone()
            if has_chunks:
                conn.execute(
                    """UPDATE documents
                       SET status = 'not_vectorized'
                       WHERE status = 'ready'
                         AND NOT EXISTS (
                             SELECT 1 FROM chunks c
                             WHERE c.document_id = documents.id
                               AND c.embed_status = 'ok'
                         )"""
                )
        except Exception:
            pass  # 迁移不阻塞启动
        conn.commit()


def _ensure_storage_paths_aligned(db_path: str) -> None:
    """跨机/跨用户迁移时，按 ai_docs 锚点逐行重建 storage_path。

    以 ai_docs 为锚点保留相对部分，替换为当前用户的 ai_docs 基址；
    兼容 Windows 反斜杠、UNC、POSIX 正斜杠三种历史写法（统一存 /）。
    同机同用户（样本路径仍存在）直接跳过，不做任何写入。
    """
    anchor = "/.insight_eye/ai_docs/"
    new_base = (Path.home() / ".insight_eye" / "ai_docs").as_posix()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            sample = conn.execute(
                "SELECT storage_path FROM documents WHERE storage_path IS NOT NULL AND storage_path != '' LIMIT 1"
            ).fetchone()
            if not sample:
                return
            if Path(_to_posix(sample["storage_path"])).exists():
                return

            existing_tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table in ("documents", "document_versions"):
                if table not in existing_tables:
                    continue
                updates = []
                for row in conn.execute(f"SELECT id, storage_path FROM {table}"):
                    norm = _to_posix(row["storage_path"] or "")
                    idx = norm.find(anchor)
                    if idx < 0:
                        # 非默认 docs_dir 或无法识别，保持原样不猜
                        continue
                    tail = norm[idx + len(anchor):]
                    new_val = f"{new_base}/{tail}"
                    if new_val != row["storage_path"]:
                        updates.append((new_val, row["id"]))
                if updates:
                    conn.executemany(
                        f"UPDATE {table} SET storage_path = ? WHERE id = ?", updates
                    )
                    logger.info("storage_path 自愈：%s 更新 %d 条", table, len(updates))
            conn.commit()
    except Exception:
        logger.warning("storage_path 自愈失败，已跳过", exc_info=True)


class KBDatabase:
    def __init__(self, db_path: str, embed_dim: int = 1536, vector_enabled: bool = True) -> None:
        self.db_path = db_path
        self._embed_dim = embed_dim
        self._local = threading.local()  # vec0 原生连接仍用线程本地（ORM 通道另走 session_scope）
        self._vec_available: bool = False
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        # 建表 + 增量迁移 + 自愈校准，只对同一 db_path 跑一次。
        # 多线程并发 KBDatabase() 时（deps.py 每次请求都 new），
        # 多个线程同时执行 ALTER TABLE 会触发 "duplicate column name"。
        abs_path = os.path.abspath(db_path)
        if abs_path not in _schema_ready:
            with _schema_lock:
                if abs_path not in _schema_ready:  # double-check
                    Base.metadata.create_all(
                        get_engine(db_path),
                        tables=[Document.__table__, Chunk.__table__, DocumentVersion.__table__, Folder.__table__],
                    )
                    _ensure_project_columns(db_path)
                    _ensure_document_meta_columns(db_path)
                    _ensure_storage_paths_aligned(db_path)
                    _ensure_fts5_table(db_path)
                    _schema_ready.add(abs_path)
        # vec0 扩展加载：仅扩展加载/建表失败时降级（缺可选依赖）。
        # 维度不一致（ValueError）是数据完整性错误，必须抛出。
        # vector_enabled=False 时跳过 vec0 初始化——不读也不校验旧表，
        # 文档 CRUD 仍走 ORM 表正常工作。避免旧库维度不一致时构造崩溃。
        if not vector_enabled:
            self._vec_available = False
            return
        try:
            self._init_vec_table()
            self._vec_available = True
        except ValueError:
            raise
        except Exception as e:
            try:
                from logzero import logger

                logger.warning(f"sqlite-vec 不可用，向量检索降级: {e}")
            except Exception:
                pass
            self._vec_available = False

    def _ensure_vec_extension(self, conn: sqlite3.Connection) -> bool:
        """给当前连接临时加载 sqlite-vec 扩展。

        与 ``self._vec_available`` 无关——即使 RAG 整体关着，只要 vec0 虚拟表在磁盘上，
        清向量/删文档时也需要临时 load 扩展来操作它。返回是否成功加载。
        """
        try:
            import sqlite_vec

            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            return True
        except Exception:
            return False

    def get_connection(self) -> sqlite3.Connection:
        """vec0 原生连接（vector_store/retriever/documents 路由的原生 SQL 用）。

        每条连接加载 sqlite-vec 扩展（扩展是连接级，非进程级）。
        与 ORM session 通道相互独立，各自管各自的事务。
        """
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            if self._vec_available:
                try:
                    import sqlite_vec

                    conn.enable_load_extension(True)
                    sqlite_vec.load(conn)
                    conn.enable_load_extension(False)
                except Exception:
                    pass
            self._local.conn = conn
        return self._local.conn

    def _init_vec_table(self) -> None:
        """加载 sqlite-vec 扩展并建 vec0 虚拟表。

        维度一致性：若 vec0 表已存在，校验其声明维度与 self._embed_dim 一致。
        """
        import sqlite_vec

        conn = self.get_connection()
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chunk_embeddings'"
        ).fetchone()
        if existing:
            sql_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='chunk_embeddings'"
            ).fetchone()
            m = re.search(r"FLOAT\[(\d+)\]", sql_row["sql"])
            if m and int(m.group(1)) != self._embed_dim:
                raise ValueError(
                    f"embed_dim 不一致：vec0 表声明 {m.group(1)}，当前配置 {self._embed_dim}。"
                    "换 embedding 模型需重新索引所有文档。"
                )
            return
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings USING vec0("
            f"chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{self._embed_dim}])"
        )
        conn.commit()

    # ===== 文档（ORM 通道）=====

    def create_document(
        self,
        filename: str,
        storage_path: str,
        content_hash: str,
        mime_type: str | None,
        project_id: int | None = None,
        version_id: int | None = None,
        folder_id: int | None = None,
        source_type: str = "local",
        source_url: str = "",
        external_id: str = "",
        source_modified_at: str | None = None,
    ) -> int:
        with session_scope(self.db_path) as s:
            d = Document(
                filename=filename,
                storage_path=_to_posix(storage_path),
                content_hash=content_hash,
                mime_type=mime_type,
                project_id=project_id,
                version_id=version_id,
                folder_id=folder_id,
                source_type=source_type,
                source_url=source_url,
                external_id=external_id,
                source_modified_at=source_modified_at,
            )
            s.add(d)
            s.flush()
            return d.id

    def get_document(self, doc_id: int) -> Document | None:
        with session_scope(self.db_path) as s:
            return s.get(Document, doc_id)

    def list_documents(
        self,
        status_filter: str | None = None,
        project_id: int | None = None,
        version_id: int | None = None,
        folder_id: int | None = None,
        source_type: str | None = None,
        search: str | None = None,
        doc_type: str | None = None,
        tags: list[str] | None = None,
        page: int | None = None,
        page_size: int | None = None,
        return_total: bool = False,
    ) -> list[Document] | tuple[list[Document], int]:
        """分页 + 条件筛选。

        默认（不传 page/page_size）返回全量 list[Document]（向后兼容）；
        传了 page/page_size 时分页；return_total=True 时返回 (list, total)。
        """
        from sqlalchemy import func

        stmt = select(Document)
        count_stmt = select(func.count(Document.id))
        if status_filter:
            stmt = stmt.where(Document.status == DocumentStatus(status_filter))
            count_stmt = count_stmt.where(Document.status == DocumentStatus(status_filter))
        if project_id is not None:
            stmt = stmt.where(Document.project_id == project_id)
            count_stmt = count_stmt.where(Document.project_id == project_id)
        if version_id is not None:
            stmt = stmt.where(Document.version_id == version_id)
            count_stmt = count_stmt.where(Document.version_id == version_id)
        if source_type is not None:
            stmt = stmt.where(Document.source_type == source_type)
            count_stmt = count_stmt.where(Document.source_type == source_type)
        if folder_id is not None:
            if folder_id == 0:  # 0 表示未分类/根目录
                stmt = stmt.where(Document.folder_id.is_(None))
                count_stmt = count_stmt.where(Document.folder_id.is_(None))
            else:
                stmt = stmt.where(Document.folder_id == folder_id)
                count_stmt = count_stmt.where(Document.folder_id == folder_id)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(Document.filename.ilike(like))
            count_stmt = count_stmt.where(Document.filename.ilike(like))
        if doc_type:
            stmt = stmt.where(Document.doc_type == doc_type)
            count_stmt = count_stmt.where(Document.doc_type == doc_type)
        if tags:
            # tags 列存 JSON 数组字符串 '["a","b"]'，LIKE 匹配最简便
            for t in tags:
                tag_like = f'%"{t}"%'
                stmt = stmt.where(Document.tags.ilike(tag_like))
                count_stmt = count_stmt.where(Document.tags.ilike(tag_like))
        # 分页（仅在 page 或 page_size 显式传值时生效）
        if page is not None or page_size is not None:
            p = max(1, page or 1)
            ps = max(1, min(page_size or 500, 500))  # 防滥用
            stmt = stmt.offset((p - 1) * ps).limit(ps)
        stmt = stmt.order_by(Document.created_at.desc())
        with session_scope(self.db_path) as s:
            total = s.scalar(count_stmt) or 0
            items = list(s.scalars(stmt))
        if return_total:
            return items, total
        return items

    def move_document(self, doc_id: int, folder_id: int | None) -> bool:
        """移动文档到指定文件夹（None 或 0 表示移到根目录）。"""
        actual_folder_id = None if (folder_id is None or folder_id == 0) else folder_id
        with session_scope(self.db_path) as s:
            d = s.get(Document, doc_id)
            if d is None:
                return False
            d.folder_id = actual_folder_id
            d.updated_at = datetime.now()
            return True

    # ===== 文件夹目录（Folder）CRUD =====

    def create_folder(
        self,
        name: str,
        parent_id: int | None = None,
        project_id: int | None = None,
        source_type: str = "local",
        external_id: str = "",
    ) -> Folder:
        with session_scope(self.db_path) as s:
            f = Folder(
                name=name.strip(),
                parent_id=parent_id if parent_id and parent_id > 0 else None,
                project_id=project_id,
                source_type=source_type,
                external_id=external_id,
            )
            s.add(f)
            s.flush()
            return Folder(
                id=f.id,
                name=f.name,
                parent_id=f.parent_id,
                project_id=f.project_id,
                source_type=f.source_type,
                external_id=f.external_id,
                created_at=f.created_at,
                updated_at=f.updated_at,
            )

    def find_folder_by_external_id(self, external_id: str) -> Folder | None:
        if not external_id:
            return None
        stmt = select(Folder).where(Folder.external_id == external_id)
        with session_scope(self.db_path) as s:
            f = s.scalars(stmt).first()
            if not f:
                return None
            return Folder(
                id=f.id,
                name=f.name,
                parent_id=f.parent_id,
                project_id=f.project_id,
                source_type=f.source_type,
                external_id=f.external_id,
                created_at=f.created_at,
                updated_at=f.updated_at,
            )

    def list_folders(
        self,
        project_id: int | None = None,
        source_type: str | None = None,
    ) -> list[Folder]:
        stmt = select(Folder)
        if project_id is not None:
            stmt = stmt.where(Folder.project_id == project_id)
        if source_type is not None:
            stmt = stmt.where(Folder.source_type == source_type)
        stmt = stmt.order_by(Folder.name.asc())
        with session_scope(self.db_path) as s:
            return [
                Folder(
                    id=f.id,
                    name=f.name,
                    parent_id=f.parent_id,
                    project_id=f.project_id,
                    source_type=getattr(f, "source_type", "local"),
                    external_id=getattr(f, "external_id", ""),
                    created_at=f.created_at,
                    updated_at=f.updated_at,
                )
                for f in s.scalars(stmt)
            ]

    def update_folder(
        self,
        folder_id: int,
        name: str | None = None,
        parent_id: int | None = -1,  # -1 表示不修改
    ) -> bool:
        with session_scope(self.db_path) as s:
            f = s.get(Folder, folder_id)
            if f is None:
                return False
            if name is not None:
                f.name = name.strip()
            if parent_id != -1:
                f.parent_id = None if (parent_id is None or parent_id <= 0) else parent_id
            f.updated_at = datetime.now()
            return True

    def delete_folder(self, folder_id: int) -> bool:
        """删除文件夹：将其下文档的 folder_id 重置为 NULL，子文件夹 parent_id 重置为 NULL 后删除。"""
        with session_scope(self.db_path) as s:
            f = s.get(Folder, folder_id)
            if f is None:
                return False
            # 1. 解除直属文档的归属
            from sqlalchemy import update
            s.execute(
                update(Document).where(Document.folder_id == folder_id).values(folder_id=None)
            )
            # 2. 解除子文件夹的 parent_id
            s.execute(
                update(Folder).where(Folder.parent_id == folder_id).values(parent_id=None)
            )
            # 3. 删除文件夹
            s.delete(f)
            return True

    def count_by_project(self, project_id: int | None) -> int:
        """统计某项目下的文档数（project_id=None 统计未分类）。"""
        from sqlalchemy import func

        stmt = select(func.count(Document.id))
        if project_id is not None:
            stmt = stmt.where(Document.project_id == project_id)
        else:
            stmt = stmt.where(Document.project_id.is_(None))
        with session_scope(self.db_path) as s:
            return s.scalar(stmt) or 0

    def update_document_status(
        self,
        doc_id: int,
        status: DocumentStatus,
        error_message: str | None = None,
        char_count: int | None = None,
        chunk_count: int | None = None,
    ) -> None:
        with session_scope(self.db_path) as s:
            d = s.get(Document, doc_id)
            if d is None:
                return
            d.status = status
            d.updated_at = datetime.now()
            d.error_message = error_message  # 始终覆盖——None 代表无错误（含重启/重试时清旧错误）
            if char_count is not None:
                d.char_count = char_count
            if chunk_count is not None:
                d.chunk_count = chunk_count

    def delete_document(self, doc_id: int) -> bool:
        with session_scope(self.db_path) as s:
            d = s.get(Document, doc_id)
            if d is None:
                return False
            s.delete(d)
            return True

    def find_by_content_hash(self, content_hash: str) -> Document | None:
        stmt = select(Document).where(Document.content_hash == content_hash)
        with session_scope(self.db_path) as s:
            return s.scalars(stmt).first()

    def find_by_external_id(self, external_id: str) -> Document | None:
        stmt = select(Document).where(Document.external_id == external_id)
        with session_scope(self.db_path) as s:
            return s.scalars(stmt).first()

    # ===== 文档元数据 / 内容 / 版本（KB 升级新增）=====

    def update_document_meta(
        self,
        doc_id: int,
        tags: str | None = None,
        doc_type: str | None = None,
        description: str | None = None,
    ) -> None:
        """更新文档标签/类型/描述。tags 为 JSON 数组字符串。仅更新非 None 字段。"""
        with session_scope(self.db_path) as s:
            d = s.get(Document, doc_id)
            if d is None:
                return
            if tags is not None:
                d.tags = tags
            if doc_type is not None:
                d.doc_type = doc_type
            if description is not None:
                d.description = description
            d.updated_at = datetime.now()

    def list_tags(self, project_id: int | None = None) -> list[dict]:
        """聚合返回标签及计数（供标签云）。tags 列存 JSON 数组字符串。"""
        import json

        stmt = select(Document.tags)
        if project_id is not None:
            stmt = stmt.where(Document.project_id == project_id)
        counts: dict[str, int] = {}
        with session_scope(self.db_path) as s:
            for (raw,) in s.execute(stmt):
                try:
                    tags = json.loads(raw) if raw else []
                except (json.JSONDecodeError, TypeError):
                    tags = []
                for t in tags:
                    t = str(t).strip()
                    if t:
                        counts[t] = counts.get(t, 0) + 1
        return [{"tag": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]

    def get_document_content(self, doc_id: int) -> str:
        """获取文档纯文本。优先从 chunks 拼接；无 chunks（处理中/未分块）时直接解析原始文件。

        使用原始 sqlite3 + GROUP_CONCAT 避免 SQLAlchemy session 开销和 Python 循环拼接——
        对 1604 chunks / 180k chars 的大文档，从 300+ms 降到 <10ms。
        """
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT GROUP_CONCAT(text, CHAR(10)) FROM ("
                "SELECT text FROM chunks WHERE document_id = ? ORDER BY chunk_index"
                ")",
                (doc_id,),
            ).fetchone()
        if row and row[0] is not None:
            return row[0]
        # 无 chunks：直接解析原始文件（处理中文档/纯文本编辑场景）
        doc = self.get_document(doc_id)
        if doc and doc.storage_path:
            from pathlib import Path

            p = Path(doc.storage_path)
            if p.exists():
                try:
                    from insight_aitest.platform.services.kb.loader import get_loader

                    loader = get_loader(doc.filename)
                    parsed = loader.load(p)
                    return parsed.content
                except Exception:
                    return ""
        return ""

    def replace_document_content(self, doc_id: int, new_text: str) -> None:
        """编辑保存：用新文本替换文档全部分块（单块整文）。

        只更新 chunks 表文本（纯文本编辑场景）；向量化由路由层后台 reindex 触发。
        保留 chunk 的 char_start/char_end 为 0..len，使 chunks 不变量 text[0:len]==text 成立。
        """
        conn = self.get_connection()
        # 删旧 chunks（含向量由路由层 VectorStore 处理，这里只清 chunks 文本行）
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        cur = conn.execute(
            "INSERT INTO chunks (document_id, chunk_index, text, char_start, char_end, embed_status) "
            "VALUES (?, 0, ?, 0, ?, 'pending')",
            (doc_id, new_text, len(new_text)),
        )
        new_chunk_id = cur.lastrowid
        conn.execute(
            "UPDATE documents SET char_count = ?, chunk_count = 1, updated_at = ? WHERE id = ?",
            (len(new_text), datetime.now().isoformat(), doc_id),
        )
        # 同步更新 chunks_fts
        try:
            doc = self.get_document(doc_id)
            project_id = doc.project_id if doc else None
            conn.execute(
                "INSERT INTO chunks_fts (chunk_id, document_id, project_id, indexed_tokens) VALUES (?, ?, ?, ?)",
                (new_chunk_id, doc_id, project_id, tokenize_for_fts(new_text)),
            )
        except Exception:
            pass
        conn.commit()

    def get_chunks_text(
        self,
        document_ids: list[int] | None = None,
        project_id: int | None = None,
        max_chars: int = 5000,
        exclude_document_ids: list[int] | None = None,
    ) -> list[tuple[str, str, int]]:
        """拼接文档 chunk 原文（HybridRetriever L3 兜底 + 手动档文档选择）。

        Returns: [(filename, text, document_id), ...]
        """
        # 无范围限制时不做全库扫描，避免大量数据加载
        if not document_ids and project_id is None:
            return []

        stmt = (
            select(Chunk.text, Document.filename, Document.id)
            .join(Document, Chunk.document_id == Document.id)
            .order_by(Chunk.document_id, Chunk.chunk_index)
            .limit(2000)
        )
        if document_ids:
            stmt = stmt.where(Chunk.document_id.in_(document_ids))
        if exclude_document_ids:
            stmt = stmt.where(Chunk.document_id.notin_(exclude_document_ids))
        if project_id is not None:
            stmt = stmt.where(Document.project_id == project_id)

        with session_scope(self.db_path) as s:
            rows = list(s.execute(stmt))

        doc_texts: dict[int, tuple[str, str]] = {}  # doc_id -> (filename, text)
        for text, filename, doc_id in rows:
            if doc_id not in doc_texts:
                doc_texts[doc_id] = (filename or f"doc_{doc_id}", "")
            name, existing = doc_texts[doc_id]
            if len(existing) < max_chars:
                doc_texts[doc_id] = (name, existing + (text or "") + "\n")

        return [(name, text[:max_chars], did) for did, (name, text) in doc_texts.items()]

    def update_document_file(
        self,
        doc_id: int,
        storage_path: str,
        content_hash: str | None = None,
    ) -> None:
        """编辑保存（二进制文件场景）：更新 storage_path/content_hash，状态置 pending 待 reindex。"""
        with session_scope(self.db_path) as s:
            d = s.get(Document, doc_id)
            if d is None:
                return
            d.storage_path = _to_posix(storage_path)
            if content_hash is not None:
                d.content_hash = content_hash
            d.status = DocumentStatus.PENDING
            d.char_count = 0
            d.chunk_count = 0
            d.error_message = None
            d.updated_at = datetime.now()

    # ===== 版本管理 =====

    def create_version_snapshot(
        self,
        doc_id: int,
        storage_path: str,
        content_hash: str | None,
        char_count: int,
        chunk_count: int,
        note: str = "",
    ) -> int:
        """为文档当前内容创建版本快照，version_no 自增。返回新 version_id。"""
        with session_scope(self.db_path) as s:
            # 取该文档最大 version_no
            from sqlalchemy import func

            next_no = (
                s.scalar(
                    select(func.max(DocumentVersion.version_no)).where(
                        DocumentVersion.document_id == doc_id
                    )
                )
                or 0
            ) + 1
            v = DocumentVersion(
                document_id=doc_id,
                version_no=next_no,
                storage_path=_to_posix(storage_path),
                content_hash=content_hash,
                char_count=char_count,
                chunk_count=chunk_count,
                note=note,
                is_current=0,
            )
            s.add(v)
            s.flush()
            return v.id

    def list_versions(self, doc_id: int) -> list[DocumentVersion]:
        """列出版本历史（按版本号降序，最新在前）。"""
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == doc_id)
            .order_by(DocumentVersion.version_no.desc())
        )
        with session_scope(self.db_path) as s:
            return list(s.scalars(stmt))

    def get_version(self, doc_id: int, version_no: int) -> DocumentVersion | None:
        stmt = select(DocumentVersion).where(
            DocumentVersion.document_id == doc_id,
            DocumentVersion.version_no == version_no,
        )
        with session_scope(self.db_path) as s:
            return s.scalars(stmt).first()

    def rollback_version(self, doc_id: int, version_no: int) -> DocumentVersion | None:
        """回滚到指定版本：把当前内容另存一个版本快照，然后把目标版本的 storage_path
        写回 documents 表，状态置 pending 待 reindex。返回目标版本记录。"""
        target = self.get_version(doc_id, version_no)
        if target is None:
            return None
        # 先把当前内容存为快照（避免回滚后丢失当前版本）
        cur = self.get_document(doc_id)
        if cur is not None:
            self.create_version_snapshot(
                doc_id,
                cur.storage_path,
                cur.content_hash,
                cur.char_count,
                cur.chunk_count,
                note=f"回滚前快照（从 v{version_no} 回滚）",
            )
        # 把目标版本写回 documents
        self.update_document_file(doc_id, target.storage_path, target.content_hash)
        return target

    # ===== 分块（ORM 通道；向量由 VectorStore 走 get_connection 写 chunk_embeddings）=====

    def insert_chunks(self, document_id: int, chunks: list[Chunk]) -> list[int]:
        ids: list[int] = []
        with session_scope(self.db_path) as s:
            for c in chunks:
                c.document_id = document_id
                c.embed_status = EmbedStatus.PENDING
                s.add(c)
                s.flush()
                ids.append(c.id)

        # 同步写入 FTS5 倒排索引
        try:
            doc = self.get_document(document_id)
            project_id = doc.project_id if doc else None
            fts_rows = [
                (cid, document_id, project_id, tokenize_for_fts(c.text or ""))
                for cid, c in zip(ids, chunks)
            ]
            conn = self.get_connection()
            conn.executemany(
                "INSERT INTO chunks_fts (chunk_id, document_id, project_id, indexed_tokens) VALUES (?, ?, ?, ?)",
                fts_rows,
            )
            conn.commit()
        except Exception:
            pass  # FTS 同步不阻塞主摄取管线

        return ids

    def update_chunk_embed_status(self, chunk_id: int, status: EmbedStatus) -> None:
        """走 vec0 原生连接（非 ORM session）。

        原因：VectorStore.upsert_chunks 在同一原生连接里写 chunk_embeddings（vec0）的同时
        逐块调本方法更新 embed_status。若走 ORM session 会开第二个写事务，在 WAL 下与
        vec0 写事务互锁（database is locked）。用同一个原生连接保持单写事务，避免锁冲突。
        """
        conn = self.get_connection()
        conn.execute("UPDATE chunks SET embed_status = ? WHERE id = ?", (status.value, chunk_id))
        conn.commit()

    def get_chunks_by_document(self, doc_id: int) -> list[Chunk]:
        stmt = select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.chunk_index)
        with session_scope(self.db_path) as s:
            return list(s.scalars(stmt))


# ===== 迁移：旧 ai_kb.db → kb.db + ai.db =====


def migrate_from_legacy(ai_kb_path: str, kb_db_path: str, ai_db_path: str) -> bool:
    """旧 ai_kb.db 拆成 kb.db（文档/分块/向量）+ ai.db（会话/消息）。已迁移则跳过。

    返回 True 表示执行了迁移，False 表示跳过（已迁移或无旧库）。
    注意：不实例化 KBDatabase（它会强制 vec0 维度校验）。用原生 sqlite 建普通表 schema，
    vec0 表由后续真正打开 kb.db 的 KBDatabase 按配置 embed_dim 创建。
    """
    if os.path.exists(kb_db_path):
        return False  # 已迁移
    if not os.path.exists(ai_kb_path):
        return False  # 纯新装，无旧库

    src = sqlite3.connect(ai_kb_path)
    src.row_factory = sqlite3.Row

    # —— 建 kb.db 的普通表 schema（documents/chunks，不含 vec0）——
    kb_conn = sqlite3.connect(kb_db_path)
    kb_conn.executescript(
        """
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL,
        storage_path TEXT NOT NULL, mime_type TEXT, char_count INTEGER DEFAULT 0,
        chunk_count INTEGER DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
        error_message TEXT, content_hash TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL,
        chunk_index INTEGER NOT NULL, text TEXT NOT NULL,
        char_start INTEGER NOT NULL, char_end INTEGER NOT NULL,
        embed_status TEXT NOT NULL DEFAULT 'pending',
        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE);
    CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
    CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
    """
    )

    # 搬 documents
    for row in src.execute("SELECT * FROM documents").fetchall():
        kb_conn.execute(
            "INSERT OR IGNORE INTO documents (id, filename, storage_path, mime_type, "
            "char_count, chunk_count, status, error_message, content_hash, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["id"],
                row["filename"],
                row["storage_path"],
                row["mime_type"],
                row["char_count"],
                row["chunk_count"],
                row["status"],
                row["error_message"],
                row["content_hash"],
                row["created_at"],
                row["updated_at"],
            ),
        )
    # 搬 chunks
    for row in src.execute("SELECT * FROM chunks").fetchall():
        kb_conn.execute(
            "INSERT OR IGNORE INTO chunks (id, document_id, chunk_index, text, "
            "char_start, char_end, embed_status) VALUES (?,?,?,?,?,?,?)",
            (
                row["id"],
                row["document_id"],
                row["chunk_index"],
                row["text"],
                row["char_start"],
                row["char_end"],
                row["embed_status"],
            ),
        )
    kb_conn.commit()
    kb_conn.close()

    # —— 建 ai.db（会话/消息）：用 AIDatabase 建 schema，再用原生 sqlite 搬数据 ——
    from insight_aitest.modules.ai.backend.persistence.database import AIDatabase

    AIDatabase(ai_db_path)  # 建 schema（create_all + ensure_schema）
    ai_conn = sqlite3.connect(ai_db_path)
    ai_conn.row_factory = sqlite3.Row
    for tbl in ("conversations", "messages", "conversation_documents"):
        try:
            rows = src.execute(f"SELECT * FROM {tbl}").fetchall()
        except Exception:
            continue
        if not rows:
            continue
        cols = rows[0].keys()
        placeholders = ",".join("?" * len(cols))
        collist = ",".join(cols)
        for row in rows:
            ai_conn.execute(
                f"INSERT OR IGNORE INTO {tbl} ({collist}) VALUES ({placeholders})",
                tuple(row[c] for c in cols),
            )
    ai_conn.commit()
    ai_conn.close()
    src.close()
    # 释放 AIDatabase 创建时缓存的 ORM engine（否则 Windows 下占用文件句柄无法 rename）
    from insight_aitest.platform.persistence.engine import dispose_all

    dispose_all()

    # 旧库重命名备份（不删）
    os.rename(ai_kb_path, ai_kb_path + ".migrated")
    return True


# ===== 辅助 =====


def _parse_dt(val) -> datetime:
    """供 vector_store/retriever 的原生 SQL 结果行用（ORM 通道已自带 datetime 转换）。"""
    if val is None:
        return datetime.now()
    try:
        return datetime.fromisoformat(str(val))
    except (ValueError, TypeError):
        return datetime.now()
