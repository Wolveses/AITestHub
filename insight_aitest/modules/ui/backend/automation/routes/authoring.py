# -*- coding: utf-8 -*-
"""本地 Agent 编写：文案生成 / MCP Token 管理 / 进度事件（SSE）。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from insight_aitest.modules.ui.backend.automation import authoring_service as svc
from insight_aitest.modules.ui.backend.automation import mcp_tokens
from insight_aitest.modules.ui.backend.automation.current_env import project_name
from insight_aitest.modules.ui.backend.automation.deps import get_automation_db

router = APIRouter(prefix="/automation/authoring", tags=["ui-automation-authoring"])


def build_prompt(case_ids: list[int], token: str, mcp_url: str) -> str:
    listing = "\n".join(f"- case_id={cid}" for cid in case_ids)
    first = case_ids[0] if case_ids else 0
    return f"""你是资深 Playwright UI 自动化测试工程师。请通过 Insight-AITest 平台 MCP 服务，在本机为下列用例编写可运行脚本并提交入库。

【MCP 接入】
- 服务地址：{mcp_url}（Streamable HTTP）
- 请求头：Authorization: Bearer {token}
- 可用工具：ui.contract.get / ui.env.get / ui.case.get / ui.example.get / ui.run.latest / ui.script.validate / ui.script.dry_run / ui.script.submit
- Token 30 天内有效，只在本会话使用；不要写入脚本、不要提交到仓库。

【前置检查】
1. 确认本机已启用 Playwright MCP；若未安装，请自行安装并启用（如 `npx @playwright/mcp@latest`）。
2. 确认已安装浏览器（如 `npx playwright install chromium`）。

【处理顺序（严格串行，禁止并行）】
以下为默认流程；若 ui.contract.get 返回的 workflow 与本节不一致，以 workflow 为准。
对每个 case_id 依次执行：
1. 调用 ui.contract.get(case_id={first})，按返回的 rules 编写（文件路径、import 白名单、禁用项都在里面）。
2. 调用 ui.env.get(case_id={first}) 获取 base_url / entry_url / 认证：
   - auth.storage_state_url 非空时下载 JSON，作为 Playwright MCP 的 storageState 使用；链接 5 分钟内只能下载一次；
   - auth.mode=header 时使用 auth.header_name / auth.header_value；
   - 脚本内不要写死 token，运行期平台会自动注入登录态。
3. 调用 ui.case.get(case_id={first})，记下 case_rev 与 script.version（提交时原样传回）。
4. 调用 ui.example.get(case_id={first}) 获取项目既有经验：hard_rules、known_traps、lessons（踩过的坑）、
   同目录动作片段、known_routes、pages/common 签名与最小骨架。先复用其中路由/定位/等待写法，
   再打开浏览器只补差异；lessons 与本次实测冲突时以实测为准。
5. 用 Playwright MCP 打开 entry_url，按用例步骤真实探索，确认真实定位器（优先 get_by_role + accessible name）。
6. 编写文件集合：
   - case.py 必须包含 def test_xxx(page):，使用同步风格；
   - 站点地址统一用 base_url()（from insight_aitest.modules.ui.backend.automation.env import base_url）；
   - 可新增或复用 pages/*.py、common/*.py；同名资产已存在时优先复用；
   - 断言用 expect(...)，禁止固定 sleep、禁止写死域名/Token、禁止 async/await；
   - 每个 test 函数至少 3 条 print 执行日志，必须以 [步骤] 开头，断言前打印 [断言] 实际值与预期值；
     常用前缀：[步骤]/[操作]/[输入]/[选择]/[勾选]/[断言]/[数据]/[结果]。
7. 调用 ui.script.validate(case_id, files)，必须 ok=true；失败按 violations[].code + fix 修正后重试。
8. 调用 ui.script.dry_run(case_id, files, source_hash)，必须 ok=true；失败根据 log_tail 修正后重新 validate + dry_run。
9. 调用 ui.script.submit(case_id, files, source_hash, expect_case_rev, expect_script_version)，ok=true 即入库成功。

【失败与重试】
- 工具返回 isError=true 时，先读 code / fix / required_next，再决定是否重试；
- 同一错误码连续 3 次仍无法推进：停止并回报，不要继续硬试；
- 遇到 ENV_NOT_CONFIGURED / ENV_NOT_ALLOWED / PERMISSION_DENIED / CASE_NOT_FOUND：立即停止并回报；
- 不要调用不存在的工具，不要改动其他用例。

【最终回报（六段式）】
1. 用例：case_id + 标题
2. 结论：已入库 / 未完成（原因）
3. 脚本版本：vN
4. 校验结果：validate 通过轮次与最终 source_hash
5. 试跑结果：耗时、是否通过、关键日志
6. 未解决项与建议

【用例列表】
{listing}
"""


@router.post("/prompt")
async def create_prompt(request: Request, body: dict):
    """生成可直接粘贴给本地 Agent 的文案（同时创建一次性可见的 Bearer Token）。"""
    project_id = int(body.get("project_id") or 0)
    case_ids = [int(x) for x in (body.get("case_ids") or []) if str(x).isdigit()]
    if not project_id:
        raise HTTPException(400, "缺少 project_id")
    if not case_ids:
        raise HTTPException(400, "请至少勾选一个用例")

    db = get_automation_db()
    valid_ids: list[int] = []
    for cid in case_ids:
        case = svc.resolve_case(db, cid, project_id)
        if case is not None:
            valid_ids.append(cid)
    if not valid_ids:
        raise HTTPException(404, "勾选的用例均不属于当前项目")

    token, row = mcp_tokens.create_token(project_id, name=f"本地 Agent {datetime.now():%m-%d %H:%M}")
    base = str(request.base_url).rstrip("/")
    prompt = build_prompt(valid_ids, token, f"{base}/mcp")
    for cid in valid_ids:
        case = db.get_case(cid)
        if case is not None:
            svc.record_event(db, case, "prompt_ready", "已生成本地编写文案", {"token_id": row.id})
    return {
        "ok": True,
        "project_id": project_id,
        "project_name": project_name(project_id),
        "case_ids": valid_ids,
        "skipped_case_ids": [c for c in case_ids if c not in valid_ids],
        "prompt": prompt,
        "token": token,
        "mcp_url": f"{base}/mcp",
        "token_id": row.id,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


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
