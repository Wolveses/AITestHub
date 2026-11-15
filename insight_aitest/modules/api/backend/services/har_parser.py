import json
from urllib.parse import parse_qsl, urlsplit
from typing import Any
from insight_aitest.modules.ui.backend.automation.capture import (
    _STATIC_RESOURCE_TYPES,
    _STATIC_SUFFIXES,
    _AUTH_PATH_RE,
    _clean_query,
    clean_headers,
    redact_body,
    _parse_request_body,
    path_template,
    fingerprint,
)

def parse_har_to_candidates(har_text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(har_text)
    except Exception as exc:
        raise ValueError(f"HAR 内容必须是有效的 JSON 格式: {exc}")

    entries = []
    if isinstance(data, dict):
        if "log" in data and isinstance(data["log"], dict) and "entries" in data["log"]:
            entries = data["log"]["entries"]
        elif "entries" in data and isinstance(data["entries"], list):
            entries = data["entries"]
    elif isinstance(data, list):
        entries = data

    if not isinstance(entries, list):
        raise ValueError("未在 HAR 中找到有效的 entries 请求条目")

    candidates = []
    seen_fingerprints = set()

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        req = entry.get("request") or {}
        resp = entry.get("response") or {}
        url = str(req.get("url") or "").strip()
        if not url:
            continue

        method = str(req.get("method") or "GET").upper()
        if method == "OPTIONS":
            continue

        parts = urlsplit(url)
        pathname = parts.path or "/"

        # 过滤静态资源
        if pathname.lower().endswith(_STATIC_SUFFIXES):
            continue

        # 检查是否为静态 mimeType
        mime_type = ""
        post_data = req.get("postData") or {}
        resp_content = resp.get("content") or {}
        resp_mime = str(resp_content.get("mimeType") or "").lower()
        if any(t in resp_mime for t in ["image/", "font/", "css", "javascript", "video/", "audio/"]):
            continue

        # 解析 Headers (HAR 中的 headers 是 [{"name": ..., "value": ...}])
        def extract_headers(h_list):
            res = {}
            if isinstance(h_list, list):
                for h in h_list:
                    if isinstance(h, dict) and h.get("name"):
                        res[str(h["name"])] = str(h.get("value") or "")
            elif isinstance(h_list, dict):
                res = {str(k): str(v) for k, v in h_list.items()}
            return clean_headers(res)

        req_headers = extract_headers(req.get("headers"))
        resp_headers = extract_headers(resp.get("headers"))

        # 解析 Body
        req_body = None
        if post_data.get("text"):
            req_body = _parse_request_body(post_data["text"])
        elif post_data.get("params"):
            # form-data / urlencoded
            req_body = {p.get("name"): p.get("value") for p in post_data["params"] if isinstance(p, dict)}

        resp_body = None
        raw_resp_text = resp_content.get("text")
        if raw_resp_text is not None:
            # 兼容 base64 编码的响应体（如 Chrome HAR 对特定内容启用了 encoding: "base64"）
            if str(resp_content.get("encoding") or "").lower() == "base64" and isinstance(raw_resp_text, str):
                try:
                    import base64
                    raw_resp_text = base64.b64decode(raw_resp_text).decode("utf-8", errors="replace")
                except Exception:
                    pass

            if isinstance(raw_resp_text, str):
                trimmed = raw_resp_text.strip()
                if trimmed.startswith(("{", "[")):
                    try:
                        resp_body = redact_body(json.loads(trimmed))
                    except Exception:
                        resp_body = trimmed[:10000]
                else:
                    resp_body = trimmed[:10000]
            elif isinstance(raw_resp_text, (dict, list)):
                resp_body = redact_body(raw_resp_text)
            else:
                resp_body = str(raw_resp_text)[:10000]

        query = _clean_query(parts.query)
        fp = fingerprint(method, pathname)
        pt = path_template(pathname)
        base_url = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
        status = int(resp.get("status") or 0)

        # 归一化去重指纹：HAR 文件内若有多个相同指纹的请求，只保留最新/具有代表性的一条，
        # 并累加频次，避免列表充斥成百上千条重复接口导致解析和传输卡顿
        if fp in seen_fingerprints:
            continue
        seen_fingerprints.add(fp)

        # 保护响应体体积（避免超大 base64/HTML 撑爆网络传输，截断上限 10KB 样本）
        if isinstance(resp_body, str) and len(resp_body) > 10000:
            resp_body = resp_body[:10000]

        candidates.append({
            "fingerprint": fp,
            "method": method,
            "path": pathname + (f"?{query}" if query else ""),
            "path_template": pt,
            "base_url": "",
            "title": f"{method} {pt}",
            "headers": req_headers,
            "body": req_body,
            "response_status": status,
            "response_headers": resp_headers,
            "response_body": resp_body,
            "response_content_type": resp_mime,
            "is_duplicate_in_har": False,
        })

    return candidates
