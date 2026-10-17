# -*- coding: utf-8 -*-
"""OpenAI 兼容 LLM 客户端（平台共享服务）。chat 与 embedding 用同一 base_url + key。

从 ai 模块上提，ai 和 testcase 模块共用。不抽象 Provider——首版只有 OpenAI 兼容一个实现。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Iterator

from insight_aitest.platform.services.llm.config import LLMConfig
from insight_aitest.platform.services.llm.thinking import resolve_thinking_params

logger = logging.getLogger("insight_aitest.llm")

ChatMessage = dict  # {role, content}


def _format_messages_for_log(messages: list[ChatMessage]) -> str:
    """格式化 messages 为可读的字符串，并对图片 base64 做脱敏压缩，防止撑爆日志文件"""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif item.get("type") == "image_url":
                        url = item.get("image_url", {}).get("url", "")
                        if "base64," in url:
                            prefix = url.split("base64,")[0]
                            parts.append(f"<{prefix}base64, length={len(url)}>")
                        else:
                            parts.append(f"<image_url: {url[:60]}>")
                    else:
                        parts.append(str(item))
                else:
                    parts.append(str(item))
            lines.append(f"  [{role}]: {' '.join(parts)}")
        else:
            lines.append(f"  [{role}]: {content}")
    return "\n".join(lines)


class LLMConfigError(Exception):
    """LLM 配置错误（如 key 缺失）。"""


class LLMUnavailableError(Exception):
    """LLM 服务不可用（网络/限流/超时，重试耗尽后抛出）。"""


# 重试配置（瞬时错误：限流/超时/连接失败）
_MAX_RETRIES = 3
_RETRY_DELAYS = [1, 2, 4]  # 指数退避秒数
# 可重试的 OpenAI SDK 异常（瞬时）
_RETRYABLE = (
    "RateLimitError",
    "APITimeoutError",
    "APIConnectionError",
    "InternalServerError",
)


def _is_retryable(e: Exception) -> bool:
    """判断异常是否可重试（限流/超时/连接/5xx 内部错误）。"""
    return any(type(e).__name__ == name for name in _RETRYABLE)


def _retry_call(fn, *args, **kwargs):
    """带指数退避的重试包装。瞬时错误重试 ≤3 次（1s/2s/4s），耗尽后抛 LLMUnavailableError。

    不可重试的错误（AuthenticationError/BadRequestError/NotFoundError）原样抛出。
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if not _is_retryable(e) or attempt == _MAX_RETRIES:
                break
            time.sleep(_RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)])
    # 重试耗尽：瞬时错误转 LLMUnavailableError，配置/参数错误原样抛
    if last_exc is None:
        raise RuntimeError("_retry_call 退出但无异常（不应发生）")
    if _is_retryable(last_exc):
        raise LLMUnavailableError(
            f"LLM 服务不可用（重试 {_MAX_RETRIES} 次后仍失败）: {last_exc}"
        ) from last_exc
    raise last_exc


