# -*- coding: utf-8 -*-
"""接口资产路由：列表/详情/编辑/删除/按需 AI 整理/转为 API 用例。

资产由 UI 自动化生成期首跑抓包自动写入（source=ui-capture），
本路由只负责查询与人工动作；模型仅在 enhance 时按需调用一次。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from insight_aitest.modules.api.backend.deps import get_asset_db
from insight_aitest.modules.api.backend.persistence.asset_database import AssetDatabase
from insight_aitest.modules.api.backend.services.asset_enhance import (
    enhance,
    infer_schema,
    jsonpath_samples,
)

router = APIRouter(prefix="/assets", tags=["api-assets"])


class AssetOut(BaseModel):
    id: int
    project_id: int | None = None
    title: str = ""
    method: str = ""
    path: str = ""
    path_template: str = ""
    base_url: str = ""
    headers: dict = {}
    body: Any = None
    response_status: int = 0
    response_headers: dict = {}
    response_body: Any = None
    response_content_type: str = ""
    body_truncated: bool = False
    fingerprint: str = ""
    times_seen: int = 1
    source: str = "ui-capture"
    source_case_id: int | None = None
    tags: list[str] = []
    is_noise: bool = False
    ai_meta: Any = None
    jsonpath_samples: list[dict] = []
    first_seen_at: str = ""
    last_seen_at: str = ""

    @classmethod
    def from_asset(cls, asset) -> "AssetOut":
        response_body = getattr(asset, "response_body", None)
        samples = (
            jsonpath_samples(response_body)
            if isinstance(response_body, (dict, list))
            else []
        )
        first = getattr(asset, "first_seen_at", None)
        last = getattr(asset, "last_seen_at", None)
        return cls(
            id=asset.id,
            project_id=asset.project_id,
            title=asset.title or "",
            method=asset.method or "",
            path=asset.path or "",
            path_template=asset.path_template or "",
            base_url=asset.base_url or "",
            headers=asset.headers or {},
            body=asset.body,
            response_status=asset.response_status or 0,
            response_headers=asset.response_headers or {},
            response_body=response_body,
            response_content_type=asset.response_content_type or "",
            body_truncated=bool(asset.body_truncated),
            fingerprint=asset.fingerprint or "",
            times_seen=asset.times_seen or 0,
            source=asset.source or "ui-capture",
            source_case_id=asset.source_case_id,
            tags=asset.tags or [],
            is_noise=bool(asset.is_noise),
            ai_meta=asset.ai_meta,
            jsonpath_samples=samples,
            first_seen_at=first.isoformat() if isinstance(first, datetime) else "",
            last_seen_at=last.isoformat() if isinstance(last, datetime) else "",
        )


class AssetListOut(BaseModel):
    items: list[AssetOut]
    total: int
    page: int
    page_size: int


class AssetUpdateIn(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    is_noise: bool | None = None
    path_template: str | None = None
    ai_meta: dict | None = None


@router.get("", response_model=AssetListOut)
def list_assets(
    project_id: int | None = Query(None),
    method: str = Query(""),
    keyword: str = Query(""),
    hide_noise: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AssetDatabase = Depends(get_asset_db),
) -> AssetListOut:
    items, total = db.list_assets(
        project_id=project_id,
        method=method,
        keyword=keyword,
        hide_noise=hide_noise,
        page=page,
        page_size=page_size,
    )
    return AssetListOut(
        items=[AssetOut.from_asset(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/enhance-progress")
def get_enhance_progress_route(project_id: int | None = Query(None)) -> dict:
    """后台自动 AI 整理进度（进程内状态，页面打开时轮询回显）。"""
    from insight_aitest.modules.ui.backend.automation.capture import (
        get_enhance_progress,
    )

    return get_enhance_progress(project_id)


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: int, db: AssetDatabase = Depends(get_asset_db)) -> AssetOut:
    asset = db.get(asset_id)
    if asset is None:
        raise HTTPException(404, "接口资产不存在")
    return AssetOut.from_asset(asset)


@router.patch("/{asset_id}", response_model=AssetOut)
def update_asset(
    asset_id: int, body: AssetUpdateIn, db: AssetDatabase = Depends(get_asset_db)
) -> AssetOut:
    asset = db.update(
        asset_id,
        title=body.title,
        tags=body.tags,
        is_noise=body.is_noise,
        path_template=body.path_template,
        ai_meta=body.ai_meta,
    )
    if asset is None:
        raise HTTPException(404, "接口资产不存在")
    return AssetOut.from_asset(asset)


_MAX_DEBUG_BODY = 512 * 1024


class AssetDebugIn(BaseModel):
    method: str = ""
    url: str = ""
    headers: dict[str, str] = {}
    body: Any = None
    timeout: float = 30.0


@router.post("/{asset_id}/debug")
def debug_asset(
    asset_id: int, body: AssetDebugIn, db: AssetDatabase = Depends(get_asset_db)
) -> dict:
    """在线调试：按前端编辑后的 URL/headers/body 真实发送一次请求。

    仅回显本次响应，不写库、不产生调试历史，退出后资产内容不变。
    """
    import json
    import time
    import warnings

    import httpx

    asset = db.get(asset_id)
    if asset is None:
        raise HTTPException(404, "接口资产不存在")

    method = (body.method or asset.method or "GET").upper()
    url = (body.url or "").strip() or (
        f"{(asset.base_url or '').rstrip('/')}{asset.path or ''}"
    )
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "URL 必须以 http:// 或 https:// 开头")

    headers = {
        str(k).strip(): str(v)
        for k, v in (body.headers or {}).items()
        if str(k).strip()
    }
    payload = body.body
    content: bytes | None = None
    if payload is not None and payload != "":
        if isinstance(payload, (dict, list)):
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if not any(k.lower() == "content-type" for k in headers):
                headers["Content-Type"] = "application/json"
        else:
            content = str(payload).encode("utf-8")

    timeout = max(1.0, min(float(body.timeout or 30), 60.0))
    started = time.perf_counter()
    try:
        with warnings.catch_warnings():
            # 调试允许访问自签名 HTTPS 环境，忽略证书校验告警
            warnings.simplefilter("ignore")
            with httpx.Client(
                timeout=timeout, follow_redirects=True, verify=False
            ) as client:
                resp = client.request(method, url, headers=headers, content=content)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"请求失败：{str(exc)[:200]}") from exc
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    raw = resp.content or b""
    truncated = len(raw) > _MAX_DEBUG_BODY
    if truncated:
        raw = raw[:_MAX_DEBUG_BODY]
    try:
        text = raw.decode(resp.encoding or "utf-8", errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")

    return {
        "status": resp.status_code,
        "headers": dict(resp.headers),
        "body": text,
        "content_type": resp.headers.get("content-type", ""),
        "elapsed_ms": elapsed_ms,
        "size": len(resp.content or b""),
        "truncated": truncated,
        "url": str(resp.url),
    }


class AssetBatchDeleteIn(BaseModel):
    ids: list[int]


@router.post("/batch-delete")
def batch_delete_assets(
    body: AssetBatchDeleteIn, db: AssetDatabase = Depends(get_asset_db)
) -> dict:
    return {"deleted": db.delete_many(body.ids)}


@router.delete("/{asset_id}")
def delete_asset(asset_id: int, db: AssetDatabase = Depends(get_asset_db)) -> dict:
    if not db.delete(asset_id):
        raise HTTPException(404, "接口资产不存在")
    return {"ok": True}


@router.post("/{asset_id}/enhance")
def enhance_asset(asset_id: int, db: AssetDatabase = Depends(get_asset_db)) -> dict:
    """按需调用一次大模型产出整理建议（不写库，前端确认后走 PATCH 应用）。"""
    asset = db.get(asset_id)
    if asset is None:
        raise HTTPException(404, "接口资产不存在")
    try:
        from insight_aitest.modules.ai.backend.deps import get_llm
    except Exception as exc:  # pragma: no cover - 模块被禁用时的兜底
        raise HTTPException(400, "AI 模块不可用，无法整理资产") from exc
    try:
        return enhance(asset, get_llm())
    except ValueError as exc:
        raise HTTPException(502, f"模型整理失败：{exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"模型整理失败：{str(exc)[:200]}") from exc


@router.post("/{asset_id}/auth-token")
def fetch_asset_auth_token(
    asset_id: int, db: AssetDatabase = Depends(get_asset_db)
) -> dict:
    """按项目级前置脚本获取一次登录 token（每次调用都重新登录，可用于刷新）。"""
    asset = db.get(asset_id)
    if asset is None:
        raise HTTPException(404, "接口资产不存在")
    if not asset.project_id:
        raise HTTPException(400, "该接口资产未关联项目，无法获取项目级 token")

    try:
        from insight_aitest.modules.ui.backend.automation.deps import (
            get_automation_db,
        )
        from insight_aitest.modules.ui.backend.automation.env_service import (
            prepare_auth,
        )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(400, "UI 自动化模块不可用，无法获取 token") from exc

    env_db = get_automation_db()
    env = env_db.default_env(asset.project_id)
    if env is None:
        envs = env_db.list_envs(asset.project_id)
        env = envs[0] if envs else None
    if env is None:
        raise HTTPException(400, "该项目尚未配置 UI 自动化环境，无法获取 token")

    auth = prepare_auth(env)
    if not auth.ok:
        raise HTTPException(502, f"获取 token 失败：{auth.message}")
    if not auth.token:
        raise HTTPException(400, "环境未配置登录信息或前置脚本未返回 token")

    inject = (getattr(env, "token_inject", "") or "").lower()
    name = (getattr(env, "token_name", "") or "token").strip()
    # 接口调试统一组装为 Authorization: Bearer <token>
    # 环境若显式配置了前缀则沿用（自动补一个空格），否则默认 Bearer
    raw_prefix = (getattr(env, "token_prefix", "") or "").strip()
    prefix = f"{raw_prefix} " if raw_prefix else "Bearer "
    header_name = "Authorization"
    header_value = f"{prefix}{auth.token}"

    return {
        "token": auth.token,
        "inject": "header",
        "name": name,
        "prefix": prefix,
        "header_name": header_name,
        "header_value": header_value,
        "env_id": getattr(env, "id", None),
        "env_name": getattr(env, "name", ""),
        "env_inject": inject,
    }


@router.post("/{asset_id}/to-case")
def asset_to_case(asset_id: int, db: AssetDatabase = Depends(get_asset_db)) -> dict:
    """把资产转成 API 用例（默认用实际路径，保证可直接执行）。"""
    asset = db.get(asset_id)
    if asset is None:
        raise HTTPException(404, "接口资产不存在")

    try:
        from insight_aitest.modules.testcase.backend.deps import get_tc_db
        from insight_aitest.modules.testcase.backend.persistence.models import (
            CasePriority,
            CaseStatus,
            CaseType,
            TestCase,
            TestType,
        )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(400, "用例模块不可用，无法转为用例") from exc

    assertions: list[dict] = [
        {"type": "status_code", "expected": int(asset.response_status or 200)}
    ]
    response_body = getattr(asset, "response_body", None)
    if isinstance(response_body, (dict, list)) and response_body:
        schema = infer_schema(response_body)
        try:
            import json

            if len(json.dumps(schema, ensure_ascii=False)) <= 4096:
                assertions.append({"type": "json_schema", "expected": schema})
        except (TypeError, ValueError):
            pass

    step = {
        "name": asset.title or f"{asset.method} {asset.path_template}",
        "method": asset.method,
        "path": asset.path,
        "headers": asset.headers or {},
        "body": asset.body,
        "assertions": assertions,
        "extract": {},
    }
    case = TestCase(
        title=(asset.title or f"{asset.method} {asset.path_template}")[:120],
        type=CaseType.API,
        description=(
            f"由 UI 用例抓包资产自动生成（来源用例 id={asset.source_case_id}）；"
            "路径中的具体 ID 可按需参数化"
        ),
        priority=CasePriority.P2,
        status=CaseStatus.DRAFT,
        test_design=TestType.POSITIVE,
        content={"base_url": asset.base_url, "steps": [step]},
        tags=["ui-capture", f"asset:{asset.id}"],
        source="ui-capture",
        project_id=asset.project_id,
    )
    case_id = get_tc_db().create_case(case)
    return {"ok": True, "case_id": case_id}
