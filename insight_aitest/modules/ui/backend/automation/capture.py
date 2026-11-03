# -*- coding: utf-8 -*-
"""UI 生成期首跑抓包 → 接口资产（规则采集，AI 整理在后台按需异步执行）。

职责：
- 读取脚手架产出的 ``network.jsonl``；
- 过滤静态资源/跨域/OPTIONS/登录鉴权流量，剔除敏感头与敏感字段；
- 按 ``METHOD + 归一化路径`` 生成指纹，一个接口一条资产（重复命中累加次数）；
- 写入 api 模块的独立接口资产库（api.db / api_assets）。

任何异常都只记录日志、返回统计，不影响 UI 脚本生成结果。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# 敏感/噪声请求头：一律不落库
_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "proxy-authorization",
    "x-csrf-token",
    "x-xsrf-token",
}
_DROP_HEADERS = {
    "host",
    "content-length",
    "accept-encoding",
    "connection",
    "user-agent",
    "origin",
    "referer",
    "accept-language",
}
_SENSITIVE_WORDS = ("token", "secret", "password", "session", "api-key", "apikey")

_STATIC_RESOURCE_TYPES = {
    "document",
    "stylesheet",
    "script",
    "image",
    "font",
    "media",
    "manifest",
    "texttrack",
    "websocket",
    "eventsource",
}
_STATIC_SUFFIXES = (
    ".js",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
)
_AUTH_PATH_RE = re.compile(r"/(login|logout|oauth|captcha|token)(/|$)", re.I)
_SENSITIVE_BODY_KEYS = {
    "password",
    "passwd",
    "pwd",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "authorization",
    "cookie",
    "session",
}
_MAX_ASSETS = 200


def _is_sensitive_header(key: str) -> bool:
    lowered = str(key).lower()
    if lowered in _SENSITIVE_HEADERS or lowered in _DROP_HEADERS:
        return True
    if lowered.startswith("sec-"):
        return True
    return any(word in lowered for word in _SENSITIVE_WORDS)


def clean_headers(headers: dict | None) -> dict:
    """剔除凭证、Cookie 与浏览器噪声头，只保留可复用的业务头。"""
    return {
        str(key): value
        for key, value in (headers or {}).items()
        if not _is_sensitive_header(key)
    }


def redact_body(value):
    """递归把敏感 JSON 字段替换为 <redacted>。"""
    if isinstance(value, dict):
        return {
            key: ("<redacted>" if str(key).lower() in _SENSITIVE_BODY_KEYS else redact_body(val))
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [redact_body(item) for item in value]
    return value


def _parse_request_body(raw) -> object | None:
    if not raw:
        return None
    if isinstance(raw, (dict, list)):
        return redact_body(raw)
    text = str(raw)
    try:
        return redact_body(json.loads(text))
    except ValueError:
        return text


def _clean_query(query: str) -> str:
    """query 中敏感参数值置为 <redacted>，避免 token 通过 URL 落库。"""
    pairs = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        if any(word in key.lower() for word in _SENSITIVE_WORDS):
            value = "<redacted>"
        pairs.append(f"{key}={value}")
    return "&".join(pairs)


def normalize_segment(segment: str) -> str:
    """路径段归一化：数字/UUID/长 hex 替换为占位符，供指纹与模板使用。"""
    if not segment:
        return segment
    if segment.isdigit():
        return "{id}"
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", segment):
        return "{uuid}"
    if re.fullmatch(r"[0-9a-fA-F]{16,}", segment):
        return "{hash}"
    return segment


def path_template(pathname: str) -> str:
    if not pathname:
        return "/"
    return "/".join(normalize_segment(seg) for seg in pathname.split("/"))


def fingerprint(method: str, pathname: str) -> str:
    return f"{(method or 'GET').upper()} {path_template(pathname)}"


def load_records(network_path: Path | str) -> list[dict]:
    path = Path(network_path)
    if not path.exists():
        return []
    records: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict) and item.get("url"):
                    records.append(item)
    except OSError:
        return []
    return records


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def _skip(url: str, record: dict, base_origin: str, login_api_path: str) -> bool:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if base_origin and origin.lower() != base_origin.lower():
        return True
    if (record.get("resource_type") or "") in _STATIC_RESOURCE_TYPES:
        return True
    if (record.get("method") or "").upper() == "OPTIONS":
        return True
    status = int(record.get("status") or 0)
    if status < 200 or status >= 500 or 300 <= status < 400:
        return True
    pathname = parts.path or "/"
    if pathname.lower().endswith(_STATIC_SUFFIXES):
        return True
    if login_api_path and pathname.rstrip("/").lower() == login_api_path.rstrip("/").lower():
        return True
    return bool(_AUTH_PATH_RE.search(pathname))


def build_assets(
    records: list[dict],
    *,
    base_origin: str = "",
    login_api_path: str = "",
) -> list[dict]:
    """把抓包记录转成资产条目（同指纹只保留首条样本并累加次数）。"""
    merged: dict[str, dict] = {}
    for record in records:
        url = str(record.get("url") or "")
        if not url or _skip(url, record, base_origin, login_api_path):
            continue
        parts = urlsplit(url)
        method = (record.get("method") or "GET").upper()
        pathname = parts.path or "/"
        query = _clean_query(parts.query)
        fp = fingerprint(method, pathname)
        if fp in merged:
            merged[fp]["times_seen"] += 1
            continue
        content_type = ""
        for key, value in (record.get("response_headers") or {}).items():
            if str(key).lower() == "content-type":
                content_type = str(value)
                break
        merged[fp] = {
            "title": fp,
            "method": method,
            "path": pathname + (f"?{query}" if query else ""),
            "path_template": path_template(pathname),
            "base_url": f"{parts.scheme}://{parts.netloc}",
            "headers": clean_headers(record.get("request_headers")),
            "body": _parse_request_body(record.get("request_body")),
            "response_status": int(record.get("status") or 0),
            "response_headers": clean_headers(record.get("response_headers")),
            "response_body": redact_body(record.get("response_body")),
            "response_content_type": content_type,
            "body_truncated": bool(record.get("body_truncated")),
            "fingerprint": fp,
            "times_seen": 1,
        }
        if len(merged) >= _MAX_ASSETS:
            break
    return list(merged.values())


def import_captured_api_assets(
    *,
    project_id: int | None,
    ui_case_id: int | None,
    ui_case_title: str = "",
    network_path: Path | str,
    base_origin: str = "",
    login_api_path: str = "",
    auto_enhance: bool = False,
    enhance_limit: int = 30,
) -> dict:
    """解析抓包产物并写入独立接口资产库，返回统计（失败只记日志，不抛异常）。

    ``auto_enhance=True`` 时（仅生成期首跑）对本次落库的资产追加一次 AI 整理并直接应用。
    """
    stats = {
        "captured": 0,
        "imported": 0,
        "updated": 0,
        "enhanced": 0,
        "enhance_failed": 0,
        "enhance_skipped": 0,
        "enhance_queued": 0,
    }
    records = load_records(network_path)
    stats["captured"] = len(records)
    if not records:
        return stats

    origin = base_origin or _origin(str(records[0].get("url") or ""))
    assets = build_assets(records, base_origin=origin, login_api_path=login_api_path)
    if not assets:
        return stats

    try:
        from insight_aitest.modules.api.backend.deps import get_asset_db

        db = get_asset_db()
    except Exception as exc:  # api 模块被禁用等场景：不影响生成结果
        logger.warning("接口资产库不可用，跳过抓包入库：%s", exc)
        return stats

    items = [
        {
            **asset,
            "project_id": project_id,
            "source": "ui-capture",
            "source_case_id": ui_case_id,
            "tags": [f"ui-case:{ui_case_id}"] if ui_case_id else [],
        }
        for asset in assets
    ]
    fingerprints = [a["fingerprint"] for a in assets]

    try:
        result = db.upsert_many(items)
        stats.update(result)
    except Exception as exc:
        logger.warning("抓包入库失败：%s", exc)

    if auto_enhance and fingerprints:
        # 只整理尚无整理结果的资产（含本次新增，以及此前整理失败/中断留下的），
        # 已整理过的接口不重复调用模型；整理放到后台线程，避免生成流程卡在「本地验证」
        try:
            pending = [
                a for a in db.list_by_fingerprints(project_id, fingerprints) if not a.ai_meta
            ]
        except Exception as exc:
            logger.warning("查询待整理资产失败：%s", exc)
            pending = []
        queued = len(pending[:enhance_limit]) if enhance_limit else len(pending)
        stats["enhance_queued"] = queued
        if queued:
            threading.Thread(
                target=_auto_enhance_assets,
                kwargs={
                    "db": db,
                    "project_id": project_id,
                    "fingerprints": fingerprints,
                    "limit": enhance_limit,
                },
                name="api-asset-auto-enhance",
                daemon=True,
            ).start()

    logger.info(
        "UI 抓包资产入库：采集 %s 条，新增 %s，更新 %s，待 AI 整理 %s 条（后台执行）"
        "（用例 %s《%s》）",
        stats["captured"],
        stats["imported"],
        stats["updated"],
        stats["enhance_queued"],
        ui_case_id,
        ui_case_title,
    )
    return stats


def _auto_enhance_assets(
    db,
    *,
    project_id: int | None,
    fingerprints: list[str],
    limit: int,
) -> dict:
    """对尚未整理过的抓包资产自动整理并应用（失败不影响生成）。"""
    stats = {"enhanced": 0, "enhance_failed": 0, "enhance_skipped": 0}
    try:
        from insight_aitest.modules.ai.backend.deps import get_llm
        from insight_aitest.modules.api.backend.services.asset_enhance import enhance

        llm = get_llm()
        assets = [a for a in db.list_by_fingerprints(project_id, fingerprints) if not a.ai_meta]
    except Exception as exc:
        logger.warning("自动 AI 整理跳过（模型或资产库不可用）：%s", exc)
        stats["enhance_skipped"] = len(fingerprints)
        return stats

    targets = assets[:limit] if limit else assets
    stats["enhance_skipped"] = len(assets) - len(targets)
    _progress_start(project_id, [a.id for a in targets])
    try:
        for asset in targets:
            try:
                result = enhance(asset, llm)
                fields = {
                    "ai_meta": result,
                    "title": result.get("title") or asset.title,
                    "path_template": result.get("path_template") or asset.path_template,
                }
                if isinstance(result.get("is_noise"), bool):
                    fields["is_noise"] = result["is_noise"]
                db.update(asset.id, **fields)
                stats["enhanced"] += 1
                _progress_item(project_id, asset.id, True)
            except Exception as exc:
                logger.warning("接口资产自动整理失败 id=%s：%s", asset.id, exc)
                stats["enhance_failed"] += 1
                _progress_item(project_id, asset.id, False)
    except Exception as exc:  # 线程池内异常必须吞掉并记录，避免静默中断
        logger.warning("接口资产后台整理异常终止：%s", exc)
    finally:
        _progress_finish(project_id)
    logger.info(
        "接口资产后台 AI 整理完成：成功 %s，失败 %s，超限跳过 %s",
        stats["enhanced"],
        stats["enhance_failed"],
        stats["enhance_skipped"],
    )
    return stats


# ===== 后台整理进度（进程内，供资产页轮询回显） =====
_ENHANCE_PROGRESS: dict[object, dict] = {}
_ENHANCE_LOCK = threading.Lock()


def _progress_start(project_id: int | None, asset_ids: list[int]) -> None:
    with _ENHANCE_LOCK:
        _ENHANCE_PROGRESS[project_id] = {
            "status": "running",
            "total": len(asset_ids),
            "done": 0,
            "failed": 0,
            "pending_ids": list(asset_ids),
            "done_ids": [],
            "failed_ids": [],
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
        }


def _progress_item(project_id: int | None, asset_id: int, ok: bool) -> None:
    with _ENHANCE_LOCK:
        p = _ENHANCE_PROGRESS.get(project_id)
        if not p:
            return
        if asset_id in p["pending_ids"]:
            p["pending_ids"].remove(asset_id)
        if ok:
            p["done"] += 1
            p["done_ids"].append(asset_id)
        else:
            p["failed"] += 1
            p["failed_ids"].append(asset_id)


def _progress_finish(project_id: int | None) -> None:
    with _ENHANCE_LOCK:
        p = _ENHANCE_PROGRESS.get(project_id)
        if not p:
            return
        p["status"] = "done"
        p["pending_ids"] = []
        p["finished_at"] = datetime.now().isoformat(timespec="seconds")


def get_enhance_progress(project_id: int | None) -> dict:
    """返回某项目最近一次后台整理进度；从未执行过返回 idle。"""
    with _ENHANCE_LOCK:
        p = _ENHANCE_PROGRESS.get(project_id)
        if p:
            return dict(p)
    return {
        "status": "idle",
        "total": 0,
        "done": 0,
        "failed": 0,
        "pending_ids": [],
        "done_ids": [],
        "failed_ids": [],
        "started_at": None,
        "finished_at": None,
    }