def _normalize(vec: list[float]) -> list[float]:
    """L2 归一化：归一化向量的 L2 距离等价于余弦距离（用于 RAG 召回）。"""
    import math

    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        from openai import OpenAI

        self._config = config
        self._client = OpenAI(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key or "missing",
            timeout=config.llm_timeout,
        )
        self._chat_model = config.chat_model
        self._embed_model = config.embed_model
        # embedding 可走独立端点（当 chat 端点无 embedding 模型时，如 agnes → 智谱 embedding）
        # embed_base_url/embed_api_key 留空则与 chat 共用主 client（向后兼容）
        embed_base = config.embed_base_url or config.llm_base_url
        embed_key = config.embed_api_key or config.llm_api_key or "missing"
        if embed_base == config.llm_base_url and embed_key == (config.llm_api_key or "missing"):
            self._embed_client = self._client  # 共用，避免多余连接
        else:
            self._embed_client = OpenAI(
                base_url=embed_base,
                api_key=embed_key,
                timeout=config.llm_timeout,
            )

    def _ensure_key(self) -> None:
        if not self._config.llm_api_key:
            raise LLMConfigError("未配置 LLM API Key，请在设置中配置。")

    def embed(self, texts: list[str]) -> list[list[float]]:
        # embedding 用独立 client（embed_base_url 配置时）；key 检查覆盖 embed_api_key 回退链
        embed_key = self._config.embed_api_key or self._config.llm_api_key
        if not embed_key:
            raise LLMConfigError("未配置 LLM API Key，请在设置中配置。")
        if not texts:
            return []

        # 多数第三方提供商（如 DashScope 百炼）限制单批次请求不超过 25 条，取安全上限 20 自动子批次切分
        batch_size = min(getattr(self._config, "embed_batch_size", 20) or 20, 20)
        all_normalized: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk_texts = texts[i : i + batch_size]
            resp = self._embed_client.embeddings.create(model=self._embed_model, input=chunk_texts)
            ordered = sorted(resp.data, key=lambda d: d.index)
            # L2 归一化：sqlite-vec 默认用 L2（欧氏）距离，归一化后
            # L2 距离与余弦距离等价（||a-b||² = 2(1-cos)），RAG 召回更准
            all_normalized.extend([_normalize(d.embedding) for d in ordered])
        return all_normalized

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def chat(self, messages: list[ChatMessage], thinking_level: str = "off", **kwargs) -> str:
        self._ensure_key()
        # 合并思考级别参数（按模型族探测，off/不支持时为空 dict）
        call_kwargs = dict(kwargs)
        thinking_params = resolve_thinking_params(self._chat_model, thinking_level)
        if "extra_body" in thinking_params:
            merged_extra = dict(call_kwargs.get("extra_body") or {})
            merged_extra.update(thinking_params["extra_body"])
            call_kwargs["extra_body"] = merged_extra
        else:
            call_kwargs.update(thinking_params)

        req_id = uuid.uuid4().hex[:8]
        start_time = time.time()
        logger.info(
            "\n%s [LLM Request] (req_id=%s) %s\n"
            "Model: %s\n"
            "Parameters: %s\n"
            "Messages (%d turns):\n%s\n%s",
            "=" * 28,
            req_id,
            "=" * 28,
            self._chat_model,
            call_kwargs,
            len(messages),
            _format_messages_for_log(messages),
            "=" * 78,
        )

        try:
            resp = _retry_call(
                self._client.chat.completions.create,
                model=self._chat_model,
                messages=messages,
                **call_kwargs,
            )
            content = resp.choices[0].message.content or ""
            elapsed = time.time() - start_time
            if not content.strip():
                raise LLMUnavailableError("模型返回空回复，请重试或检查模型配置")

            logger.info(
                "\n%s [LLM Response] (req_id=%s, 耗时 %.2fs) %s\n" "%s\n%s",
                "=" * 28,
                req_id,
                elapsed,
                "=" * 28,
                content,
                "=" * 82,
            )
            return content
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                "\n%s [LLM Error] (req_id=%s, 耗时 %.2fs) %s\n" "Error: %s\n%s",
                "=" * 28,
                req_id,
                elapsed,
                "=" * 28,
                e,
                "=" * 82,
            )
            raise

    def chat_with_image(
        self, prompt: str, image_base64: str, mime: str = "image/png", **kwargs
    ) -> str:
        """多模态对话：发文本 + 图片（OpenAI 兼容 vision 协议），返回文本。

        用 vision_model（空则回退 chat_model，与 ui executor 一致）。
        图片以 data URL 形式传入：data:<mime>;base64,<image_base64>。
        """
        self._ensure_key()
        model = self._config.vision_model or self._chat_model
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{image_base64}"},
                    },
                ],
            }
        ]

        req_id = uuid.uuid4().hex[:8]
        start_time = time.time()
        logger.info(
            "\n%s [LLM Vision Request] (req_id=%s) %s\n"
            "Model: %s\n"
            "Parameters: %s\n"
            "Prompt: %s\n"
            "Image: <mime=%s, base64_len=%d>\n%s",
            "=" * 25,
            req_id,
            "=" * 25,
            model,
            kwargs,
            prompt,
            mime,
            len(image_base64),
            "=" * 78,
        )

        try:
            resp = _retry_call(
                self._client.chat.completions.create,
                model=model,
                messages=messages,
                **kwargs,
            )
            content = resp.choices[0].message.content or ""
            elapsed = time.time() - start_time
            if not content.strip():
                raise LLMUnavailableError("模型返回空回复，请重试或检查视觉模型配置")

            logger.info(
                "\n%s [LLM Vision Response] (req_id=%s, 耗时 %.2fs) %s\n" "%s\n%s",
                "=" * 25,
                req_id,
                elapsed,
                "=" * 25,
                content,
                "=" * 82,
            )
            return content
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                "\n%s [LLM Vision Error] (req_id=%s, 耗时 %.2fs) %s\n" "Error: %s\n%s",
                "=" * 25,
                req_id,
                elapsed,
                "=" * 25,
                e,
                "=" * 82,
            )
            raise

    def chat_with_images(self, prompt: str, images: list[tuple[str, str]], **kwargs) -> str:
        """多图多模态对话：发文本 + 多张图片（OpenAI 兼容 vision 协议），返回文本。

        images: [(image_base64, mime), ...] 列表，至少 1 张。
        每张图以 data URL 形式传入 content 数组。
        用 vision_model（空则回退 chat_model，与 chat_with_image 一致）。
        """
        assert images, "chat_with_images 至少需要 1 张图片"
        self._ensure_key()
        model = self._config.vision_model or self._chat_model
        content: list[dict] = [{"type": "text", "text": prompt}]
        for image_base64, mime in images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{image_base64}"},
                }
            )
        messages = [{"role": "user", "content": content}]

        req_id = uuid.uuid4().hex[:8]
        start_time = time.time()
        logger.info(
            "\n%s [LLM Multi-Vision Request] (req_id=%s) %s\n"
            "Model: %s\n"
            "Parameters: %s\n"
            "Prompt: %s\n"
            "Images Count: %d\n%s",
            "=" * 23,
            req_id,
            "=" * 23,
            model,
            kwargs,
            prompt,
            len(images),
            "=" * 78,
        )

        try:
            resp = _retry_call(
                self._client.chat.completions.create,
                model=model,
                messages=messages,
                **kwargs,
            )
            content_out = resp.choices[0].message.content or ""
            elapsed = time.time() - start_time
            if not content_out.strip():
                raise LLMUnavailableError("模型返回空回复，请重试或检查视觉模型配置")

            logger.info(
                "\n%s [LLM Multi-Vision Response] (req_id=%s, 耗时 %.2fs) %s\n" "%s\n%s",
                "=" * 23,
                req_id,
                elapsed,
                "=" * 23,
                content_out,
                "=" * 82,
            )
            return content_out
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                "\n%s [LLM Multi-Vision Error] (req_id=%s, 耗时 %.2fs) %s\n" "Error: %s\n%s",
                "=" * 23,
                req_id,
                elapsed,
                "=" * 23,
                e,
                "=" * 82,
            )
            raise

    def stream_chat_raw(
        self, messages: list[ChatMessage], thinking_level: str = "off", **kwargs
    ) -> Iterator[tuple[str, str]]:
        """流式聊天（原始）：yield (kind, text) 元组。

        kind="reasoning" ← delta.reasoning_content（GLM/DeepSeek-R1 类）或 delta.reasoning（OpenAI o 系列原生 SDK）。
        kind="content"   ← delta.content（正常回答）。
        模型不吐 reasoning 时只 yield content（getattr 安全降级）。
        thinking_level 按 model 探测注入 reasoning_effort/thinking 参数。
        流式启动时重试（首 chunk 前），流中途断不重试（避免重复内容）。
        流结束后若既无 content 也无 reasoning → 抛 LLMUnavailableError（空回复检测）。
        """
        self._ensure_key()
        # 合并思考级别参数（按模型族探测，off/不支持时为空 dict）
        call_kwargs = dict(kwargs)
        thinking_params = resolve_thinking_params(self._chat_model, thinking_level)
        if "extra_body" in thinking_params:
            merged_extra = dict(call_kwargs.get("extra_body") or {})
            merged_extra.update(thinking_params["extra_body"])
            call_kwargs["extra_body"] = merged_extra
        else:
            call_kwargs.update(thinking_params)

        req_id = uuid.uuid4().hex[:8]
        start_time = time.time()
        logger.info(
            "\n%s [LLM Request (Stream)] (req_id=%s) %s\n"
            "Model: %s\n"
            "Parameters: %s\n"
            "Messages (%d turns):\n%s\n%s",
            "=" * 25,
            req_id,
            "=" * 25,
            self._chat_model,
            call_kwargs,
            len(messages),
            _format_messages_for_log(messages),
            "=" * 87,
        )

        # 流式启动重试（create 调用本身可能因限流/超时失败）
        try:
            stream = _retry_call(
                self._client.chat.completions.create,
                model=self._chat_model,
                messages=messages,
                stream=True,
                **call_kwargs,
            )
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                "\n%s [LLM Stream Start Error] (req_id=%s, 耗时 %.2fs) %s\n" "Error: %s\n%s",
                "=" * 25,
                req_id,
                elapsed,
                "=" * 25,
                e,
                "=" * 87,
            )
            raise

        has_any = False
        collected_reasoning: list[str] = []
        collected_content: list[str] = []

        try:
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta:
                    # 兼容两家字段名：GLM/DeepSeek 用 reasoning_content，OpenAI o 系列原生 SDK 用 reasoning
                    reasoning = getattr(delta, "reasoning_content", None) or getattr(
                        delta, "reasoning", None
                    )
                    if reasoning:
                        has_any = True
                        collected_reasoning.append(reasoning)
                        if thinking_level != "off":
                            yield ("reasoning", reasoning)
                    if delta.content:
                        has_any = True
                        collected_content.append(delta.content)
                        yield ("content", delta.content)

            elapsed = time.time() - start_time
            # 空回复检测：整条流既无 content 也无 reasoning → 异常（不静默返回空）
            if not has_any:
                raise LLMUnavailableError("模型流式返回为空，请重试或检查模型配置")

            full_reasoning = "".join(str(c) for c in collected_reasoning).strip()
            full_content = "".join(str(c) for c in collected_content).strip()

            log_parts = []
            if full_reasoning:
                log_parts.append(
                    f"Reasoning/Thinking ({len(full_reasoning)} 字):\n{full_reasoning}"
                )
            log_parts.append(f"Content ({len(full_content)} 字):\n{full_content}")

            logger.info(
                "\n%s [LLM Response (Stream)] (req_id=%s, 耗时 %.2fs) %s\n" "%s\n%s",
                "=" * 25,
                req_id,
                elapsed,
                "=" * 25,
                "\n\n".join(log_parts),
                "=" * 88,
            )
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                "\n%s [LLM Stream Error] (req_id=%s, 耗时 %.2fs) %s\n" "Error: %s\n%s",
                "=" * 25,
                req_id,
                elapsed,
                "=" * 25,
                e,
                "=" * 87,
            )
            raise

    def stream_chat(self, messages: list[ChatMessage], **kwargs) -> Iterator[str]:
        """流式聊天（兼容旧）：只 yield content 文本（过滤 reasoning）。"""
        for kind, text in self.stream_chat_raw(messages, **kwargs):
            if kind == "content":
                yield text


