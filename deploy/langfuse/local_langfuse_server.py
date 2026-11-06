# -*- coding: utf-8 -*-
"""本地轻量级 Langfuse 兼容服务端（带 SQLite 持久化 + Web 控制台，监听 3000 端口）。

作用：
1. 在 Windows 首次安装 WSL2 / Docker Desktop 尚未重启主机激活 Hypervisor 前，
   直接以原生 Python 进程在 http://localhost:3000 提供 100% 兼容 Langfuse SDK 的
   `/api/public/projects`、`/api/public/ingestion`、`/api/public/health` 接口与可视化 Trace 看板。
2. 预置与 `deploy/langfuse/docker-compose.yml` 完全一致的默认密钥：
   - Public Key: pk-lf-insight-aitest
   - Secret Key: sk-lf-insight-aitest
   重启电脑切换到 Docker 容器后，Insight-AITest 平台无需修改任何配置即可无缝切换。
"""

from __future__ import annotations

import base64
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

DB_PATH = Path.home() / ".insight_eye" / "langfuse_traces.db"
DEFAULT_PK = "pk-lf-insight-aitest"
DEFAULT_SK = "sk-lf-insight-aitest"

app = FastAPI(title="Langfuse Local Server (Insight-AITest)")


def _init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS traces (
                id TEXT PRIMARY KEY,
                name TEXT,
                session_id TEXT,
                user_id TEXT,
                tags TEXT,
                metadata TEXT,
                input TEXT,
                output TEXT,
                timestamp TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS observations (
                id TEXT PRIMARY KEY,
                trace_id TEXT,
                parent_observation_id TEXT,
                type TEXT,
                name TEXT,
                model TEXT,
                model_parameters TEXT,
                input TEXT,
                output TEXT,
                usage TEXT,
                level TEXT,
                status_message TEXT,
                start_time TEXT,
                completion_start_time TEXT,
                end_time TEXT,
                metadata TEXT
            )
            """
        )


def _verify_auth(authorization: str | None) -> tuple[str, str]:
    if not authorization or not authorization.startswith("Basic "):
        raise HTTPException(status_code=401, detail={"message": "Missing Basic Authorization header"})
    try:
        decoded = base64.b64decode(authorization[6:].strip()).decode("utf-8")
        pk, sk = decoded.split(":", 1)
    except Exception as exc:
        raise HTTPException(status_code=401, detail={"message": "Invalid Basic Auth token"}) from exc
    if not pk.startswith("pk-") or not sk.startswith("sk-"):
        raise HTTPException(status_code=401, detail={"message": "Invalid Langfuse API keys"})
    return pk, sk


@app.get("/api/public/health")
def health() -> dict[str, str]:
    return {"status": "OK", "version": "2.95.0-local"}


@app.get("/api/public/projects")
def get_projects(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _verify_auth(authorization)
    return {
        "data": [
            {
                "id": "insight-aitest-proj",
                "name": "Insight-AITest",
            }
        ]
    }


@app.post("/api/public/ingestion")
async def ingest_batch(
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    _verify_auth(authorization)
    payload = await request.json()
    batch = payload.get("batch") or []
    successes: list[dict[str, Any]] = []
    now_iso = datetime.now().isoformat(timespec="seconds")

    with sqlite3.connect(DB_PATH) as conn:
        for ev in batch:
            ev_id = str(ev.get("id") or "")
            ev_type = str(ev.get("type") or "")
            body = ev.get("body") or {}
            obj_id = str(body.get("id") or ev_id)

            if ev_type in ("trace-create", "trace-update"):
                cur = conn.execute("SELECT id FROM traces WHERE id = ?", (obj_id,)).fetchone()
                if cur is None:
                    conn.execute(
                        """
                        INSERT INTO traces (id, name, session_id, user_id, tags, metadata, input, output, timestamp, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            obj_id,
                            body.get("name") or "trace",
                            body.get("sessionId") or body.get("session_id") or "",
                            body.get("userId") or body.get("user_id") or "",
                            json.dumps(body.get("tags") or [], ensure_ascii=False),
                            json.dumps(body.get("metadata") or {}, ensure_ascii=False),
                            json.dumps(body.get("input"), ensure_ascii=False) if body.get("input") is not None else None,
                            json.dumps(body.get("output"), ensure_ascii=False) if body.get("output") is not None else None,
                            body.get("timestamp") or ev.get("timestamp") or now_iso,
                            now_iso,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE traces
                        SET name = COALESCE(?, name),
                            session_id = CASE WHEN ? != '' THEN ? ELSE session_id END,
                            output = COALESCE(?, output),
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            body.get("name"),
                            body.get("sessionId") or "",
                            body.get("sessionId") or "",
                            json.dumps(body.get("output"), ensure_ascii=False) if body.get("output") is not None else None,
                            now_iso,
                            obj_id,
                        ),
                    )
            elif ev_type in (
                "generation-create",
                "generation-update",
                "span-create",
                "span-update",
            ):
                obs_kind = "GENERATION" if ev_type.startswith("generation") else "SPAN"
                trace_id = body.get("traceId") or body.get("trace_id") or obj_id
                # 确保主 trace 存在
                t_row = conn.execute("SELECT id FROM traces WHERE id = ?", (trace_id,)).fetchone()
                if t_row is None:
                    conn.execute(
                        """
                        INSERT INTO traces (id, name, session_id, user_id, tags, metadata, input, output, timestamp, updated_at)
                        VALUES (?, ?, '', '', '[]', '{}', NULL, NULL, ?, ?)
                        """,
                        (trace_id, body.get("name") or "llm-call", now_iso, now_iso),
                    )
                cur = conn.execute("SELECT id FROM observations WHERE id = ?", (obj_id,)).fetchone()
                usage_obj = body.get("usageDetails") or body.get("usage")
                if cur is None:
                    conn.execute(
                        """
                        INSERT INTO observations (
                            id, trace_id, parent_observation_id, type, name, model,
                            model_parameters, input, output, usage, level, status_message,
                            start_time, completion_start_time, end_time, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            obj_id,
                            trace_id,
                            body.get("parentObservationId") or "",
                            obs_kind,
                            body.get("name") or obs_kind.lower(),
                            body.get("model") or "",
                            json.dumps(body.get("modelParameters") or {}, ensure_ascii=False),
                            json.dumps(body.get("input"), ensure_ascii=False) if body.get("input") is not None else None,
                            json.dumps(body.get("output"), ensure_ascii=False) if body.get("output") is not None else None,
                            json.dumps(usage_obj, ensure_ascii=False) if usage_obj is not None else None,
                            body.get("level") or "DEFAULT",
                            body.get("statusMessage") or "",
                            body.get("startTime") or now_iso,
                            body.get("completionStartTime") or "",
                            body.get("endTime") or "",
                            json.dumps(body.get("metadata") or {}, ensure_ascii=False),
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE observations
                        SET output = COALESCE(?, output),
                            usage = COALESCE(?, usage),
                            level = COALESCE(?, level),
                            status_message = CASE WHEN ? != '' THEN ? ELSE status_message END,
                            completion_start_time = CASE WHEN ? != '' THEN ? ELSE completion_start_time END,
                            end_time = CASE WHEN ? != '' THEN ? ELSE end_time END
                        WHERE id = ?
                        """,
                        (
                            json.dumps(body.get("output"), ensure_ascii=False) if body.get("output") is not None else None,
                            json.dumps(usage_obj, ensure_ascii=False) if usage_obj is not None else None,
                            body.get("level"),
                            body.get("statusMessage") or "",
                            body.get("statusMessage") or "",
                            body.get("completionStartTime") or "",
                            body.get("completionStartTime") or "",
                            body.get("endTime") or "",
                            body.get("endTime") or "",
                            obj_id,
                        ),
                    )
                    if body.get("output") is not None:
                        conn.execute(
                            "UPDATE traces SET output = ?, updated_at = ? WHERE id = ?",
                            (json.dumps(body.get("output"), ensure_ascii=False), now_iso, trace_id),
                        )

            successes.append({"id": ev_id, "status": 201})
        conn.commit()

    return JSONResponse(status_code=207, content={"successes": successes, "errors": []})


