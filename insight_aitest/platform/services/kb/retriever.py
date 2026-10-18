# -*- coding: utf-8 -*-
"""检索编排（平台共享服务）。

三级降级检索链：
  L1: 向量语义搜索 (KNN) → 高精度，需向量模型
  L2: SQL关键词回退 (LIKE) → 无需向量，中文分词关键词匹配
  L3: 文档原文兜底 → 全量拼接，确保永远不空
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from insight_aitest.platform.services.llm.config import LLMConfig
    from insight_aitest.platform.services.kb.vector_store import ScoredChunk, VectorStore
    from insight_aitest.platform.services.llm.client import LLMClient
    from insight_aitest.platform.services.kb.database import KBDatabase


class Retriever:
    """混合检索器：向量(L1) → 关键词(L2) → 原文(L3) 三级降级。

    document_ids 限定检索范围（手动档勾选文档）。
    project_id 限定项目隔离。
    """

    def __init__(
        self,
        vector_store: "VectorStore",
        kb_db: "KBDatabase | None",
        llm: "LLMClient",
        config: "LLMConfig",
    ) -> None:
        self.vector_store = vector_store
        self.kb_db = kb_db
        self.llm = llm
        self.config = config

    # ── 公开接口 ──────────────────────────────────────

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        document_ids: list[int] | None = None,
        project_id: int | None = None,
        fallback: bool = True,
        exclude_document_ids: list[int] | None = None,
    ) -> list["ScoredChunk"]:
        """三级降级检索：向量 → 关键词 → 原文。
        如果查询包含明确的 IP 地址等实体标识符，优先执行精确关键词匹配，确保专用实体不被泛化语义掩盖。
        """
        k = top_k or self.config.top_k

        # 检查是否包含明确的 IP 地址等高精度关键词标识
        has_ip = bool(re.search(r"\b\d{1,3}(?:\.\d{1,3}){2,3}\b", query))
        if has_ip:
            kw_results = self._keyword_retrieve(query, k, document_ids, project_id, exclude_document_ids)
            if kw_results:
                return kw_results

        # L1: 向量语义搜索
        results = self._vector_retrieve(query, k, document_ids, project_id, exclude_document_ids)
        if results:
            return results

        # L2: SQL 关键词回退
        results = self._keyword_retrieve(query, k, document_ids, project_id, exclude_document_ids)
        if results:
            return results

        # L3: 文档原文兜底（仅在允许 fallback 时触发，如用例生成器；常规对话不兜底无关文档）
        if fallback:
            return self._fulltext_fallback(query, k, document_ids, project_id, exclude_document_ids=exclude_document_ids)
        return []

    def keyword_search(
        self,
        query: str,
        top_k: int = 4,
        document_ids: list[int] | None = None,
        project_id: int | None = None,
        exclude_document_ids: list[int] | None = None,
    ) -> list["ScoredChunk"]:
        """直接关键词搜索（手动档专用，跳过向量）。"""
        return self._keyword_retrieve(query, top_k, document_ids, project_id, exclude_document_ids)

    def document_content(
        self,
        document_ids: list[int],
        max_chars: int = 8000,
    ) -> list["ScoredChunk"]:
        """获取文档原文（手动档专用）。"""
        if not document_ids:
            return []
        return self._fulltext_fallback("", 8, document_ids, None, max_chars)

    # ── 统计信息 ──────────────────────────────────────

    def stats(self, document_ids: list[int] | None = None) -> dict:
        """返回检索范围统计（前端可视化）。"""
        if self.kb_db is None:
            return {
                "total_docs": 0,
                "total_chunks": 0,
                "vectorized_docs": 0,
                "vector_enabled": getattr(self.config, "vector_enabled", False),
            }

        from insight_aitest.platform.persistence import session_scope

        with session_scope(self.kb_db.db_path) as s:
            from insight_aitest.platform.services.kb.models import Document, Chunk
            from sqlalchemy import func

            doc_q = s.query(func.count(Document.id))
            chunk_q = s.query(func.count(Chunk.id))
            ready_q = s.query(func.count(func.distinct(Chunk.document_id))).filter(
                Chunk.embed_status == "ok"
            )
            if document_ids:
                doc_q = doc_q.filter(Document.id.in_(document_ids))
                chunk_q = chunk_q.filter(Chunk.document_id.in_(document_ids))
                ready_q = ready_q.filter(Chunk.document_id.in_(document_ids))

            total_docs = doc_q.scalar() or 0
            total_chunks = chunk_q.scalar() or 0
            vectorized_docs = ready_q.scalar() or 0

        return {
            "total_docs": total_docs,
            "total_chunks": total_chunks,
            "vectorized_docs": vectorized_docs,
            "vector_enabled": getattr(self.config, "vector_enabled", False),
        }

    # ── L1: 向量检索 ──────────────────────────────────

    def _vector_retrieve(
        self,
        query: str,
        k: int,
        document_ids: list[int] | None,
        project_id: int | None,
        exclude_document_ids: list[int] | None = None,
    ) -> list["ScoredChunk"]:
        if not getattr(self.config, "vector_enabled", False):
            return []
        try:
            query_vec = self.llm.embed_query(query)
        except Exception:
            return []

        fetch_k = k
        if self.config.rerank_enabled:
            fetch_k = max(self.config.rerank_fetch_k, k)

        results = self.vector_store.search(
            query_vec,
            top_k=fetch_k,
            document_ids=document_ids,
            project_id=project_id,
            exclude_document_ids=exclude_document_ids,
        )
        results = [r for r in results if r.score >= self.config.min_score]

        if self.config.rerank_enabled and len(results) > k:
            results = self._rerank(query, results, k)

        # 文档多样性控制：当检索未限定单个文档且结果中包含多个不同文档时，
        # 单篇文档最多占据 2 个 chunk，避免某一文档的相似 chunk 霸占全部 top-k 槽位
        distinct_docs = {r.document.filename for r in results}
        if not (document_ids and len(document_ids) == 1) and len(distinct_docs) > 1 and len(results) > k:
            doc_counts: dict[str, int] = {}
            diversified: list["ScoredChunk"] = []
            max_per_doc = 2
            for r in results:
                doc_name = r.document.filename
                cnt = doc_counts.get(doc_name, 0)
                if cnt < max_per_doc:
                    diversified.append(r)
                    doc_counts[doc_name] = cnt + 1
            # 若多样性筛选后不足 k 条，用剩余高分 chunk 补齐
            if len(diversified) < k:
                seen_chunk_ids = {r.chunk.id for r in diversified}
                for r in results:
                    if r.chunk.id not in seen_chunk_ids:
                        diversified.append(r)
                        if len(diversified) >= k:
                            break
            results = diversified

        return results[:k]

    # ── L2: SQL 关键词回退 ────────────────────────────

    def _keyword_retrieve(
        self,
        query: str,
        k: int,
        document_ids: list[int] | None,
        project_id: int | None,
        exclude_document_ids: list[int] | None = None,
    ) -> list["ScoredChunk"]:
        """SQL LIKE 关键词匹配。提取关键词逐个 LIKE 搜索并按加权命中排序。"""
        if not query or not query.strip():
            return []
        if self.kb_db is None:
            return []

        # 提取关键词
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        from insight_aitest.platform.persistence import session_scope
        from insight_aitest.platform.services.kb.models import Chunk, Document, ScoredChunk
        from sqlalchemy import or_

        # 区分高优先级精准关键词（如完整 IP、纯英文数字实体）与普通分词
        ips = [kw for kw in keywords if re.match(r"^\d{1,3}(?:\.\d{1,3}){2,3}$", kw)]

        with session_scope(self.kb_db.db_path) as s:
            stmt = s.query(Chunk, Document).join(Document, Chunk.document_id == Document.id)
            if document_ids:
                stmt = stmt.filter(Chunk.document_id.in_(document_ids))
            if exclude_document_ids:
                stmt = stmt.filter(Chunk.document_id.notin_(exclude_document_ids))
            if project_id is not None:
                stmt = stmt.filter(or_(Document.project_id == project_id, Document.project_id.is_(None)))

            # 如果存在精确 IP 关键词，直接优先按 IP 精确过滤召回
            if ips:
                ip_conds = [Chunk.text.like(f"%{ip}%") for ip in ips]
                ip_rows = stmt.filter(or_(*ip_conds)).limit(k * 4).all()
                if ip_rows:
                    return [
                        ScoredChunk(chunk=chunk, document=doc, score=0.98)
                        for chunk, doc in ip_rows[:k]
                    ]

            # 普通关键词检索
            conditions = [Chunk.text.like(f"%{kw}%") for kw in keywords[:8]]
            stmt = stmt.filter(or_(*conditions))
            stmt = stmt.limit(k * 8)
            rows = stmt.all()

        # 按关键词命中数及关键词长度加权计分
        scored = []
        for chunk, doc in rows:
            text = chunk.text or ""
            # 计算命中得分
            hit_score = 0.0
            for kw in keywords:
                if kw in text:
                    # 较长关键词权重更高
                    hit_score += len(kw)
            score = min(hit_score / max(sum(len(kw) for kw in keywords), 1), 0.95)
            if score > 0:
                scored.append(
                    ScoredChunk(
                        chunk=chunk,
                        document=doc,
                        score=score,
                    )
                )

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:k]

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """从查询文本提取关键词：IP/点分数字 + 连续英文标识符 + 中文2-4字片段。"""
        keywords = []
        # 1. IP 地址 / 点分版本号等 (如 192.2.0.163)
        ips = re.findall(r"\b\d{1,3}(?:\.\d{1,3}){2,3}\b", text)
        keywords.extend(ips)
        # 2. 连续英文字母标识符（排除纯单字）
        eng_words = re.findall(r"[a-zA-Z_]{2,}", text)
        keywords.extend(eng_words)
        # 3. 中文：连续中文字符提取2-4字片段
        chinese = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        for seg in chinese:
            for l in (4, 3, 2):
                for i in range(len(seg) - l + 1):
                    keywords.append(seg[i : i + l])
        # 去重，优先长关键词
        seen = set()
        unique = []
        for kw in sorted(keywords, key=lambda x: -len(x)):
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)
        return unique[:16]

    # ── L3: 文档原文兜底 ──────────────────────────────

    def _fulltext_fallback(
        self,
        query: str,
        k: int,
        document_ids: list[int] | None,
        project_id: int | None,
        max_chars: int = 5000,
        exclude_document_ids: list[int] | None = None,
    ) -> list["ScoredChunk"]:
        """直接拼接文档 chunk 原文（不依赖向量也不依赖关键词匹配）。"""
        if self.kb_db is None:
            return []
        docs_content = self.kb_db.get_chunks_text(
            document_ids, project_id, max_chars, exclude_document_ids=exclude_document_ids
        )
        if not docs_content:
            # 最终兜底：从文件直接读取
            read_ids = [d for d in (document_ids or []) if not (exclude_document_ids and d in exclude_document_ids)]
            docs_content = self._read_raw_files(read_ids, max_chars)

        if not docs_content:
            return []

        # 包装为 ScoredChunk（用低分标记为兜底）
        from insight_aitest.platform.services.kb.models import (
            Chunk,
            Document,
            EmbedStatus,
            ScoredChunk as SC,
        )

        results = []
        for doc_name, text, doc_id in docs_content:
            # 创建伪 Chunk
            fake_chunk = Chunk(
                document_id=doc_id or 0,
                text=text,
                chunk_index=0,
                embed_status=EmbedStatus.OK,
            )
            fake_doc = Document(id=doc_id or 0, filename=doc_name)
            results.append(
                SC(
                    chunk=fake_chunk,
                    document=fake_doc,
                    score=0.05,  # 标记为兜底
                )
            )
        return results[:k]

    def _read_raw_files(
        self, document_ids: list[int] | None, max_chars: int
    ) -> list[tuple[str, str, int]]:
        """直接从原始文件读取（chunks 表无数据时的最终兜底）。"""
        if not document_ids or self.kb_db is None:
            return []
        results = []
        for doc_id in document_ids:
            try:
                doc = self.kb_db.get_document(doc_id)
                if doc and doc.storage_path:
                    from pathlib import Path

                    p = Path(doc.storage_path)
                    if p.exists():
                        text = p.read_text(encoding="utf-8", errors="ignore")[:max_chars]
                        results.append((doc.filename or f"doc_{doc_id}", text, doc_id))
            except Exception:
                continue
        return results

    # ── Rerank (保持不变) ──────────────────────────────

    def _rerank(self, query: str, candidates: list["ScoredChunk"], k: int) -> list["ScoredChunk"]:
        if not candidates:
            return candidates
        try:
            scores = self._llm_score(query, [c.chunk.text for c in candidates])
        except Exception:
            return candidates
        paired = list(zip(candidates, scores))
        paired.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in paired[: max(k, len(candidates))]]

    def _llm_score(self, query: str, docs: list[str]) -> list[float]:
        snippets = []
        for i, d in enumerate(docs):
            t = (d or "").replace("\n", " ").strip()[:200]
            snippets.append(f"[{i}] {t}")
        joined = "\n".join(snippets)
        prompt = (
            f"你是检索相关性打分器。用户问题：{query}\n\n"
            f"以下是 {len(docs)} 个候选文本片段：\n{joined}\n\n"
            f"请对每个片段打 0-10 的相关性分（10=高度相关，0=无关）。"
            f"只输出 JSON 数组，长度={len(docs)}，元素为 0-10 的数字，顺序与片段一致。示例：[8,3,10]"
        )
        raw = self.llm.chat(
            [
                {"role": "system", "content": "你是检索相关性打分器，只输出 JSON 数组。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        return self._parse_score_array(raw, len(docs))

    @staticmethod
    def _parse_score_array(raw: str, expected_len: int) -> list[float]:
        m = re.search(r"\[[\s\S]*?\]", raw)
        if not m:
            return [0.0] * expected_len
        try:
            arr = json.loads(m.group(0))
            if not isinstance(arr, list):
                return [0.0] * expected_len
            scores = [float(x) for x in arr if isinstance(x, (int, float))][:expected_len]
            scores += [0.0] * (expected_len - len(scores))
            return scores
        except (json.JSONDecodeError, ValueError, TypeError):
            return [0.0] * expected_len


class NullRetriever:
    """空检索器：retrieve 永远返回空列表。

    用于 use_kb=False 场景（用户在输入框关闭了知识库检索），
    替代真实 Retriever 注入 Generator/SkillContext，使生成走纯 LLM 无参考资料。
    """

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        document_ids: list[int] | None = None,
        project_id: int | None = None,
    ) -> list["ScoredChunk"]:
        return []

    def keyword_search(
        self,
        query: str,
        top_k: int = 4,
        document_ids: list[int] | None = None,
        project_id: int | None = None,
    ) -> list["ScoredChunk"]:
        return []

    def document_content(
        self,
        document_ids: list[int],
        max_chars: int = 8000,
    ) -> list["ScoredChunk"]:
        return []

    def stats(self, document_ids: list[int] | None = None) -> dict:
        return {"total_docs": 0, "total_chunks": 0, "vectorized_docs": 0, "vector_enabled": False}
