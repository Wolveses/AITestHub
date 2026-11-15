# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from insight_aitest.platform.services.llm.config import AIConfig
from insight_aitest.platform.services.llm.client import LLMClient, LLMConfigError


def _cfg():
    return AIConfig(llm_api_key="sk-test", embed_dim=8)


def test_embed_calls_openai():
    client = LLMClient(_cfg())
    fake_resp = MagicMock()
    fake_resp.data = [MagicMock(embedding=[0.1] * 8, index=0),
                      MagicMock(embedding=[0.2] * 8, index=1)]
    with patch.object(client._client.embeddings, "create", return_value=fake_resp) as m:
        vecs = client.embed(["a", "b"])
    assert len(vecs) == 2
    # embed 返回的是归一化向量（L2 范数 = 1）
    import math
    for v in vecs:
        assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-6
    m.assert_called_once()


def test_embed_query_returns_single_vector():
    client = LLMClient(_cfg())
    fake_resp = MagicMock()
    fake_resp.data = [MagicMock(embedding=[0.5] * 8, index=0)]
    with patch.object(client._client.embeddings, "create", return_value=fake_resp):
        v = client.embed_query("hello")
    import math
    assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-6


def test_chat_returns_content():
    client = LLMClient(_cfg())
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="回答"))]
    with patch.object(client._client.chat.completions, "create", return_value=fake_resp) as m:
        ans = client.chat([{"role": "user", "content": "问"}])
    assert ans == "回答"
    m.assert_called_once()


def test_stream_chat_yields_tokens():
    client = LLMClient(_cfg())

    def fake_stream():
        for tok in ["你", "好", "世界"]:
            ch = MagicMock()
            ch.choices = [MagicMock(delta=MagicMock(content=tok))]
            yield ch

    with patch.object(client._client.chat.completions, "create", return_value=fake_stream()):
        toks = list(client.stream_chat([{"role": "user", "content": "hi"}]))
    assert toks == ["你", "好", "世界"]


def test_missing_key_raises_on_chat():
    cfg = AIConfig(llm_api_key="", embed_dim=8)
    client = LLMClient(cfg)
    import pytest
    with pytest.raises(LLMConfigError):
        client.chat([{"role": "user", "content": "x"}])


def test_chat_with_image_uses_vision_model():
    """多模态对话：用 vision_model，构造正确的 data URL message。"""
    cfg = AIConfig(
        llm_api_key="sk-test",
        embed_dim=8,
        chat_model="chat-m",
        vision_model="vision-m",
    )
    client = LLMClient(cfg)
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="OCR 文字结果"))]
    with patch.object(client._client.chat.completions, "create", return_value=fake_resp) as m:
        ans = client.chat_with_image("提取文字", "BASE64DATA", mime="image/png")
    assert ans == "OCR 文字结果"
    call_kwargs = m.call_args.kwargs
    assert call_kwargs["model"] == "vision-m"  # 用 vision_model
    content = call_kwargs["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "提取文字"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,BASE64DATA"


def test_chat_with_image_falls_back_to_chat_model():
    """vision_model 空时回退 chat_model。"""
    cfg = AIConfig(llm_api_key="sk-test", embed_dim=8, chat_model="chat-m", vision_model="")
    client = LLMClient(cfg)
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="ok"))]
    with patch.object(client._client.chat.completions, "create", return_value=fake_resp) as m:
        client.chat_with_image("p", "b64")
    assert m.call_args.kwargs["model"] == "chat-m"


def test_chat_with_image_missing_key_raises():
    cfg = AIConfig(llm_api_key="", embed_dim=8)
    client = LLMClient(cfg)
    import pytest
    with pytest.raises(LLMConfigError):
        client.chat_with_image("p", "b64")


def test_chat_with_images_delegates_to_chat():
    """多图对话复用统一 chat() 出口，使用 vision_model。"""
    cfg = AIConfig(
        llm_api_key="sk-test",
        embed_dim=8,
        chat_model="chat-m",
        vision_model="vision-m",
    )
    client = LLMClient(cfg)
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="多图结果"))]
    with patch.object(client._client.chat.completions, "create", return_value=fake_resp) as m:
        ans = client.chat_with_images(
            "对比两张图",
            [("B64_1", "image/png"), ("B64_2", "image/jpeg")],
        )
    assert ans == "多图结果"
    call_kwargs = m.call_args.kwargs
    assert call_kwargs["model"] == "vision-m"
    user_parts = call_kwargs["messages"][0]["content"]
    assert len(user_parts) == 3
    assert user_parts[0] == {"type": "text", "text": "对比两张图"}
    assert user_parts[1]["image_url"]["url"] == "data:image/png;base64,B64_1"
    assert user_parts[2]["image_url"]["url"] == "data:image/jpeg;base64,B64_2"


def test_sanitize_messages_truncates_base64():
    """Langfuse 追踪前自动将 base64 图片替换为摘要，避免负载爆炸。"""
    from insight_aitest.platform.services.llm.tracing import sanitize_messages_for_trace

    raw_msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "识别图片"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 5000}},
            ],
        }
    ]
    cleaned = sanitize_messages_for_trace(raw_msgs)
    img_url = cleaned[0]["content"][1]["image_url"]["url"]
    assert img_url.startswith("<data:image/png;base64, length=")
    assert "AAAA" not in img_url
    # 原消息不被原地修改
    assert raw_msgs[0]["content"][1]["image_url"]["url"].endswith("A" * 5000)


def test_langfuse_tracer_records_chat_and_context():
    """启用 Langfuse 时，chat 调用自动携带 trace_context 属性与 token usage。"""
    from insight_aitest.platform.services.llm.tracing import trace_context

    cfg = AIConfig(
        llm_api_key="sk-test",
        embed_dim=8,
        langfuse_enabled=True,
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-test",
        langfuse_host="http://localhost:3000",
    )
    mock_obs = MagicMock()
    mock_trace = MagicMock()
    mock_trace.generation.return_value = mock_obs
    mock_trace.span.return_value = mock_trace

    with patch("langfuse.Langfuse") as mock_lf_cls:
        mock_lf = MagicMock(spec=["trace", "flush", "shutdown"])
        mock_lf.trace.return_value = mock_trace
        mock_lf_cls.return_value = mock_lf
        client = LLMClient(cfg)

        fake_resp = MagicMock()
        fake_resp.choices = [MagicMock(message=MagicMock(content="ok", reasoning_content=None))]
        fake_resp.usage = MagicMock(prompt_tokens=12, completion_tokens=8, total_tokens=20)

        with patch.object(client._client.chat.completions, "create", return_value=fake_resp):
            with trace_context(
                name="ui.script.generate",
                session_id="ui-case-1",
                tags=["module:ui"],
                metadata={"case_id": 1},
            ):
                ans = client.chat([{"role": "user", "content": "hi"}])

        assert ans == "ok"
        assert mock_lf.trace.called
        assert mock_trace.generation.called
        mock_obs.update.assert_called_with(
            output="ok",
            usage_details={"input": 12, "output": 8, "total": 20},
        )
        assert mock_obs.end.called
