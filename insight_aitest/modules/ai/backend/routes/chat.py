# -*- coding: utf-8 -*-
"""对话 API：SSE 流式 /chat/stream + 会话附件。"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
import logging

logger = logging.getLogger(__name__)

from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from insight_aitest.modules.ai.backend.deps import get_agent, get_db, get_config
from insight_aitest.modules.ai.backend.persistence.database import AIDatabase
from insight_aitest.modules.ai.backend.persistence.models import Role

router = APIRouter(prefix="/chat", tags=["ai-chat"])


class ChatRequest(BaseModel):
    conversation_id: int
    query: str
    history_turns: int = 6
    document_ids: list[int] | None = None
    thinking_level: str | None = None  # off/low/medium/high；None 时回退会话级配置
    attachments: list[dict] | None = None
    use_kb: bool | None = None  # 请求级覆盖会话级 rag_enabled（None→用会话配置）


def _sse(event_type: str, data) -> str:
    payload = (
        data
        if isinstance(data, str)
        else json.dumps(data, ensure_ascii=False, default=lambda o: o.__dict__)
    )
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.post("/stream")
async def chat_stream(
    body: ChatRequest, agent=Depends(get_agent), db: AIDatabase = Depends(get_db)
):
    conv = db.get_conversation(body.conversation_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    history = db.list_messages_by_turns(body.conversation_id, turns=body.history_turns)
    history_msgs = [{"role": m.role.value, "content": m.content} for m in history]
    db.add_message(body.conversation_id, Role.USER, body.query, attachments=body.attachments)

    thinking_switch = (
        body.thinking_level
        if body.thinking_level is not None
        else getattr(conv, "thinking_level", "off")
    )
    # 防御：迁移中途脏数据（None / 非标准值）兜底为 off
    if not thinking_switch or thinking_switch not in ("off", "low", "medium", "high"):
        thinking_switch = "off"

    full_answer = [""]  # 用 list 闭包可变
    thinking_text = [""]
    citations_holder = [[]]

    # use_rag：请求级 use_kb 优先（None→用会话级 rag_enabled）
    use_rag = body.use_kb if body.use_kb is not None else conv.rag_enabled
    # KB 升级：按会话所属项目隔离检索（project_id 来自 Conversation）
    proj_id = getattr(conv, "project_id", None)

    logger.info(
        "[AI Chat] 收到对话请求 (会话 %s): query=%r, use_rag=%s, thinking_level=%s",
        body.conversation_id,
        body.query[:100],
        use_rag,
        thinking_switch,
    )

    async def event_gen():
        try:
            async for event in agent.stream_answer_async(
                body.query,
                history_msgs,
                body.document_ids,
                use_rag=use_rag,
                thinking_level=thinking_switch,
                project_id=proj_id,
            ):
                if event.type == "citations":
                    citations_holder[0] = event.data
                    # spec §6.4：data 包成 {"citations":[...]}，对齐前端解析
                    yield _sse("citations", {"citations": [c.__dict__ for c in event.data]})
                elif event.type == "thinking":
                    if thinking_switch != "off":
                        thinking_text[0] += event.data
                        yield _sse("thinking", {"text": event.data})
                elif event.type == "token":
                    full_answer[0] += event.data
                    yield _sse("token", {"text": event.data})
                elif event.type == "done":
                    logger.info(
                        "[AI Chat] 对话流式完成 (会话 %s): 回复字数=%d, 引用文献数=%d",
                        body.conversation_id,
                        len(full_answer[0]),
                        len(citations_holder[0]),
                    )
                    db.add_message(
                        body.conversation_id,
                        Role.ASSISTANT,
                        full_answer[0],
                        citations_holder[0],
                        thinking=thinking_text[0] or None,
                    )
                    yield _sse("done", {})
                elif event.type == "error":
                    # 写入错误占位消息，保证历史完整（避免 DB 残留孤立 user 消息）
                    db.add_message(
                        body.conversation_id,
                        Role.ASSISTANT,
                        "⚠️ 回复失败，请重试",
                    )
                    yield _sse("error", {"code": "internal", "message": _safe_error(event.data)})
        except Exception as e:
            # 写入错误占位消息，保证历史完整（避免 DB 残留孤立 user 消息）
            db.add_message(
                body.conversation_id,
                Role.ASSISTANT,
                "⚠️ 回复失败，请重试",
            )
            yield _sse("error", {"code": "internal", "message": _safe_error(e)})

    return StreamingResponse(event_gen(), media_type="text/event-stream")


_SAFE_ERROR_MSG = "internal error"


def _safe_error(detail: object) -> str:
    """Sanitize error detail for client-facing messages.

    Internal details (stack traces, file paths) are logged but not
    exposed to the SSE client. Only a generic message is returned.
    """
    logger.warning("Chat error: %s", detail)
    return _SAFE_ERROR_MSG


_ATTACHMENT_ID_RE = re.compile(r"^[a-f0-9]+\.[a-zA-Z0-9]+$")
_PREVIEW_MAX_CHARS = 2000


def _is_image_mime(mime: str) -> bool:
    return mime.startswith("image/")


def _extract_preview_text(filename: str, path: Path) -> str | None:
    """文档类附件：用 KB loader 抽纯文本前 N 字。失败返回 None。"""
    try:
        from insight_aitest.platform.services.kb.loader import get_loader

        loader = get_loader(filename)
        doc = loader.load(path)
        return doc.content[:_PREVIEW_MAX_CHARS]
    except Exception:
        # 不支持的格式 / 解析失败 → 不阻塞上传，仅 preview_text=None
        return None


@router.post("/attachments")
async def upload_attachments(
    files: list[UploadFile] = File(...),
    config=Depends(get_config),
) -> dict:
    """上传会话附件 → 存原始文件 + 返回附件元数据列表。

    图片：kind=image，preview_text=None。
    文档：kind=document，preview_text=KB loader 抽取纯文本前 2000 字。
    不入知识库（只服务本次对话预览）。
    """
    attachments_dir = Path(config.docs_dir) / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    result = []
    for f in files:
        content = await f.read()
        if len(content) > config.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"附件超过 {config.max_upload_mb}MB 限制")
        ext = Path(f.filename or "").suffix
        basename = f"{uuid.uuid4().hex}{ext}"
        storage_path = attachments_dir / basename
        storage_path.write_bytes(content)

        mime = f.content_type or "application/octet-stream"
        kind = "image" if _is_image_mime(mime) else "document"
        preview_text = None
        if kind == "document":
            preview_text = _extract_preview_text(f.filename or "", storage_path)

        result.append(
            {
                "id": basename,
                "filename": f.filename,
                "mime": mime,
                "kind": kind,
                "size": len(content),
                "preview_text": preview_text,
            }
        )

    return {"attachments": result}


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: str,
    config=Depends(get_config),
):
    """下载附件原始文件。attachment_id = storage basename（uuid.ext）。"""
    if not _ATTACHMENT_ID_RE.match(attachment_id):
        raise HTTPException(400, "非法附件 ID")

    path = Path(config.docs_dir) / "attachments" / attachment_id
    if not path.exists():
        raise HTTPException(404, "附件不存在")

    return FileResponse(str(path), filename=attachment_id)