def test_connection(base_url: str, api_key: str, model: str, timeout: int = 20) -> tuple[bool, str]:
    """用临时 client 探测连通性（不发正式 chat，用 models.list 或最小 chat 请求）。

    返回 (ok, message)。成功时 message 为模型名或 "ok"；失败时为错误描述。
    不影响全局单例，不读取配置文件——纯临时 client。
    """
    from openai import OpenAI

    if not base_url:
        return False, "Base URL 为空"
    if not api_key:
        return False, "API Key 为空"
    if not model:
        return False, "模型名为空"
    try:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        # 先尝试 models.list（轻量，部分 OpenAI 兼容端点不支持）
        try:
            models = client.models.list()
            ids = [m.id for m in models.data]
            # 若目标模型在列表中，直接确认；否则仍用 chat 探测（list 不全或模型名自由输入）
            if model in ids:
                return True, f"ok（{model} 在模型列表中）"
        except Exception:
            pass  # list 不支持也无妨，下面用 chat 探测
        # 用最小 chat 请求确认 key + model 可用
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        return True, f"ok（{model} 响应正常）"
    except Exception as e:
        name = type(e).__name__
        msg = str(e)
        # 常见错误分类提示
        if "Authentication" in name or "401" in msg or "api key" in msg.lower():
            return False, f"认证失败：API Key 无效（{name}）"
        if "NotFound" in name or "404" in msg or "model" in msg.lower():
            return False, f"模型不存在或无权访问：{model}（{name}）"
        if "Connection" in name or "Timeout" in name or "timed out" in msg.lower():
            return False, f"连接失败：{msg}（{name}）"
        return False, f"{name}: {msg}"
