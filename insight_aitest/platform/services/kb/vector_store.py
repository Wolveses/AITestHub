# -*- coding: utf-8 -*-
"""sqlite-vec 向量存取（平台共享服务）。

职责：chunks 原文已在 KBDatabase 写入 → 批量 embed → 写入 chunk_embeddings。
查询：KNN 检索（MATCH ... ORDER BY distance LIMIT k）→ JOIN chunks/documents 取原文与文档元信息。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from insight_aitest.platform.services.kb.models import Chunk, Document, EmbedStatus, ScoredChunk

if TYPE_CHECKING:
    from insight_aitest.platform.services.llm.config import LLMConfig
    from insight_aitest.platform.services.llm.client import LLMClient
    from insight_aitest.platform.services.kb.database import KBDatabase


def _vec_to_str(vec: list[float]) -> str:
    return "[" + ",".join(str(x) for x in vec) + "]"


class VectorStore:
    def __init__(self, db: "KBDatabase", llm: "LLMClient", config: "LLMConfig") -> None:
        self.db = db
        self.llm = llm
        self.config = config

    def upsert_chunks(self, document_id: int, chunks: list[Chunk]) -> None:
        """读该文档所有 chunk（含 DB id）→ 批量 embed → 写 chunk_embeddings → 更新 embed_status。

        前置：调用方应已 KBDatabase.insert_chunks，chunks 表里已有记录。
        本方法参数 chunks 仅用于触发（实际从 DB 读以拿到 id）。
        """
        db_chunks = self.db.get_chunks_by_document(document_id)
        if not db_chunks:
            return
        texts = [c.text for c in db_chunks]
        batch = self.config.embed_batch_size
        conn = self.db.get_connection()
        for i in range(0, len(texts), batch):
            batch_texts = texts[i : i + batch]
            batch_chunks = db_chunks[i : i + batch]
            try:
                vecs = self.llm.embed(batch_texts)
            except Exception as e:
                # 记录日志（用户配错 key/地址时能在后端日志看到，而非静默失败）
                try:
                    from logzero import logger

                    logger.warning(
                        f"[kb] embedding 批次失败（{len(batch_texts)} 块）: {type(e).__name__}: {e}"
                    )
                except Exception:
                    pass
                for c in batch_chunks:
                    self.db.update_chunk_embed_status(c.id, EmbedStatus.FAILED)
                continue
            for c, vec in zip(batch_chunks, vecs):
                conn.execute(
                    "INSERT OR REPLACE INTO chunk_embeddings (chunk_id, embedding) VALUES (?, ?)",
                    (c.id, _vec_to_str(vec)),
                )
                self.db.update_chunk_embed_status(c.id, EmbedStatus.OK)
            conn.commit()

    def search(
        self,
        query_vec: list[float],
        top_k: int,
        document_ids: list[int] | None = None,
        project_id: int | None = None,
        exclude_document_ids: list[int] | None = None,
    ) -> list[ScoredChunk]:
        if not self.db._vec_available:
            return []
        conn = self.db.get_connection()
        vec_str = _vec_to_str(query_vec)
        select_cols = (
            "ce.chunk_id, ce.distance, c.text, c.chunk_index, "
            "c.char_start, c.char_end, c.document_id, "
            "d.filename, d.storage_path, d.mime_type, d.char_count, "
            "d.chunk_count, d.status, d.error_message, d.content_hash, "
            "d.created_at, d.updated_at"
        )
        joins = (
            "FROM chunk_embeddings ce "
            "JOIN chunks c ON c.id = ce.chunk_id "
            "JOIN documents d ON d.id = c.document_id"
        )
        # 动态拼 WHERE：project_id 过滤（KB 升级，隔离检索范围）+ document_ids 过滤 + exclude_document_ids 排除
        where_clauses = []
        params: list = []
        if document_ids:
            placeholders = ",".join("?" * len(document_ids))
            where_clauses.append(f"c.document_id IN ({placeholders})")
            params.extend(document_ids)
        if exclude_document_ids:
            placeholders = ",".join("?" * len(exclude_document_ids))
            where_clauses.append(f"c.document_id NOT IN ({placeholders})")
            params.extend(exclude_document_ids)
        if project_id is not None:
            # 允许属于该项目或全局文档（project_id IS NULL）被检索，避免全局通用文档被隔离漏召
            where_clauses.append("(d.project_id = ? OR d.project_id IS NULL)")
            params.append(project_id)
        where_sql = (
            ("WHERE " + " AND ".join(where_clauses) + " AND ") if where_clauses else "WHERE "
        )
        # sqlite-vec 中，MATCH ... k = N 会首先在 chunk_embeddings 虚拟表中取全局前 N 个最近邻，
        # 如果带有 document_ids 或 project_id 等外部表过滤条件，在小 k 下极易把目标文档的 chunk 筛光。
        # 因此有外部过滤条件时，增大 MATCH 的 k 值（至少 1000 或全局总量），保证召回足够候选后再过滤。
        match_k = top_k
        if where_clauses:
            match_k = max(top_k * 50, 1000)

        rows = conn.execute(
            f"SELECT {select_cols} {joins} "
            f"{where_sql}ce.embedding MATCH ? AND k = ? "
            f"ORDER BY ce.distance LIMIT ?",
            [*params, vec_str, match_k, top_k],
        ).fetchall()

        from insight_aitest.platform.services.kb.database import _parse_dt
        from insight_aitest.platform.services.kb.models import DocumentStatus

        results = []
        for r in rows:
            chunk = Chunk(
                id=r["chunk_id"],
                document_id=r["document_id"],
                chunk_index=r["chunk_index"],
                text=r["text"],
                char_start=r["char_start"],
                char_end=r["char_end"],
                embed_status=EmbedStatus.OK,
            )
            doc = Document(
                id=r["document_id"],
                filename=r["filename"],
                storage_path=r["storage_path"],
                mime_type=r["mime_type"],
                char_count=r["char_count"],
                chunk_count=r["chunk_count"],
                status=DocumentStatus(r["status"]),
                error_message=r["error_message"],
                content_hash=r["content_hash"],
                created_at=_parse_dt(r["created_at"]),
                updated_at=_parse_dt(r["updated_at"]),
            )
            # 归一化向量的 L2 距离 d：||a-b||²=2(1-cos) → cos 相似度 = 1 - d²/2
            # distance 越小越相似，转成 [0,1] 的余弦相似度作为 score
            d = float(r["distance"])
            score = max(0.0, 1.0 - (d * d) / 2.0)
            results.append(ScoredChunk(chunk=chunk, score=score, document=doc))
        return results

    def delete_document(self, document_id: int) -> None:
        """删 chunk_embeddings 中该文档的向量（chunks 表由外键 CASCADE）。"""
        conn = self.db.get_connection()
        chunk_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchall()
        ]
        # 清向量：表存在 → 临时 load vec0 扩展 → 清
        # 不依赖 _vec_available（RAG 开关），否则关 RAG 期间删文档会残留孤儿向量
        has_vec_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_embeddings'"
        ).fetchone()
        if has_vec_table and self.db._ensure_vec_extension(conn):
            for cid in chunk_ids:
                conn.execute("DELETE FROM chunk_embeddings WHERE chunk_id = ?", (cid,))
        conn.commit()
