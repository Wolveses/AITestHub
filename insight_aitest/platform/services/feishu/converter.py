# -*- coding: utf-8 -*-
"""飞书 Docx blocks 转换为标准 Markdown。"""

from __future__ import annotations

from typing import Any


def docx_blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """将飞书 Docx blocks 转换为结构化 Markdown 字符串。"""
    if not blocks:
        return ""

    lines: list[str] = []

    def _extract_text_elements(elements: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for el in elements:
            # 文本类型
            if "text_run" in el:
                t = el["text_run"].get("content", "")
                style = el["text_run"].get("text_element_style", {})
                if style.get("bold"):
                    t = f"**{t}**"
                if style.get("italic"):
                    t = f"*{t}*"
                if style.get("inline_code"):
                    t = f"`{t}`"
                parts.append(t)
            # 链接类型
            elif "link" in el:
                url = el["link"].get("url", "")
                label = el["link"].get("content", url)
                parts.append(f"[{label}]({url})")
            # 提及
            elif "mention_user" in el:
                parts.append(f"@{el['mention_user'].get('user_id', '')}")
            elif "mention_doc" in el:
                parts.append(f"[{el['mention_doc'].get('title', '文档')}]({el['mention_doc'].get('url', '')})")
        return "".join(parts)

    for b in blocks:
        b_type = b.get("block_type")
        # 1: 页面级根块
        if b_type == 1:
            page = b.get("page", {})
            elements = page.get("elements", [])
            title = _extract_text_elements(elements)
            if title:
                lines.append(f"# {title}\n")
        # 2: 文本段落
        elif b_type == 2:
            elements = b.get("text", {}).get("elements", [])
            lines.append(_extract_text_elements(elements) + "\n")
        # 3-9: 标题 (Heading 1-9)
        elif 3 <= b_type <= 9:
            level = b_type - 2  # 3 -> h1, 4 -> h2, ...
            h_key = f"heading{level}"
            elements = b.get(h_key, {}).get("elements", [])
            text = _extract_text_elements(elements)
            lines.append(f"{'#' * min(level, 6)} {text}\n")
        # 12: 无序列表 (Bullet list)
        elif b_type == 12:
            elements = b.get("bullet", {}).get("elements", [])
            lines.append(f"- {_extract_text_elements(elements)}")
        # 13: 有序列表 (Ordered list)
        elif b_type == 13:
            elements = b.get("ordered", {}).get("elements", [])
            lines.append(f"1. {_extract_text_elements(elements)}")
        # 14: 代码块 (Code block)
        elif b_type == 14:
            code_block = b.get("code", {})
            lang = code_block.get("style", {}).get("language", "")
            elements = code_block.get("elements", [])
            code_text = _extract_text_elements(elements)
            lines.append(f"```{lang}\n{code_text}\n```\n")
        # 15: 引用块 (Quote)
        elif b_type == 15:
            elements = b.get("quote", {}).get("elements", [])
            lines.append(f"> {_extract_text_elements(elements)}\n")
        # 17: 分割线
        elif b_type == 17:
            lines.append("\n---\n")

    return "\n".join(lines).strip()

