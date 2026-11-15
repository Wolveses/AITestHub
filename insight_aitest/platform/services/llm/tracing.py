# -*- coding: utf-8 -*-
"""Langfuse 大模型可观测性追踪服务（平台共享）。

设计目标：
1. 零侵入/故障隔离（Fail-Safe）：Langfuse 未启用、未安装、配置错误或网络不可达时，
   自动降级为空操作（No-Op），绝不阻塞或抛异常影响主业务大模型调用。
2. 多模态防爆：对 messages 中的 base64 图片自动脱敏摘要，避免数 MB 的图片撑爆上报队列。
3. 支持父级链路聚合（trace_context）：将 UI 脚本多轮生成、Agent 闭环任务、RAG 问答等
   多步调用聚合在同一条 Langfuse Trace / Session 下。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import logging
from typing import Any, Iterator

from insight_aitest.platform.services.llm.config import LLMConfig

logger = logging.getLogger("insight_aitest.llm.tracing")

# 当前协程/线程上下文中的业务属性（供 LLMClient 自动继承 tags / session_id / metadata）
_trace_attrs_var: ContextVar[dict[str, Any] | None] = ContextVar(
    "insight_langfuse_trace_attrs", default=None
)


def sanitize_messages_for_trace(messages: Any) -> Any:
    """深拷贝并压缩 messages 中的超长 base64 图片数据，防止上报负载过大。"""
    if not isinstance(messages, list):
        return messages
    cleaned = []
    for msg in messages:
        if not isinstance(msg, dict):
            cleaned.append(msg)
            continue
        content = msg.get("content")
        if isinstance(content, list):
            new_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    img_obj = item.get("image_url") or {}
                    url = img_obj.get("url", "") if isinstance(img_obj, dict) else ""
                    if "base64," in url:
                        prefix = url.split("base64,")[0]
                        url_summary = f"<{prefix}base64, length={len(url)}>"
                    else:
                        url_summary = url[:200]
                    new_parts.append({"type": "image_url", "image_url": {"url": url_summary}})
                else:
                    new_parts.append(item)
            cleaned.append({**msg, "content": new_parts})
        else:
            cleaned.append(msg)
    return cleaned


def _clean_model_parameters(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """将 model_parameters 过滤为 Langfuse 允许的标量/简单字典结构。"""
    if not params:
        return None
    out: dict[str, Any] = {}
    for k, v in params.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            out[k] = v
        else:
            out[k] = str(v)
    return out


class _NoopObservation:
    """Langfuse 未启用或异常时的空操作兜底对象。"""

    def update(self, **kwargs: Any) -> "_NoopObservation":
        return self

    def end(self, **kwargs: Any) -> None:
        pass


class LangfuseTracer:
    """绑定于 LLMClient 的 Langfuse 追踪器。"""

    def __init__(self, config: LLMConfig) -> None:
        self._enabled = bool(
            getattr(config, "langfuse_enabled", False)
            and getattr(config, "langfuse_public_key", "").strip()
            and getattr(config, "langfuse_secret_key", "").strip()
        )
        self._client = None
        if self._enabled:
            try:
                from langfuse import Langfuse
                import inspect

                host = (getattr(config, "langfuse_host", "") or "http://localhost:3000").strip()
                sig = inspect.signature(Langfuse.__init__)
                init_kwargs: dict[str, Any] = {
                    "public_key": config.langfuse_public_key.strip(),
                    "secret_key": config.langfuse_secret_key.strip(),
                    "host": host,
                }
                if "tracing_enabled" in sig.parameters:
                    init_kwargs["tracing_enabled"] = True
                elif "enabled" in sig.parameters:
                    init_kwargs["enabled"] = True
                self._client = Langfuse(**init_kwargs)
                logger.info("Langfuse tracing 已启用 (host=%s)", host)
            except Exception as e:
                logger.warning("Langfuse 初始化失败，已自动降级禁用: %s", e)
                self._client = None
                self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled and self._client is not None

    def flush(self) -> None:
        if self._client is not None:
            try:
                self._client.flush()
            except Exception as e:
                logger.debug("Langfuse flush 异常: %s", e)

    def shutdown(self) -> None:
        if self._client is not None:
            try:
                self._client.shutdown()
            except Exception as e:
                logger.debug("Langfuse shutdown 异常: %s", e)

    @contextmanager
    def observe_generation(
        self,
        name: str,
        *,
        model: str,
        input_data: Any,
        model_parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        as_type: str = "generation",
    ) -> Iterator[Any]:
        """包裹一次 LLM 调用（chat / stream_chat_raw / embed），自动上报 Generation / Embedding。"""
        if not self.enabled or self._client is None:
            yield _NoopObservation()
            return

        ctx_attrs = _trace_attrs_var.get() or {}
        merged_meta = {**(ctx_attrs.get("metadata") or {}), **(metadata or {})}
        clean_params = _clean_model_parameters(model_parameters)
        clean_input = sanitize_messages_for_trace(input_data)

        obs_cm = None
        prop_cm = None
        v2_gen = None
        obs = _NoopObservation()
        try:
            if hasattr(self._client, "start_as_current_observation"):
                # Langfuse SDK v3+ (OTel)
                try:
                    from langfuse import propagate_attributes

                    if ctx_attrs:
                        prop_cm = propagate_attributes(
                            trace_name=ctx_attrs.get("trace_name"),
                            session_id=ctx_attrs.get("session_id"),
                            user_id=ctx_attrs.get("user_id"),
                            tags=ctx_attrs.get("tags"),
                            metadata={k: str(v) for k, v in merged_meta.items()} if merged_meta else None,
                        )
                        prop_cm.__enter__()
                except ImportError:
                    pass

                obs_cm = self._client.start_as_current_observation(
                    name=name,
                    as_type=as_type,  # type: ignore[arg-type]
                    model=model,
                    input=clean_input,
                    model_parameters=clean_params,
                    metadata=merged_meta or None,
                )
                obs = obs_cm.__enter__()
            elif hasattr(self._client, "trace"):
                # Langfuse SDK v2.x (Ingestion API，兼容轻量版 v2 与 v3 服务端)
                parent = ctx_attrs.get("parent")
                if parent is None:
                    parent = self._client.trace(
                        name=ctx_attrs.get("trace_name") or name,
                        session_id=ctx_attrs.get("session_id"),
                        user_id=ctx_attrs.get("user_id"),
                        tags=ctx_attrs.get("tags"),
                        metadata=merged_meta or None,
                        input=clean_input,
                    )
                v2_gen = parent.generation(
                    name=name,
                    model=model,
                    input=clean_input,
                    model_parameters=clean_params,
                    metadata=merged_meta or None,
                )
                obs = v2_gen
        except Exception as e:
            logger.debug("Langfuse start observation 失败（已忽略）: %s", e)
            obs_cm = None
            v2_gen = None
            obs = _NoopObservation()

        try:
            yield obs
        except Exception as call_err:
            try:
                obs.update(level="ERROR", status_message=str(call_err))
            except Exception:
                pass
            raise
        finally:
            if v2_gen is not None:
                try:
                    v2_gen.end()
                except Exception as e:
                    logger.debug("Langfuse v2 end generation 失败（已忽略）: %s", e)
            if obs_cm is not None:
                try:
                    obs_cm.__exit__(None, None, None)
                except Exception as e:
                    logger.debug("Langfuse end observation 失败（已忽略）: %s", e)
            if prop_cm is not None:
                try:
                    prop_cm.__exit__(None, None, None)
                except Exception:
                    pass


@contextmanager
def trace_context(
    name: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    input_data: Any = None,
) -> Iterator[Any]:
    """业务链路级追踪上下文：将同一业务动作下的多次 LLM 调用聚合到同一个父级 Span / Trace。"""
    prev = _trace_attrs_var.get() or {}
    merged_tags = list(dict.fromkeys([*(prev.get("tags") or []), *(tags or [])]))
    merged_meta = {**(prev.get("metadata") or {}), **(metadata or {})}
    new_attrs: dict[str, Any] = {
        "trace_name": prev.get("trace_name") or name,
        "session_id": session_id or prev.get("session_id"),
        "user_id": user_id or prev.get("user_id"),
        "tags": merged_tags or None,
        "metadata": merged_meta or None,
        "parent": prev.get("parent"),
    }

    span_cm = None
    prop_cm = None
    v2_span = None
    span_obj: Any = _NoopObservation()
    try:
        from insight_aitest.platform.services.kb.deps import get_llm

        llm = get_llm()
        tracer: LangfuseTracer | None = getattr(llm, "_tracer", None)
        if tracer and tracer.enabled and tracer._client is not None:
            if hasattr(tracer._client, "start_as_current_observation"):
                try:
                    from langfuse import propagate_attributes

                    prop_cm = propagate_attributes(
                        trace_name=new_attrs["trace_name"],
                        session_id=new_attrs["session_id"],
                        user_id=new_attrs["user_id"],
                        tags=new_attrs["tags"],
                        metadata={k: str(v) for k, v in merged_meta.items()} if merged_meta else None,
                    )
                    prop_cm.__enter__()
                except ImportError:
                    pass
                span_cm = tracer._client.start_as_current_observation(
                    name=name,
                    as_type="span",
                    input=input_data,
                    metadata=merged_meta or None,
                )
                span_obj = span_cm.__enter__()
            elif hasattr(tracer._client, "trace"):
                parent = prev.get("parent")
                if parent is None:
                    trace_obj = tracer._client.trace(
                        name=new_attrs["trace_name"],
                        session_id=new_attrs["session_id"],
                        user_id=new_attrs["user_id"],
                        tags=new_attrs["tags"],
                        metadata=merged_meta or None,
                        input=input_data,
                    )
                    v2_span = trace_obj.span(
                        name=name,
                        input=input_data,
                        metadata=merged_meta or None,
                    )
                else:
                    v2_span = parent.span(
                        name=name,
                        input=input_data,
                        metadata=merged_meta or None,
                    )
                span_obj = v2_span
                new_attrs["parent"] = v2_span
    except Exception as e:
        logger.debug("trace_context 启动跳过: %s", e)
        span_cm = None
        v2_span = None

    token = _trace_attrs_var.set(new_attrs)
    try:
        yield span_obj
    except Exception as err:
        try:
            span_obj.update(level="ERROR", status_message=str(err))
        except Exception:
            pass
        raise
    finally:
        if v2_span is not None:
            try:
                v2_span.end()
            except Exception:
                pass
        if span_cm is not None:
            try:
                span_cm.__exit__(None, None, None)
            except Exception:
                pass
        if prop_cm is not None:
            try:
                prop_cm.__exit__(None, None, None)
            except Exception:
                pass
        _trace_attrs_var.reset(token)


def extract_openai_usage(resp: Any) -> dict[str, int] | None:
    """从 OpenAI ChatCompletion / Embedding 响应或流式 chunk 中提取 token 用量。"""
    usage = getattr(resp, "usage", None)
    if not usage:
        return None
    details: dict[str, int] = {}
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)
    if isinstance(prompt_tokens, int):
        details["input"] = prompt_tokens
    if isinstance(completion_tokens, int):
        details["output"] = completion_tokens
    if isinstance(total_tokens, int):
        details["total"] = total_tokens
    return details or None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def test_langfuse_connection(host: str, public_key: str, secret_key: str) -> tuple[bool, str]:
    """测试 Langfuse 连通性与密钥有效性（供设置面板「测试连通」按钮调用）。"""
    host = (host or "").strip()
    public_key = (public_key or "").strip()
    secret_key = (secret_key or "").strip()
    if not host:
        return False, "请填写 Langfuse Host 地址"
    if not public_key:
        return False, "请填写 Public Key"
    if not secret_key:
        return False, "请填写 Secret Key"
    try:
        from langfuse import Langfuse
        import inspect

        sig = inspect.signature(Langfuse.__init__)
        init_kwargs: dict[str, Any] = {
            "public_key": public_key,
            "secret_key": secret_key,
            "host": host,
            "timeout": 10,
        }
        if "tracing_enabled" in sig.parameters:
            init_kwargs["tracing_enabled"] = False
        elif "enabled" in sig.parameters:
            init_kwargs["enabled"] = False
        client = Langfuse(**init_kwargs)
        ok = client.auth_check()
        client.shutdown()
        if ok:
            return True, f"连接成功（{host}）"
        return False, "认证失败：Public Key 或 Secret Key 不正确"
    except Exception as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg or "credentials" in msg.lower():
            return False, "认证失败：Public Key 或 Secret Key 无效"
        if "ConnectError" in type(e).__name__ or "Connection" in msg or "timed out" in msg.lower():
            return False, f"无法连接到 Langfuse 服务 ({host})：{msg}"
        return False, f"连接异常：{type(e).__name__}: {msg}"
