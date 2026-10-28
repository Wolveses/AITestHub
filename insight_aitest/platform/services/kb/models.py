# -*- coding: utf-8 -*-
"""知识库数据模型（平台共享服务 + P0-1 ORM 迁移）。

从 ai 模块上提：KB 相关的 Document/Chunk/ParsedDocument/ScoredChunk + 枚举。
ai 模块保留 Conversation/Message/Role/Citation（对话专属）。

P0-1：Document/Chunk 从手写 dataclass 改为 ``MappedAsDataclass`` ORM 模型，
同名同字段替换——业务层（routes/vector_store/retriever/ingest/tests）用法不变。
- 枚举字段（DocumentStatus/EmbedStatus）Python 侧仍是枚举，存 ``.value`` TEXT。
- chunk_embeddings（vec0 虚拟表）不入 ORM，由 KBDatabase 原生 sqlite3 通道管理。
- ParsedDocument/ScoredChunk 是内存流水线模型（非持久化），保持 dataclass。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column

from insight_aitest.platform.persistence import Base
from insight_aitest.platform.persistence.types import enum_values

# ============ 枚举 ============


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    NOT_VECTORIZED = "not_vectorized"
    PARSE_FAILED = "parse_failed"
    EMBED_FAILED = "embed_failed"
    EMBED_PARTIAL = "embed_partial"

    @property
    def is_terminal(self) -> bool:
        return self in (
            DocumentStatus.READY,
            DocumentStatus.NOT_VECTORIZED,
            DocumentStatus.PARSE_FAILED,
            DocumentStatus.EMBED_FAILED,
            DocumentStatus.EMBED_PARTIAL,
        )


class EmbedStatus(str, Enum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"


# ============ DB 行模型（ORM）============
# 所有模型的 id 默认 None（插入前构造，DB 回填 id）。


class Document(MappedAsDataclass, Base):
    """文档（ORM 模型，即业务层 DTO）。

    ``id`` 进 __init__（默认 None）：vector_store 从原生 SQL 结果行构造 Document 时
    传 id=（带 DB id 的已读回对象），与新建（id=None 由 DB 回填）两种用法都要支持。

    project_id/version_id：可空逻辑外键（跨 DB 文件，不加 FK 约束）。
    旧数据 NULL = 未分类。ensure_schema 幂等补列。

    KB 升级新增（幂等 ALTER TABLE 补列，旧数据 NULL/空）：
    - tags：JSON 数组字符串，如 '["登录","接口"]'，支持多词标签（CommaList 无法表达含逗号的标签）
    - doc_type：文档类型（需求/设计/接口/测试/其他）
    - description：一句话描述
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_status", "status"),
        Index("idx_documents_kind", "kind"),
    )

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    filename: Mapped[str] = mapped_column(Text, default="")
    storage_path: Mapped[str] = mapped_column(Text, default="")
    mime_type: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus, values_callable=enum_values), default=DocumentStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    folder_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # KB 升级：标签与元数据（幂等补列，旧数据为空）
    tags: Mapped[str] = mapped_column(Text, default="")  # JSON 数组字符串
    doc_type: Mapped[str] = mapped_column(Text, default="")
    # 内容实体类型：doc（文档）| defect（缺陷）| case（用例）。
    # 与 source_type（数据来源 local/feishu/tapd）正交，幂等补列，旧数据默认 doc。
    kind: Mapped[str] = mapped_column(Text, default="doc")
    description: Mapped[str] = mapped_column(Text, default="")
    # 飞书等外部数据源支持
    source_type: Mapped[str] = mapped_column(Text, default="local")  # local | feishu
    source_url: Mapped[str] = mapped_column(Text, default="")
    external_id: Mapped[str] = mapped_column(Text, default="")
    # 外部源修改时间戳（Unix 秒）：飞书 latest_modify_time 等值，用于元数据前置增量判断
    # 为空则回退到 content_hash 全量比对
    source_modified_at: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


class DefectMeta(MappedAsDataclass, Base):
    """TAPD 缺陷结构化元数据（与 documents 1:1，``document_id`` 即主键）。

    只放「需要筛选/排序/统计」的字段；复现步骤、期望/实际、根因、评论等叙述性内容
    留在文档正文与 chunk 里，避免把 30+ 字段摊到通用 documents 表。
    """

    __tablename__ = "kb_defect_meta"
    __table_args__ = (
        Index("idx_defect_status", "status"),
        Index("idx_defect_module", "module"),
        Index("idx_defect_owner", "owner"),
        Index("idx_defect_modified", "modified_at_ext"),
        Index("idx_defect_external", "workspace_id", "defect_id", unique=True),
    )

    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[str] = mapped_column(Text, default="")
    defect_id: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(Text, default="")
    module: Mapped[str] = mapped_column(Text, default="")
    bugtype: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(Text, default="")
    creator: Mapped[str] = mapped_column(Text, default="")
    iteration_id: Mapped[str] = mapped_column(Text, default="")
    found_version: Mapped[str] = mapped_column(Text, default="")
    fix_version: Mapped[str] = mapped_column(Text, default="")
    # 外部时间统一存字符串原文（如 2026-09-02 10:00:00），避免时区歧义
    created_at_ext: Mapped[str] = mapped_column(Text, default="")
    modified_at_ext: Mapped[str] = mapped_column(Text, default="")
    comment_count: Mapped[int] = mapped_column(Integer, default=0)


