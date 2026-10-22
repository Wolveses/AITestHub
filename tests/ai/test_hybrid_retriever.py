# -*- coding: utf-8 -*-
"""多路融合检索 (Hybrid Retrieval: Dense + Sparse FTS5 + RRF) 单元测试。"""
import tempfile
import os
from unittest.mock import MagicMock
from insight_aitest.platform.services.kb.database import KBDatabase
from insight_aitest.platform.services.kb.models import Chunk, ScoredChunk, Document
from insight_aitest.platform.services.kb.retriever import Retriever
from insight_aitest.platform.services.llm.config import AIConfig


def test_fts5_indexing_and_search():
    """验证 FTS5 自动索引建立与检索命中。"""
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "kb.db")
        db = KBDatabase(db_path, vector_enabled=False)
        doc_id = db.create_document("perf.xlsx", "/path/perf.xlsx", "hash1", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        c1 = Chunk(id=None, document_id=doc_id, chunk_index=0, text="# 长跑测试\n| 1 | 压力测试 | 输出分辨率 16384*2160，GPU占用率很高 |")
        c2 = Chunk(id=None, document_id=doc_id, chunk_index=1, text="# 界面测试\n| 2 | 功能测试 | 登录与退出按钮点击正常 |")
        db.insert_chunks(doc_id, [c1, c2])

        cfg = AIConfig(llm_api_key="k", vector_enabled=False, top_k=2)
        vs = MagicMock()
        llm = MagicMock()
        r = Retriever(vs, db, llm, cfg)

        # 搜索特殊分辨率（英文/符号）
        res1 = r.retrieve("16384*2160")
        assert len(res1) == 1
        assert res1[0].chunk.chunk_index == 0
        assert "16384*2160" in res1[0].chunk.text

        # 搜索中文连续词
        res2 = r.retrieve("登录与退出")
        assert len(res2) == 1
        assert res2[0].chunk.chunk_index == 1


def test_rrf_merge_combines_dense_and_sparse():
    """验证 RRF 算法能融合稠密向量路与稀疏全文路。"""
    cfg = AIConfig(llm_api_key="k", vector_enabled=False, top_k=2)
    r = Retriever(MagicMock(), None, MagicMock(), cfg)

    doc = Document(id=1, filename="test.txt")
    c1 = Chunk(id=1, document_id=1, chunk_index=0, text="Chunk 1 (Dense 第一, Sparse 第二)")
    c2 = Chunk(id=2, document_id=1, chunk_index=1, text="Chunk 2 (Sparse 第一, Dense 第二)")
    c3 = Chunk(id=3, document_id=1, chunk_index=2, text="Chunk 3 (仅 Dense 第三)")

    sc1_d = ScoredChunk(chunk=c1, document=doc, score=0.9)
    sc2_d = ScoredChunk(chunk=c2, document=doc, score=0.8)
    sc3_d = ScoredChunk(chunk=c3, document=doc, score=0.7)

    sc2_s = ScoredChunk(chunk=c2, document=doc, score=0.95)
    sc1_s = ScoredChunk(chunk=c1, document=doc, score=0.85)

    # dense_results: [c1, c2, c3], sparse_results: [c2, c1]
    merged = r._rrf_merge([sc1_d, sc2_d, sc3_d], [sc2_s, sc1_s], k=2)
    assert len(merged) == 2
    # c1 和 c2 都有双路支持，远高于 c3
    chunk_ids = [m.chunk.id for m in merged]
    assert 1 in chunk_ids and 2 in chunk_ids
