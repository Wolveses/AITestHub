# -*- coding: utf-8 -*-
"""Excel 表格 Loader（.xlsx）。用 openpyxl 逐 sheet 提取每行单元格文本。"""

from __future__ import annotations

from pathlib import Path

from insight_aitest.platform.services.kb.loader import register_loader
from insight_aitest.platform.services.kb.loader.base import DocumentLoader
from insight_aitest.platform.services.kb.models import ParsedDocument


@register_loader(".xlsx")
class XlsxLoader(DocumentLoader):
    """Excel .xlsx 文档 Loader。逐 sheet 提取表头与各行，单元格用 ` | ` 拼接。"""

    def load(self, path: Path) -> ParsedDocument:
        from openpyxl import load_workbook

        # 注意：不要使用 read_only=True！很多 Excel 文件的 worksheet dimension 标记不准确（如仅写了 A1），
        # 在 read_only=True 模式下 openpyxl 依赖 dimension 会导致提前终止迭代，严重漏读行数据。
        wb = load_workbook(str(path), data_only=True)
        parts: list[str] = []

        for sheet in wb.worksheets:
            parts.append(f"# {sheet.title}")
            rows_iter = sheet.iter_rows(values_only=True)
            
            # 找到首个非空行作为表头
            headers: list[str] = []
            for row in rows_iter:
                if any(c is not None and str(c).strip() for c in row):
                    headers = [str(c).strip() if c is not None else "" for c in row]
                    # 表头行本身输出
                    header_cells = [h for h in headers if h]
                    if header_cells:
                        parts.append(" | ".join(header_cells))
                    break

            # 遍历后续数据行，结合表头生成 "表头: 单元格值" 形式，增强检索与向量语义
            for row in rows_iter:
                row_items: list[str] = []
                for idx, cell in enumerate(row):
                    if cell is None:
                        continue
                    val = str(cell).strip()
                    if not val:
                        continue
                    # 避免单元格内换行破坏单行 Markdown 结构
                    val = " ".join(val.splitlines())
                    header = headers[idx] if idx < len(headers) else ""
                    if header:
                        row_items.append(f"{header}: {val}")
                    else:
                        row_items.append(val)
                if row_items:
                    parts.append(" | ".join(row_items))

        wb.close()
        content = "\n".join(parts)
        return ParsedDocument(filename=path.name, content=content, meta={"format": "xlsx"})
