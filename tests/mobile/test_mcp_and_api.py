# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from insight_aitest.modules.mobile.backend import deps, device_pool
from insight_aitest.modules.mobile.backend.automation import mcp_server, paths, session_manager
from insight_aitest.modules.mobile.backend.device_pool import DeviceLeaseManager
from insight_aitest.modules.mobile.backend.persistence.database import MobileDatabase
from insight_aitest.modules.mobile.backend.persistence.models import CaseStatus, GenerationStatus
from insight_aitest.modules.mobile.backend.routes import devices as devices_routes
from insight_aitest.modules.mobile.backend.routes import router as mobile_router
from insight_aitest.platform.services.models.device import Device, DeviceStatus, DeviceType


def _parse_mcp_body(resp) -> dict:
    ct = (resp.headers.get("content-type") or "").lower()
    if "application/json" in ct:
        return resp.json()
    # Streamable HTTP defaults to text/event-stream
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                return json.loads(payload)
    raise AssertionError(f"无法解析 MCP 响应 (status={resp.status_code}, ct={ct}): {resp.text}")


def _mcp_post(
    client: TestClient,
    headers: dict[str, str],
    method: str,
    *,
    req_id: int | None = 1,
    params: dict | None = None,
    session_id: str | None = None,
    path: str = "/api/modules/mobile/mcp",
):
    req_headers = {
        **headers,
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        req_headers["Mcp-Session-Id"] = session_id
    body: dict = {"jsonrpc": "2.0", "method": method}
    if req_id is not None:
        body["id"] = req_id
    if params is not None:
        body["params"] = params
    return client.post(path, headers=req_headers, json=body)


@pytest.fixture()
def mobile_client(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    db = MobileDatabase(str(tmp_path / "mobile.db"))
    paths.set_workspace_root(ws)
    monkeypatch.setattr(deps, "_db", db)
    lease_mgr = DeviceLeaseManager()
    monkeypatch.setattr(device_pool, "_lease_manager", lease_mgr)
    monkeypatch.setattr(session_manager, "_lease_manager", lease_mgr, raising=False)
    monkeypatch.setattr(session_manager, "get_lease_manager", lambda: lease_mgr)
    monkeypatch.setattr(mcp_server, "get_mobile_db", lambda: db)
    session_manager._RUNTIMES.clear()

    fake_devices = [
        Device(
            device_id="emulator-5554",
            name="Pixel_7",
            type=DeviceType.ANDROID,
            status=DeviceStatus.ONLINE,
            model="Pixel 7",
            sdk_version="14",
        )
    ]
    monkeypatch.setattr(device_pool.DeviceManager, "scan_devices", staticmethod(lambda: fake_devices))
    fake_appium = lambda url="http://127.0.0.1:4723", timeout=2.0: {"ready": True, "url": url, "detail": "ok"}
    monkeypatch.setattr(device_pool, "check_appium_status", fake_appium)
    monkeypatch.setattr(devices_routes, "check_appium_status", fake_appium)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp_server.get_mcp_server().session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(mobile_router, prefix="/api/modules/mobile")
    mcp_server.mount_mobile_mcp(app)
    with TestClient(app) as client:
        yield client, db, lease_mgr, ws

    session_manager._RUNTIMES.clear()
    paths.set_workspace_root(None)


def test_mobile_mcp_metadata_prompts_and_resources_conventions():
    server = mcp_server.get_mcp_server()
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    expected_tools = {
        "get_case_context",
        "mobile_launch_app",
        "mobile_snapshot",
        "mobile_screenshot",
        "mobile_tap",
        "mobile_input",
        "mobile_swipe",
        "mobile_back",
        "mobile_handle_alert",
        "read_staging_file",
        "write_staging_file",
        "run_server_dry_run",
        "commit_staging_script",
    }
    assert set(tools) == expected_tools
    for name, tool in tools.items():
        assert tool.title, name
        assert tool.description, name
        assert tool.output_schema, name
        for prop, spec in (tool.input_schema.get("properties") or {}).items():
            assert spec.get("description"), f"{name}.{prop} 缺少参数描述"

    assert tools["get_case_context"].annotations.read_only_hint is True
    assert tools["commit_staging_script"].annotations.destructive_hint is True
    assert tools["mobile_tap"].annotations.open_world_hint is True

    assert [p.name for p in asyncio.run(server.list_prompts())] == ["mobile.create", "mobile.fix"]
    assert [str(r.uri) for r in asyncio.run(server.list_resources())] == [
        "insight://mobile/instructions",
        "insight://mobile/rules",
        "insight://mobile/template",
    ]


def test_apps_devices_and_wireless_api(mobile_client, monkeypatch):
    client, db, _, _ = mobile_client

    # Create App with secret password -> never echoed
    resp = client.post(
        "/api/modules/mobile/automation/apps",
        json={
            "project_id": 1,
            "name": "DemoApp",
            "app_package": "com.example.demo",
            "app_activity": ".MainActivity",
            "test_username": "tester",
            "password": "super-secret-password",
            "is_default": True,
        },
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["password_set"] is True
    assert "super-secret-password" not in resp.text

    listed = client.get("/api/modules/mobile/automation/apps", params={"project_id": 1}).json()
    assert len(listed) == 1 and listed[0]["app_package"] == "com.example.demo"

    # Devices listing & wireless ADB
    devs = client.get("/api/modules/mobile/devices").json()
    assert devs["appium"]["ready"] is True
    assert devs["devices"][0]["device_id"] == "emulator-5554"

    monkeypatch.setattr(
        device_pool,
        "_run_adb",
        lambda args, timeout=10: (0, "inet 192.168.1.99/24 scope global wlan0")
        if "wlan0" in args
        else (0, "restarting in TCP mode"),
    )
    w_resp = client.post("/api/modules/mobile/devices/emulator-5554/wireless")
    assert w_resp.status_code == 200
    assert w_resp.json()["endpoint"] == "192.168.1.99:5555"


def test_mcp_generation_dry_run_and_commit_flow(mobile_client, monkeypatch):
    client, db, lease_mgr, _ = mobile_client

    app_id = db.create_app(
        project_id=1,
        name="DemoApp",
        app_package="com.example.demo",
        app_activity=".MainActivity",
        is_default=1,
    )
    case_id = db.create_case(
        project_id=1,
        kb_document_id=500,
        title="登录后校验首页",
        precondition="未登录状态",
        steps=["点击登录", "断言首页标题"],
        expected="进入首页",
        category_path="登录",
    )

    # Start MCP generation session (respecting x-forwarded-host like UI module)
    sess_resp = client.post(
        f"/api/modules/mobile/automation/cases/{case_id}/generation-sessions",
        json={"device_id": "emulator-5554", "app_id": app_id, "kind": "generate"},
        headers={"x-forwarded-host": "demo.insight.local:8080", "x-forwarded-proto": "https"},
    )
    assert sess_resp.status_code == 200
    sess = sess_resp.json()
    token = sess["session_token"]
    gen_id = sess["generation_id"]
    assert sess["mcp_url"] == "https://demo.insight.local:8080/api/modules/mobile/mcp"
    assert "get_case_context" in sess["agent_prompt"]
    assert f"Bearer {token}" in sess["agent_prompt"]
    assert f"- case_id: {case_id}" in sess["agent_prompt"]
    # 环境、用例详情由 MCP 协商获取，不硬塞进文案
    assert "emulator-5554" not in sess["agent_prompt"]
    assert "com.example.demo" not in sess["agent_prompt"]
    assert "点击登录" not in sess["agent_prompt"]
    assert lease_mgr.get("emulator-5554") is not None

    # Starting another session on busy device returns 409
    case2_id = db.create_case(project_id=1, kb_document_id=501, title="另一条用例")
    conflict = client.post(
        f"/api/modules/mobile/automation/cases/{case2_id}/generation-sessions",
        json={"device_id": "emulator-5554", "app_id": app_id},
    )
    assert conflict.status_code == 409

    headers = {"Authorization": f"Bearer {token}"}

    # MCP without token -> 401
    unauth = client.post("/api/modules/mobile/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert unauth.status_code == 401

    # initialize & notifications/initialized
    init_resp = _mcp_post(
        client,
        headers,
        "initialize",
        req_id=1,
        params={
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    )
    assert init_resp.status_code == 200
    mcp_session_id = init_resp.headers.get("mcp-session-id")
    assert mcp_session_id
    init_body = _parse_mcp_body(init_resp)
    assert init_body["result"]["serverInfo"]["name"] == "insight-mobile-mcp"

    notif_resp = _mcp_post(
        client, headers, "notifications/initialized", req_id=None, session_id=mcp_session_id
    )
    assert notif_resp.status_code == 202

    tools_resp = _mcp_post(client, headers, "tools/list", req_id=2, session_id=mcp_session_id)
    assert tools_resp.status_code == 200
    tool_names = {t["name"] for t in _parse_mcp_body(tools_resp)["result"]["tools"]}
    assert {"get_case_context", "write_staging_file", "run_server_dry_run", "commit_staging_script"} <= tool_names

    # get_case_context: summary in content[0].text, full payload in structuredContent
    ctx_resp = _mcp_post(
        client,
        headers,
        "tools/call",
        req_id=3,
        params={"name": "get_case_context", "arguments": {}},
        session_id=mcp_session_id,
    )
    ctx_res = _parse_mcp_body(ctx_resp)["result"]
    assert ctx_res["isError"] is False
    assert "【用例上下文】" in ctx_res["content"][0]["text"]
    assert ctx_res["structuredContent"]["device_id"] == "emulator-5554"
    assert ctx_res["structuredContent"]["intent"] == "create"
    assert ctx_res["structuredContent"]["workflow"]["id"] == "mobile.create@1"

    # prompts/get reuses unified prompt_builder
    prompt_resp = _mcp_post(
        client,
        headers,
        "prompts/get",
        req_id=30,
        params={"name": "mobile.create", "arguments": {}},
        session_id=mcp_session_id,
    )
    prompt_res = _parse_mcp_body(prompt_resp)["result"]
    prompt_text = prompt_res["messages"][0]["content"]["text"]
    assert "get_case_context" in prompt_text
    assert f"- case_id: {case_id}" in prompt_text

    # mobile_screenshot returns ImageContent + structuredContent
    monkeypatch.setattr(
        session_manager,
        "tool_screenshot",
        lambda rt, label="": (b"\x89PNG\r\n\x1a\nfake", "001_shot.png"),
    )
    shot_resp = _mcp_post(
        client,
        headers,
        "tools/call",
        req_id=4,
        params={"name": "mobile_screenshot", "arguments": {"label": "shot"}},
        session_id=mcp_session_id,
    )
    shot_res = _parse_mcp_body(shot_resp)["result"]
    assert shot_res["isError"] is False
    assert shot_res["content"][1]["type"] == "image"
    assert shot_res["structuredContent"]["filename"] == "001_shot.png"

    # Reject path traversal on write_staging_file
    bad_write = _parse_mcp_body(
        _mcp_post(
            client,
            headers,
            "tools/call",
            req_id=5,
            params={
                "name": "write_staging_file",
                "arguments": {"rel_path": "../escape.py", "content": "x = 1"},
            },
            session_id=mcp_session_id,
        )
    )["result"]
    assert bad_write["isError"] is True
    assert "structuredContent" not in bad_write
    bad_err = json.loads(bad_write["content"][0]["text"])
    assert bad_err["code"] == "INVALID_PATH"

    # Write valid staging case.py
    valid_script = (
        "from appium.webdriver.common.appiumby import AppiumBy\n\n"
        "def test_(driver, params, app_env):\n"
        "    assert driver is not None\n"
    )
    good_write = _parse_mcp_body(
        _mcp_post(
            client,
            headers,
            "tools/call",
            req_id=6,
            params={
                "name": "write_staging_file",
                "arguments": {"rel_path": "case.py", "content": valid_script},
            },
            session_id=mcp_session_id,
        )
    )["result"]
    assert good_write["isError"] is False

    # Commit before dry-run -> structured DRY_RUN_REQUIRED error
    early_commit = _parse_mcp_body(
        _mcp_post(
            client,
            headers,
            "tools/call",
            req_id=61,
            params={"name": "commit_staging_script", "arguments": {}},
            session_id=mcp_session_id,
        )
    )["result"]
    assert early_commit["isError"] is True
    assert "structuredContent" not in early_commit
    early_err = json.loads(early_commit["content"][0]["text"])
    assert early_err["code"] == "DRY_RUN_REQUIRED"
    assert early_err["required_next"] == "run_server_dry_run"

    # Failing dry-run -> structured DRY_RUN_FAILED error
    def fake_fail_script(case, app, device_id, *, script_path=None, out_dir=None, **kwargs):
        return {
            "status": "failed",
            "run_status": "failed",
            "error_category": "script",
            "error_message": "AssertionError: element missing",
            "duration_ms": 120,
            "screenshots": [],
            "artifacts_rel_path": "artifacts/dry_fail",
            "stdout_tail": "AssertionError: element missing",
            "logcat_tail": "",
        }

    monkeypatch.setattr(session_manager, "run_script", fake_fail_script)
    fail_dry = _parse_mcp_body(
        _mcp_post(
            client,
            headers,
            "tools/call",
            req_id=62,
            params={"name": "run_server_dry_run", "arguments": {}},
            session_id=mcp_session_id,
        )
    )["result"]
    assert fail_dry["isError"] is True
    assert "structuredContent" not in fail_dry
    dry_err = json.loads(fail_dry["content"][0]["text"])
    assert dry_err["code"] == "DRY_RUN_FAILED"
    assert dry_err["required_next"] == "write_staging_file"

    # Mock passing server dry-run and run it
    def fake_run_script(case, app, device_id, *, script_path=None, out_dir=None, **kwargs):
        return {
            "status": "passed",
            "run_status": "passed",
            "error_category": None,
            "error_message": "",
            "duration_ms": 210,
            "screenshots": [],
            "artifacts_rel_path": "artifacts/dry",
            "stdout_tail": "1 passed in 0.21s",
            "logcat_tail": "",
        }

    monkeypatch.setattr(session_manager, "run_script", fake_run_script)
    dry_res = _parse_mcp_body(
        _mcp_post(
            client,
            headers,
            "tools/call",
            req_id=7,
            params={"name": "run_server_dry_run", "arguments": {}},
            session_id=mcp_session_id,
        )
    )["result"]
    assert dry_res["isError"] is False
    assert dry_res["structuredContent"]["passed"] is True

    # Commit staging script -> version 1, CaseStatus.IMPLEMENTED, lease released
    commit_res = _parse_mcp_body(
        _mcp_post(
            client,
            headers,
            "tools/call",
            req_id=8,
            params={"name": "commit_staging_script", "arguments": {}},
            session_id=mcp_session_id,
        )
    )["result"]
    assert commit_res["isError"] is False
    assert commit_res["structuredContent"]["script_version"] == 1
    assert lease_mgr.get("emulator-5554") is None

    case_after = db.get_case(case_id)
    assert case_after.status == CaseStatus.IMPLEMENTED
    assert case_after.script_version == 1
    assert Path(paths.resolve_rel(case_after.script_rel_path)).exists()
    assert db.get_generation(gen_id).status == GenerationStatus.SUCCESS

    # Read script via API
    script_api = client.get(f"/api/modules/mobile/automation/cases/{case_id}/script")
    assert script_api.status_code == 200
    assert script_api.json()["version"] == 1


def test_cancel_generation_releases_device_and_restores_status(mobile_client):
    client, db, lease_mgr, _ = mobile_client
    app_id = db.create_app(project_id=1, name="Demo", app_package="com.example.demo", is_default=1)
    case_id = db.create_case(project_id=1, kb_document_id=777, title="待取消用例")

    res = client.post(
        f"/api/modules/mobile/automation/cases/{case_id}/generation-sessions",
        json={"device_id": "emulator-5554", "app_id": app_id},
    )
    assert res.status_code == 200
    assert lease_mgr.get("emulator-5554") is not None

    cancel_res = client.post(f"/api/modules/mobile/automation/cases/{case_id}/cancel-generate")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["cancelled"] is True
    assert lease_mgr.get("emulator-5554") is None
    assert db.get_case(case_id).status == CaseStatus.NOT_IMPLEMENTED


def test_active_generation_recovery_duplicate_guard_and_stale_lease_cleanup(mobile_client):
    from datetime import datetime, timedelta

    client, db, lease_mgr, _ = mobile_client
    app_id = db.create_app(project_id=1, name="Demo", app_package="com.example.demo", is_default=1)
    case_id = db.create_case(project_id=1, kb_document_id=888, title="断点恢复与防重用例")

    # 初始无进行中会话
    idle_res = client.get(f"/api/modules/mobile/automation/cases/{case_id}/active-generation")
    assert idle_res.status_code == 200
    assert idle_res.json() == {"active": False, "generation": None}

    # 创建会话 -> active-generation 可查询到
    start_res = client.post(
        f"/api/modules/mobile/automation/cases/{case_id}/generation-sessions",
        json={"device_id": "emulator-5554", "app_id": app_id},
    )
    assert start_res.status_code == 200
    gen_id = start_res.json()["generation_id"]

    active_res = client.get(f"/api/modules/mobile/automation/cases/{case_id}/active-generation")
    assert active_res.status_code == 200
    payload = active_res.json()
    assert payload["active"] is True
    assert payload["generation"]["id"] == gen_id
    assert payload["generation"]["device_id"] == "emulator-5554"
    assert payload["generation"]["status"] == "running"

    # 项目级进行中任务列表（编写进度弹窗）应包含该会话
    list_active = client.get("/api/modules/mobile/automation/cases/generations/active?project_id=1")
    assert list_active.status_code == 200
    items = list_active.json()
    assert len(items) == 1
    assert items[0]["case_id"] == case_id
    assert items[0]["generation_id"] == gen_id
    assert items[0]["device_id"] == "emulator-5554"
    assert items[0]["stage"] == "waiting"

    # 同一用例再次创建不会生成冗余失败记录，直接 409 提示
    dup_res = client.post(
        f"/api/modules/mobile/automation/cases/{case_id}/generation-sessions",
        json={"device_id": "emulator-5554", "app_id": app_id},
    )
    assert dup_res.status_code == 409
    assert "已有进行中的生成会话" in dup_res.json()["detail"]
    assert len(db.list_generations(case_id)) == 1

    # 模拟设备租约超时过期 -> active-generation 自动清理僵尸会话并恢复用例状态
    lease = lease_mgr.get("emulator-5554")
    assert lease is not None
    lease.expires_at = datetime.now() - timedelta(seconds=1)

    expired_res = client.get(f"/api/modules/mobile/automation/cases/{case_id}/active-generation")
    assert expired_res.status_code == 200
    assert expired_res.json() == {"active": False, "generation": None}
    assert db.get_generation(gen_id).status == "cancelled"
    assert db.get_case(case_id).status == CaseStatus.NOT_IMPLEMENTED