class CaseMeta(MappedAsDataclass, Base):
    """TAPD 测试用例结构化元数据（与 documents 1:1）。

    与 DefectMeta 同一思路：只放列表页要展示/筛选的字段，步骤与前置条件留在正文。
    不设 (workspace_id, case_id) 唯一约束——同一用例可分别同步进不同项目。
    """

    __tablename__ = "kb_case_meta"
    __table_args__ = (
        Index("idx_case_status", "status"),
        Index("idx_case_priority", "priority"),
        Index("idx_case_owner", "owner"),
        Index("idx_case_modified", "modified_at_ext"),
        Index("idx_case_external", "workspace_id", "case_id"),
    )

    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[str] = mapped_column(Text, default="")
    case_id: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(Text, default="")
    case_type: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[str] = mapped_column(Text, default="")
    # TAPD 目录全路径（"用户中心 / 登录 / 异常场景"），便于不打目录树也能定位
    category_path: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(Text, default="")
    creator: Mapped[str] = mapped_column(Text, default="")
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at_ext: Mapped[str] = mapped_column(Text, default="")
    modified_at_ext: Mapped[str] = mapped_column(Text, default="")


class TapdSyncState(MappedAsDataclass, Base):
    """TAPD 同步水位（L1 增量），按 workspace + 项目 + 对象类型隔离。"""

    __tablename__ = "kb_tapd_sync_state"
    __table_args__ = (
        Index("idx_tapd_state_key", "workspace_id", "project_id", "kind", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    workspace_id: Mapped[str] = mapped_column(Text, default="")
    project_id: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(Text, default="")  # defect | case
    watermark: Mapped[str] = mapped_column(Text, default="")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class Folder(MappedAsDataclass, Base):
    """知识库逻辑目录（文件夹）。
    
    层级目录树：通过 parent_id 自关联；
    project_id：支持项目内独立目录或全局公共目录。
    """

    __tablename__ = "kb_folders"
    __table_args__ = (
        Index("idx_folders_parent", "parent_id"),
        Index("idx_folders_project", "project_id"),
    )

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    name: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    source_type: Mapped[str] = mapped_column(Text, default="local")  # local | feishu
    external_id: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


class Chunk(MappedAsDataclass, Base):
    """分块（ORM 模型，即业务层 DTO）。chunk_embeddings（vec0）不入 ORM。

    ``id`` 进 __init__（默认 None）：chunker 构造时传 id=None/document_id=0，
    由 DB 回填。与 TestCase 的 init=False 不同，因 chunker 显式传 id。
    """

    __tablename__ = "chunks"
    __table_args__ = (Index("idx_chunks_document", "document_id"),)

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), default=0
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    embed_status: Mapped[EmbedStatus] = mapped_column(
        SAEnum(EmbedStatus, values_callable=enum_values), default=EmbedStatus.PENDING
    )


class DocumentVersion(MappedAsDataclass, Base):
    """文档历史版本快照（KB 升级新增）。

    每次编辑保存 / 重新上传覆盖时，旧内容写入此表作为快照。
    documents 表始终持有「当前版本」；本表保存历史版本（is_current 标记最新回滚点）。
    storage_path 指向旧版本原始文件的独立副本（回滚时直接复用，不依赖 documents.storage_path）。
    """

    __tablename__ = "document_versions"
    __table_args__ = (Index("idx_doc_versions_doc", "document_id"),)

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    document_id: Mapped[int] = mapped_column(Integer, default=0)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    storage_path: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    is_current: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


# ============ 内存流水线模型（非持久化，保持 dataclass）===========


@dataclass
class ParsedDocument:
    """Loader 输出 / Chunker 输入（≠ DB 的 Document）。"""

    filename: str
    content: str
    meta: dict = field(default_factory=dict)


@dataclass
class ScoredChunk:
    """Retriever 输出：命中的 chunk + 分数 + 所属文档。"""

    chunk: Chunk
    score: float
    document: Document
