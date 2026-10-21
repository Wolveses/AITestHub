# -*- coding: utf-8 -*-
"""测试 TableChunker 表格感知分块逻辑（方案 A：语义增强与跨块表头注入）。"""
import pytest

from insight_aitest.platform.services.kb.chunker import ChunkConfig, TableChunker
from insight_aitest.platform.services.kb.models import ParsedDocument


def test_table_chunker_small_text_single_chunk():
    chunker = TableChunker(ChunkConfig(chunk_size=500, chunk_overlap=80))
    doc = ParsedDocument(filename="test.xlsx", content="# Sheet1\n| 表头1 | 表头2 |\n|---|---|\n| 值1 | 值2 |", meta={"format": "xlsx"})
    chunks = chunker.split(doc)
    assert len(chunks) == 1
    assert "Sheet1" in chunks[0].text
    assert chunks[0].char_start == 0


def test_table_chunker_row_boundary_and_header_injection():
    """行级原子性与表头跨块注入测试。"""
    rows = [
        "# 测试用例表",
        "| 用例ID | 功能模块 | 前置条件 | 测试步骤 | 预期结果 |",
        "|---|---|---|---|---|",
    ]
    for i in range(20):
        rows.append(f"| TC_{i:03d} | 登录模块 | 用户已注册 | 1.输入用户名 2.输入密码 3.点击登录 | 页面跳转成功且显示欢迎信息_{i} |")
    text = "\n".join(rows)

    chunker = TableChunker(ChunkConfig(chunk_size=400, chunk_overlap=60))
    doc = ParsedDocument(filename="cases.xlsx", content=text, meta={"format": "xlsx"})
    chunks = chunker.split(doc)

    assert len(chunks) > 1
    for c in chunks:
        # 每个 chunk 都自闭环注入了表头，大模型可知字段含义
        assert "| 用例ID | 功能模块 |" in c.text
        assert "|---|---|---|" in c.text
        # 物理位置有效
        assert 0 <= c.char_start < c.char_end <= len(text)
        # 不存在折断破损行
        lines = c.text.splitlines()
        for l in lines:
            assert l.startswith("#") or l.startswith("|")


def test_table_chunker_multi_sheets():
    """多 Sheet 分割测试：不同 Sheet 独立切块，各自携带自己 Sheet 的表头。"""
    sheet1 = "# SheetA\n| Col1 | Col2 |\n|---|---|\n" + "\n".join([f"| A_{i} | Val_{i} |" for i in range(15)])
    sheet2 = "# SheetB\n| ColX | ColY |\n|---|---|\n" + "\n".join([f"| B_{i} | Val_{i} |" for i in range(15)])
    text = f"{sheet1}\n{sheet2}"

    chunker = TableChunker(ChunkConfig(chunk_size=300, chunk_overlap=30))
    doc = ParsedDocument(filename="multi.xlsx", content=text, meta={"format": "xlsx"})
    chunks = chunker.split(doc)

    assert len(chunks) >= 2
    sheet_a_chunks = [c for c in chunks if "SheetA" in c.text]
    sheet_b_chunks = [c for c in chunks if "SheetB" in c.text]
    assert len(sheet_a_chunks) >= 1
    assert len(sheet_b_chunks) >= 1

    for c in sheet_a_chunks:
        assert "Col1" in c.text
    for c in sheet_b_chunks:
        assert "ColX" in c.text
