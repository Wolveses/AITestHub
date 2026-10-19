# -*- coding: utf-8 -*-
"""PDF Loader：优先抽文本层；扫描件（无文本）走 OCR。

策略（按依赖可用性优雅降级）：
1) pymupdf（fitz）可用 → 抽文本层；扫描件则逐页 rasterize 成图片 → OCR 拼纯文本。
2) pymupdf 不可用 → 回退 pypdf 抽文本层；扫描件报错引导（保持旧行为）。

OCR 后端由 LLMConfig.ocr_enabled 控制：
  True  → LLM OCR（vision_model 读图，精度高，需联网 + API Key）
  False → 离线 OCR（rapidocr-onnxruntime，纯本地，零联网依赖，默认）
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

from insight_aitest.platform.services.kb.loader import register_loader
from insight_aitest.platform.services.kb.loader.base import (
    DocumentLoadError,
    DocumentLoader,
    OCR_PROMPT,
)
from insight_aitest.platform.services.kb.models import ParsedDocument

if TYPE_CHECKING:
    from insight_aitest.platform.services.llm.client import LLMClient

# 扫描件判定：每页平均字符数低于此阈值视为无文本层
_MIN_CHARS_PER_PAGE = 10

# rapidocr 模块级实例（惰性初始化，避免 import 时就加载模型到内存）
_rapidocr = None


def _ocr_uses_vlm() -> bool:
    """ocr_enabled=True 时走 VLM；False 走离线 rapidocr。"""
    try:
        from insight_aitest.platform.services.kb.deps import get_llm_config

        return get_llm_config().ocr_enabled
    except Exception:
        return False  # 保守：默认走离线


def _get_llm() -> "LLMClient":
    from insight_aitest.platform.services.kb.deps import get_llm

    return get_llm()


def _get_rapidocr():
    """惰性初始化 rapidocr-onnxruntime。

    返回 RapidOCR 实例，或 None（未安装）。
    """
    global _rapidocr
    if _rapidocr is not None:
        return _rapidocr
    try:
        from rapidocr_onnxruntime import RapidOCR

        _rapidocr = RapidOCR()
        return _rapidocr
    except ImportError:
        return None


def _pdf_rasterize_pages(doc) -> list[bytes]:
    """把 pymupdf doc 的每一页 rasterize 成 PNG bytes 列表（150dpi）。"""
    pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=150)
        pages.append(pix.tobytes("png"))
    return pages


def _ocr_vlm_image(img_bytes: bytes) -> str:
    """单张图片 bytes → LLM OCR 纯文本。"""
    llm = _get_llm()
    b64 = base64.b64encode(img_bytes).decode("ascii")
    return llm.chat_with_image(OCR_PROMPT, b64, mime="image/png").strip()


def _ocr_rapidocr_image(img_bytes: bytes) -> str:
    """单张图片 bytes → rapidocr 离线 OCR 纯文本。"""
    ocr = _get_rapidocr()
    if ocr is None:
        raise DocumentLoadError(
            "离线 OCR 不可用（rapidocr-onnxruntime 未安装）。"
            "请执行 `pip install rapidocr-onnxruntime`，或在设置中开启 LLM OCR。"
        )
    result, _ = ocr(img_bytes)
    if not result:
        return ""
    # result 是 list of [box, text, confidence]，按行拼接
    lines = [item[1] for item in result if item and len(item) >= 2]
    return "\n".join(lines).strip()


def _ocr_pdf_pages(doc) -> str:
    """PDF 扫描件 → 逐页 OCR → 拼纯文本。

    后端选择由 ocr_enabled 决定；失败时抛出带页码的 DocumentLoadError。
    """
    use_vlm = _ocr_uses_vlm()
    pages = _pdf_rasterize_pages(doc)
    texts = []
    for idx, img_bytes in enumerate(pages, start=1):
        try:
            if use_vlm:
                text = _ocr_vlm_image(img_bytes)
            else:
                text = _ocr_rapidocr_image(img_bytes)
        except Exception as e:
            raise DocumentLoadError(f"PDF 扫描件 OCR 失败（第 {idx} 页）: {e}") from e
        if text:
            texts.append(text)
    return "\n\n".join(texts)


@register_loader(".pdf")
class PdfLoader(DocumentLoader):
    def load(self, path: Path) -> ParsedDocument:
        try:
            import fitz  # pymupdf

            has_fitz = True
        except ImportError:
            fitz = None
            has_fitz = False

        # ---- pymupdf 路径（优先，支持扫描件 OCR）----
        if has_fitz:
            try:
                doc = fitz.open(str(path))
            except Exception as e:
                raise DocumentLoadError(f"PDF 解析失败: {e}") from e

            page_count = doc.page_count
            # 抽文本层
            text_pages = [page.get_text() or "" for page in doc]
            content = "\n\n".join(text_pages)
            is_scanned = page_count > 0 and len(content.strip()) < page_count * _MIN_CHARS_PER_PAGE

            if is_scanned:
                # 扫描件 → OCR 分支
                try:
                    content = _ocr_pdf_pages(doc)
                finally:
                    doc.close()
                if not content.strip():
                    raise DocumentLoadError("扫描件 OCR 未识别到文字内容。")
                return ParsedDocument(
                    filename=path.name,
                    content=content,
                    meta={
                        "mime_type": "application/pdf",
                        "page_count": page_count,
                        "char_count": len(content),
                        "scanned": True,
                        "ocr_backend": "vlm" if _ocr_uses_vlm() else "rapidocr",
                    },
                )

            doc.close()
            return ParsedDocument(
                filename=path.name,
                content=content,
                meta={
                    "mime_type": "application/pdf",
                    "page_count": page_count,
                    "char_count": len(content),
                    "scanned": False,
                },
            )

        # ---- pypdf 回退路径（无 OCR 能力，保持旧行为）----
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise DocumentLoadError(f"pypdf/pymupdf 均未安装: {e}") from e
        try:
            reader = PdfReader(str(path))
            pages = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
            content = "\n\n".join(pages)
        except Exception as e:
            raise DocumentLoadError(f"PDF 解析失败: {e}") from e

        page_count = len(reader.pages)
        if page_count > 0 and len(content.strip()) < page_count * _MIN_CHARS_PER_PAGE:
            raise DocumentLoadError(
                "该 PDF 似为扫描件（无可提取文本），未安装 pymupdf 无法 OCR。"
                "请安装 pymupdf 或提供带文本层的 PDF。"
            )
        return ParsedDocument(
            filename=path.name,
            content=content,
            meta={
                "mime_type": "application/pdf",
                "page_count": page_count,
                "char_count": len(content),
                "scanned": False,
            },
        )
