# -*- coding: utf-8 -*-
"""Image Loader：OCR 抽取图片中的文字。

后端选择由 LLMConfig.ocr_enabled 控制：
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

# 支持的图片扩展名 → mime
_IMG_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# rapidocr 模块级实例（惰性初始化，避免 import 时就加载模型到内存）
_rapidocr = None


def _ocr_uses_vlm() -> bool:
    try:
        from insight_aitest.platform.services.kb.deps import get_llm_config

        return get_llm_config().ocr_enabled
    except Exception:
        return False


def _get_rapidocr():
    global _rapidocr
    if _rapidocr is not None:
        return _rapidocr
    try:
        from rapidocr_onnxruntime import RapidOCR

        _rapidocr = RapidOCR()
        return _rapidocr
    except ImportError:
        return None


def _ocr_vlm(raw: bytes, mime: str) -> str:
    from insight_aitest.platform.services.kb.deps import get_llm

    llm = get_llm()
    b64 = base64.b64encode(raw).decode("ascii")
    return llm.chat_with_image(OCR_PROMPT, b64, mime=mime).strip()


def _ocr_rapidocr(raw: bytes) -> str:
    ocr = _get_rapidocr()
    if ocr is None:
        raise DocumentLoadError(
            "离线 OCR 不可用（rapidocr-onnxruntime 未安装）。"
            "请执行 `pip install rapidocr-onnxruntime`，或在设置中开启 LLM OCR。"
        )
    result, _ = ocr(raw)
    if not result:
        return ""
    lines = [item[1] for item in result if item and len(item) >= 2]
    return "\n".join(lines).strip()


@register_loader(".png")
@register_loader(".jpg")
@register_loader(".jpeg")
@register_loader(".gif")
@register_loader(".webp")
class ImageLoader(DocumentLoader):
    """图片文档 loader：OCR 抽取文字（LLM 或离线 rapidocr）。"""

    def __init__(self, llm: "LLMClient | None" = None) -> None:
        self._llm = llm

    def load(self, path: Path) -> ParsedDocument:
        ext = path.suffix.lower()
        mime = _IMG_MIME.get(ext)
        if mime is None:
            raise DocumentLoadError(f"不支持的图片格式: {ext}")

        try:
            raw = path.read_bytes()
        except OSError as e:
            raise DocumentLoadError(f"图片读取失败: {e}") from e

        use_vlm = _ocr_uses_vlm()
        try:
            content = _ocr_vlm(raw, mime) if use_vlm else _ocr_rapidocr(raw)
        except DocumentLoadError:
            raise  # 已经是友好错误信息
        except Exception as e:
            backend = "LLM" if use_vlm else "离线"
            raise DocumentLoadError(f"图片 {backend} OCR 失败: {e}") from e

        if not content:
            raise DocumentLoadError("图片未识别到文字内容（可能为纯图形）。")

        backend = "vlm" if use_vlm else "rapidocr"
        return ParsedDocument(
            filename=path.name,
            content=content,
            meta={
                "mime_type": mime,
                "ocr": True,
                "ocr_backend": backend,
                "byte_count": len(raw),
                "char_count": len(content),
            },
        )
