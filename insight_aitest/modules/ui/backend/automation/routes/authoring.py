# -*- coding: utf-8 -*-
"""本地 Agent 编写：文案生成 / MCP Token 管理 / 进度事件（SSE）。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from insight_aitest.modules.ui.backend.automation import authoring_service as svc
from insight_aitest.modules.ui.backend.automation import mcp_tokens, prompt_builder
from insight_aitest.modules.ui.backend.automation.current_env import project_name
from insight_aitest.modules.ui.backend.automation.deps import get_automation_db

router = APIRouter(prefix="/automation/authoring", tags=["ui-automation-authoring"])


def _client_base(request: Request) -> str:
    """推导浏览器实际访问的地址。

    前端开发服务器会把 /api/* 代理到 127.0.0.1:8001 并改写 Host，
    直接取 request.base_url 会得到 127.0.0.1，其他网口访问时文案里的 MCP 地址不可用。
    这里优先用浏览器带来的 Origin/Referer 主机名，端口沿用后端实际监听端口。
    """
    base = str(request.base_url).rstrip("/")
    forwarded = request.headers.get("x-forwarded-host") or ""
    if forwarded:
        scheme = (request.headers.get("x-forwarded-proto") or "http").split(",")[0].strip()
        return f"{scheme}://{forwarded.split(',')[0].strip()}"
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if origin:
        parsed = urlparse(origin)
        host = parsed.hostname or ""
        if host and host not in ("localhost", "127.0.0.1"):
            port = urlparse(base).port
            return f"{parsed.scheme}://{host}:{port}" if port else f"{parsed.scheme}://{host}"
    return base


AUTHORING_MODES = ("auto", "create", "fix", "regenerate")


def build_prompt(case_ids: list[int], token: str, mcp_url: str, mode: str = "create") -> str:
    """兼容旧调用点：按 mode 委托 prompt_builder（文案只在 prompt_builder 维护）。"""
    if mode == "fix":
        return prompt_builder.render_fix_prompt(case_ids, token, mcp_url)
    if mode == "regenerate":
        return prompt_builder.render_regenerate_prompt(case_ids, token, mcp_url)
    return prompt_builder.render_create_prompt(case_ids, token, mcp_url)


def build_auto_prompt(cases: list, token: str, mcp_url: str) -> str:
    """兼容旧调用点：内部委托 prompt_builder。"""
    return prompt_builder.render_auto_prompt([int(c.id) for c in cases], token, mcp_url)


@router.post("/prompt")
async def create_prompt(request: Request, body: dict):
    """生成可粘贴给本地 Agent 的文案（mode=auto 时先分诊，全部无需处理则不建 Token）。"""
    project_id = int(body.get("project_id") or 0)
    case_ids = [int(x) for x in (body.get("case_ids") or []) if str(x).isdigit()]
    mode = str(body.get("mode") or "auto").strip().lower()
    if not project_id:
        raise HTTPException(400, "缺少 project_id")
    if not case_ids:
        raise HTTPException(400, "请至少勾选一个用例")
    if mode not in AUTHORING_MODES:
        raise HTTPException(400, "不支持的 mode，仅支持 auto / create / fix / regenerate")

    # 去重（保序），避免重复 triage / 重复事件；校验必须在建 Token 之前，避免孤儿 Token
    seen: set[int] = set()
    case_ids = [cid for cid in case_ids if not (cid in seen or seen.add(cid))]

    db = get_automation_db()
    valid_ids: list[int] = []
    cases: list = []
    for cid in case_ids:
        case = svc.resolve_case(db, cid, project_id)
        if case is not None:
            valid_ids.append(cid)
            cases.append(case)
    if not valid_ids:
        raise HTTPException(404, "勾选的用例均不属于当前项目")

    base = _client_base(request)
    mcp_url = f"{base}/mcp"
    triage_mode = "regenerate" if mode == "regenerate" else "auto"
    triage = svc.triage_cases(db, cases, mode=triage_mode)
    action_required = sum(
        triage["summary"][key] for key in ("create", "fix", "regenerate")
    )

    result = {
        "ok": True,
        "project_id": project_id,
        "project_name": project_name(project_id),
        "case_ids": valid_ids,
        "skipped_case_ids": [c for c in case_ids if c not in valid_ids],
        "mode": mode,
        "action_required": action_required,
        "summary": triage["summary"],
        "cases": triage["items"],
        "prompt": None,
        "token": None,
        "mcp_url": mcp_url,
        "token_id": None,
        "expires_at": None,
    }
    if mode in ("auto", "regenerate") and action_required == 0:
        return result

    token, row = mcp_tokens.create_token(project_id, name=f"本地 Agent {datetime.now():%m-%d %H:%M}")
    if mode in ("auto", "regenerate"):
        # 新建、修复、重新生成共用同一套文案
        prompt = build_auto_prompt(cases, token, mcp_url)
    else:
        prompt = build_prompt(valid_ids, token, mcp_url, mode=mode)
    for case in cases:
        svc.record_event(db, case, "prompt_ready", "已生成本地编写文案", {"token_id": row.id, "mode": mode})
    result.update(
        {
            "prompt": prompt,
            "token": token,
            "token_id": row.id,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        }
    )
    return result


@router.get("/triage")
def triage(
    project_id: int = Query(...),
    case_ids: str = Query(""),
    mode: str = Query("auto"),
):
    """只读预检：勾选用例本轮分别该 create / fix / regenerate / skip。"""
    mode = str(mode or "auto").strip().lower()
    if mode not in svc.TRIAGE_MODES:
        raise HTTPException(400, "不支持的 mode，仅支持 auto / regenerate")
    ids = [int(x) for x in case_ids.split(",") if x.strip().isdigit()]
    db = get_automation_db()
    cases = [c for c in (svc.resolve_case(db, cid, project_id) for cid in ids) if c is not None]
    result = svc.triage_cases(db, cases, mode=mode)
    return {"ok": True, **result}


@router.get("/tokens")
def list_tokens(project_id: int = Query(...)):
    return {"ok": True, "items": mcp_tokens.list_tokens(project_id)}


@router.delete("/tokens/{token_id}")
def revoke_token(token_id: int, project_id: int = Query(...)):
    ok = mcp_tokens.revoke_token(token_id, project_id)
    if not ok:
        raise HTTPException(404, "Token 不存在")
    return {"ok": True}


@router.get("/storage-state/{state_token}")
def download_storage_state(state_token: str):
    path = svc.consume_storage_state(state_token)
    if path is None:
        raise HTTPException(404, "storageState 链接无效、已过期或已使用")
    return FileResponse(str(path), media_type="application/json", filename="storageState.json")


@router.get("/events")
def list_events(case_id: int = Query(...), after_id: int = 0, limit: int = 200):
    rows = get_automation_db().list_authoring_events(case_id, after_id=after_id, limit=limit)
    return {"ok": True, "items": [_event_dict(r) for r in rows]}


@router.get("/status")
def authoring_status(case_ids: str = Query("")):
    """批量查询用例的编写状态（前端轮询兜底）。"""
    ids = [int(x) for x in case_ids.split(",") if x.strip().isdigit()]
    db = get_automation_db()
    out = []
    for cid in ids:
        case = db.get_case(cid)
        if case is None:
            out.append({"case_id": cid, "exists": False})
            continue
        state = db.get_authoring_state(cid)
        events = db.list_authoring_events(cid, after_id=0, limit=5)
        out.append(
            {
                "case_id": cid,
                "exists": True,
                "title": case.title,
                "status": case.status,
                "script_version": int(case.script_version or 0),
                "source": getattr(case, "source", "ai"),
                "authoring_at": case.authoring_at.isoformat() if case.authoring_at else None,
                "stage": state.stage if state else "",
                "mode": (state.authoring_mode if state else "") or "auto",
                "generation_id": state.generation_id if state else None,
                "last_error": state.last_error if state else "",
                "latest_event_id": db.latest_authoring_event_id(cid),
                "recent_events": [_event_dict(r) for r in events],
            }
        )
    return {"ok": True, "items": out}


@router.get("/active")
def authoring_active(
    project_id: int = Query(...), limit: int = Query(50, ge=1, le=200)
):
    """当前项目进行中的编写任务（已入库、未发起的都不返回）。"""
    db = get_automation_db()
    now = datetime.now()
    out = []
    for state, case in db.list_active_authoring(project_id, limit=200):
        stamp = state.updated_at
        if state.stage == svc.AuthoringStage.VALIDATED:
            stamp = state.validated_at or stamp
            if now - stamp > svc.VALIDATED_TTL:
                continue
        elif state.stage == svc.AuthoringStage.DRY_RUN_OK:
            stamp = state.dry_run_at or stamp
            if now - stamp > svc.DRY_RUN_TTL:
                continue
        elif state.stage == svc.AuthoringStage.GENERATING:
            if now - stamp > timedelta(hours=6):
                continue
        event = db.latest_authoring_event(case.id)
        out.append(
            {
                "case_id": case.id,
                "title": case.title,
                "status": case.status,
                "stage": state.stage,
                "mode": (state.authoring_mode or "") or "auto",
                "generation_id": state.generation_id,
                "script_version": int(case.script_version or 0),
                "source_hash": (state.source_hash or "")[:12],
                "last_error": state.last_error or "",
                "updated_at": stamp.isoformat() if stamp else None,
                "busy": bool(state.lease_until and state.lease_until > now),
                "latest_event": (
                    {"message": event.message, "created_at": event.created_at.isoformat()}
                    if event is not None
                    else None
                ),
            }
        )
        if len(out) >= limit:
            break

    # 已生成文案、但 Agent 还没开始校验的用例（等待阶段）
    seen = {item["case_id"] for item in out}
    waiting_since = now - timedelta(hours=6)
    for case, event in db.list_prompt_ready_cases(project_id, since=waiting_since, limit=limit):
        if case.id in seen:
            continue
        out.append(
            {
                "case_id": case.id,
                "title": case.title,
                "status": case.status,
                "stage": "waiting",
                "script_version": int(case.script_version or 0),
                "source_hash": "",
                "last_error": "",
                "updated_at": event.created_at.isoformat(),
                "busy": False,
                "latest_event": {"message": event.message, "created_at": event.created_at.isoformat()},
            }
        )
        if len(out) >= limit:
            break
    return {"ok": True, "count": len(out), "items": out}


@router.get("/stream")
async def stream_events(request: Request, case_id: int = Query(...), after_id: int = 0):
    """SSE 进度流：每 1 秒增量推送，15 秒心跳。"""

    async def gen():
        last = after_id
        idle = 0
        yield "retry: 3000\n\n"
        while True:
            if await request.is_disconnected():
                return
            rows = await asyncio.to_thread(
                get_automation_db().list_authoring_events, case_id, last, 100
            )
            for row in rows:
                last = int(row.id or last)
                data = json.dumps(_event_dict(row), ensure_ascii=False)
                yield f"id: {last}\nevent: authoring\ndata: {data}\n\n"
            idle += 1
            if idle >= 15:
                idle = 0
                yield ": ping\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _event_dict(row) -> dict:
    return {
        "id": row.id,
        "case_id": row.case_id,
        "kind": row.kind,
        "message": row.message,
        "payload": row.payload or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
