# -*- coding: utf-8 -*-
"""接口资产按需整理（仅用户点击时调用一次大模型）。

首跑抓包与入库全程不调用模型；本模块只负责：
- 组装脱敏后的资产摘要 + 提示词；
- 解析模型返回的 JSON（容错截断/尾随说明）；
- 本地推导响应结构断言（json_schema）与 jsonpath 样例，不让模型编造断言。
"""

from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit, urlunsplit

_SENSITIVE_KEYS = ("authorization", "cookie", "set-cookie", "proxy-authorization")
_SENSITIVE_WORDS = ("token", "secret", "password", "session", "api-key", "apikey")

_SYSTEM_PROMPT = """你是接口资产整理助手。根据抓包得到的单个 HTTP 接口信息，输出业务化命名与参数化建议。
只输出一个 JSON 对象，不要输出 Markdown、解释或多余文字。字段定义：
{
  "title": "业务化接口名称，中文，不超过 20 字",
  "summary": "一句话说明该接口的业务用途",
  "is_noise": false,
  "noise_reason": "仅当 is_noise 为 true 时填写",
  "path_template": "/api/users/{{user_id}}",
  "variables": [{"name": "user_id", "in": "path", "example": "123"}]
}
要求：
1. 禁止输出任何密钥、令牌、Cookie 或个人信息；
2. 不得修改 HTTP 方法；
3. 路径中动态的 ID、UUID、时间戳、分页游标等值抽象为 {{变量名}}，变量名用小写字母与下划线；
4. 无法确定时保持原路径；variables 最多 10 个；
5. 心跳、埋点、轮询、预加载等无业务含义的接口将 is_noise 置为 true。
"""

_MAX_FIELD_CHARS = 4096


def _dump_limited(value, limit: int = _MAX_FIELD_CHARS):
    """把请求/响应体压成有限长度的 JSON 文本，避免提示词过大。"""
    if value is None:
        return None
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def _strip_sensitive_headers(headers: dict | None) -> dict:
    out: dict = {}
    for key, value in (headers or {}).items():
        lowered = str(key).lower()
        if lowered in _SENSITIVE_KEYS or any(w in lowered for w in _SENSITIVE_WORDS):
            continue
        out[str(key)] = value
    return out


def _clean_path(path: str) -> str:
    """URL 中 query 的敏感参数值置为 <redacted>，避免 token 通过路径进入提示词。"""
    parts = urlsplit(path or "")
    if not parts.query:
        return path or ""
    query = "&".join(
        f"{key}={'<redacted>' if any(w in key.lower() for w in _SENSITIVE_WORDS) else value}"
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def build_payload(asset) -> dict:
    """组装给模型的脱敏摘要（不含凭证、超长体已截断）。"""
    return {
        "title": getattr(asset, "title", "") or "",
        "method": getattr(asset, "method", "") or "",
        "path": _clean_path(getattr(asset, "path", "") or ""),
        "path_template": _clean_path(getattr(asset, "path_template", "") or ""),
        "base_url": getattr(asset, "base_url", "") or "",
        "request_headers": _strip_sensitive_headers(getattr(asset, "headers", {})),
        "request_body": _dump_limited(getattr(asset, "body", None)),
        "response_status": getattr(asset, "response_status", 0) or 0,
        "response_headers": _strip_sensitive_headers(
            getattr(asset, "response_headers", {})
        ),
        "response_body": _dump_limited(getattr(asset, "response_body", None)),
    }


def build_messages(payload: dict) -> list[dict]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "接口抓包信息（JSON）：\n"
            + json.dumps(payload, ensure_ascii=False, default=str),
        },
    ]


def parse_result(text: str) -> dict:
    """容错解析模型输出：模型多写右括号或尾随说明时仍尽量取出 JSON。"""
    raw = (text or "").strip()
    decoder = json.JSONDecoder(strict=False)
    start = raw.find("{")
    if start < 0:
        raise ValueError("模型未返回 JSON 对象")
    try:
        data, _ = decoder.raw_decode(raw[start:])
    except ValueError as exc:
        raise ValueError(f"模型返回内容无法解析为 JSON：{raw[:120]}") from exc
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是 JSON 对象")

    title = str(data.get("title") or "").strip()[:80]
    variables = []
    for item in (data.get("variables") or [])[:10]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        variables.append(
            {
                "name": name[:40],
                "in": str(item.get("in") or "path")[:10],
                "example": str(item.get("example") or "")[:80],
            }
        )
    return {
        "title": title,
        "summary": str(data.get("summary") or "").strip()[:200],
        "is_noise": bool(data.get("is_noise")),
        "noise_reason": str(data.get("noise_reason") or "").strip()[:200],
        "path_template": str(data.get("path_template") or "").strip()[:300],
        "variables": variables,
    }


def enhance(asset, llm) -> dict:
    """调用一次模型，返回整理建议（不写库）。"""
    result = parse_result(
        llm.chat(build_messages(build_payload(asset)), temperature=0, max_tokens=600)
    )
    result["enhanced_at"] = datetime.now().isoformat(timespec="seconds")
    config = getattr(llm, "_config", None)
    result["model"] = getattr(config, "chat_model", "") if config else ""
    return result


def infer_schema(value, depth: int = 0) -> dict:
    """从响应样例推导结构断言用的 json_schema（只保留类型，不保留具体值）。"""
    if depth >= 5:
        return {}
    if isinstance(value, dict):
        properties = {}
        for key in list(value.keys())[:50]:
            properties[str(key)] = infer_schema(value[key], depth + 1)
        return {"type": "object", "properties": properties, "required": list(properties)}
    if isinstance(value, list):
        sample = infer_schema(value[0], depth + 1) if value else {}
        return {"type": "array", "items": sample}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if value is None:
        return {"type": "null"}
    return {"type": "string"}


def jsonpath_samples(value, limit: int = 20) -> list[dict]:
    """生成响应体字段路径样例（供人工参考，不作为可执行断言）。"""
    samples: list[dict] = []

    def walk(node, path: str) -> None:
        if len(samples) >= limit:
            return
        if isinstance(node, dict):
            for key, child in node.items():
                walk(child, f"{path}.{key}")
        elif isinstance(node, list):
            if node:
                walk(node[0], f"{path}[0]")
        else:
            samples.append({"path": path, "type": type(node).__name__, "sample": node})

    walk(value, "$")
    return samples