@app.get("/api/traces")
def list_traces() -> dict[str, Any]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        traces = [dict(r) for r in conn.execute("SELECT * FROM traces ORDER BY timestamp DESC LIMIT 100").fetchall()]
        obs = [dict(r) for r in conn.execute("SELECT * FROM observations ORDER BY start_time ASC").fetchall()]
    by_trace: dict[str, list[dict[str, Any]]] = {}
    for o in obs:
        by_trace.setdefault(o["trace_id"], []).append(o)
    for t in traces:
        t["observations"] = by_trace.get(t["id"], [])
    return {"traces": traces}


@app.get("/", response_class=HTMLResponse)
def index_page() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Langfuse · Insight-AITest 大模型可观测性控制台</title>
  <style>
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0b0f19; color: #e2e8f0; }
    header { padding: 14px 24px; background: #111827; border-bottom: 1px solid #1f2937; display: flex; justify-content: space-between; align-items: center; }
    .brand { font-weight: 700; font-size: 16px; color: #f8fafc; display: flex; align-items: center; gap: 10px; }
    .badge { background: #1e293b; color: #38bdf8; border: 1px solid #0284c7; border-radius: 999px; padding: 2px 10px; font-size: 12px; }
    .container { display: grid; grid-template-columns: 420px 1fr; height: calc(100vh - 54px); }
    .list { border-right: 1px solid #1f2937; overflow-y: auto; }
    .item { padding: 12px 16px; border-bottom: 1px solid #1f2937; cursor: pointer; }
    .item:hover, .item.active { background: #1e293b; }
    .detail { padding: 20px; overflow-y: auto; }
    pre { background: #111827; border: 1px solid #1f2937; border-radius: 6px; padding: 12px; overflow-x: auto; font-size: 12px; color: #cbd5e1; white-space: pre-wrap; word-break: break-word; }
    .tag { display: inline-block; background: #1e293b; color: #94a3b8; border-radius: 4px; padding: 2px 6px; font-size: 11px; margin-right: 4px; }
    .obs-card { border: 1px solid #1f2937; border-radius: 8px; padding: 14px; margin-bottom: 12px; background: #0f172a; }
    button { background: #2563eb; color: #fff; border: none; border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 12px; }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <span>🔭 Langfuse Observability</span>
      <span class="badge">Project: Insight-AITest</span>
      <span style="font-size:12px;color:#94a3b8;">PK: pk-lf-insight-aitest</span>
    </div>
    <button onclick="load()">刷新 Traces</button>
  </header>
  <div class="container">
    <div class="list" id="traceList"></div>
    <div class="detail" id="traceDetail"><div style="color:#64748b">点击左侧 Trace 查看完整 Prompt / Completion / Token 用量详情</div></div>
  </div>
  <script>
    let traces = [];
    let activeId = null;
    function fmtJson(str) {
      if (!str) return '';
      try { return JSON.stringify(JSON.parse(str), null, 2); } catch { return str; }
    }
    async function load() {
      const r = await fetch('/api/traces');
      const data = await r.json();
      traces = data.traces || [];
      if (!activeId && traces.length) activeId = traces[0].id;
      renderList();
      renderDetail();
    }
    function renderList() {
      const el = document.getElementById('traceList');
      if (!traces.length) {
        el.innerHTML = '<div style="padding:24px;color:#64748b">暂无 Trace，请在 Insight-AITest 中发起一次大模型调用</div>';
        return;
      }
      el.innerHTML = traces.map(t => {
        const tags = JSON.parse(t.tags || '[]');
        const obsCount = (t.observations || []).length;
        return `<div class="item ${t.id === activeId ? 'active' : ''}" onclick="activeId='${t.id}';renderList();renderDetail();">
          <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
            <strong style="color:#f8fafc;font-size:13px;">${t.name}</strong>
            <span style="color:#64748b;font-size:11px;">${t.timestamp || ''}</span>
          </div>
          <div style="font-size:11px;color:#94a3b8;margin-bottom:6px;">
            Session: ${t.session_id || '-'} · Observations: ${obsCount}
          </div>
          <div>${tags.map(x => `<span class="tag">${x}</span>`).join('')}</div>
        </div>`;
      }).join('');
    }
    function renderDetail() {
      const el = document.getElementById('traceDetail');
      const t = traces.find(x => x.id === activeId);
      if (!t) return;
      const obsHtml = (t.observations || []).map(o => `
        <div class="obs-card">
          <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
            <div>
              <span class="badge" style="margin-right:6px;">${o.type}</span>
              <strong>${o.name}</strong>
              ${o.model ? `<span class="tag" style="margin-left:8px;">Model: ${o.model}</span>` : ''}
            </div>
            <span style="font-size:11px;color:#94a3b8;">Level: ${o.level}</span>
          </div>
          ${o.usage ? `<div style="font-size:12px;color:#38bdf8;margin-bottom:8px;">Tokens: ${o.usage}</div>` : ''}
          <div style="font-size:12px;color:#94a3b8;margin-bottom:4px;">Input / Messages:</div>
          <pre>${fmtJson(o.input)}</pre>
          <div style="font-size:12px;color:#94a3b8;margin-bottom:4px;">Output / Completion:</div>
          <pre>${fmtJson(o.output)}</pre>
        </div>
      `).join('');
      el.innerHTML = `
        <h3 style="margin-top:0">${t.name} <span style="font-size:12px;color:#64748b;font-weight:normal;">(${t.id})</span></h3>
        <div style="font-size:12px;color:#94a3b8;margin-bottom:16px;">
          Session ID: <code>${t.session_id || '-'}</code> · Metadata: <code>${t.metadata || '{}'}</code>
        </div>
        <h4>Observations (${(t.observations || []).length})</h4>
        ${obsHtml || '<div style="color:#64748b">无子级 Observation</div>'}
      `;
    }
    load();
    setInterval(load, 4000);
  </script>
</body>
</html>"""


if __name__ == "__main__":
    _init_db()
    uvicorn.run(app, host="0.0.0.0", port=3000, log_level="info")
