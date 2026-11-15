# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from insight_aitest.modules.mobile.backend import deps, device_pool
from insight_aitest.modules.mobile.backend.automation import paths, session_manager
from insight_aitest.modules.mobile.backend.device_pool import DeviceLeaseManager
from insight_aitest.modules.mobile.backend.persistence.database import MobileDatabase
from insight_aitest.modules.mobile.backend.persistence.models import CaseStatus, GenerationStatus
from insight_aitest.modules.mobile.backend.routes import router as mobile_router
from insight_aitest.modules.mobile.backend.routes import devices as devices_routes
from insight_aitest.platform.services.models.device import Device, DeviceStatus, DeviceType


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

    app = FastAPI()
    app.include_router(mobile_router, prefix="/api/modules/mobile")
    with TestClient(app) as client:
        yield client, db, lease_mgr, ws

    session_manager._RUNTIMES.clear()
    paths.set_workspace_root(None)


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

    # Start MCP generation session
    sess_resp = client.post(
        f"/api/modules/mobile/automation/cases/{case_id}/generation-sessions",
        json={"device_id": "emulator-5554", "app_id": app_id, "kind": "generate"},
    )
    assert sess_resp.status_code == 200
    sess = sess_resp.json()
    token = sess["session_token"]
    gen_id = sess["generation_id"]
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

    # initialize & tools/list
    init_res = client.post(
        "/api/modules/mobile/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert init_res.status_code == 200
    assert init_res.json()["result"]["serverInfo"]["name"] == "insight-mobile-mcp"

    tools_res = client.post(
        "/api/modules/mobile/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    tool_names = {t["name"] for t in tools_res.json()["result"]["tools"]}
    assert {"get_case_context", "write_staging_file", "run_server_dry_run", "commit_staging_script"} <= tool_names

    # get_case_context
    ctx_res = client.post(
        "/api/modules/mobile/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_case_context", "arguments": {}}},
    )
    assert ctx_res.json()["result"]["isError"] is False

    # Reject path traversal on write_staging_file
    bad_write = client.post(
        "/api/modules/mobile/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "write_staging_file", "arguments": {"rel_path": "../escape.py", "content": "x = 1"}},
        },
    )
    assert bad_write.json()["result"]["isError"] is True

    # Write valid staging case.py
    valid_script = (
        "from appium.webdriver.common.appiumby import AppiumBy\n\n"
        "def test_(driver, params, app_env):\n"
        "    assert driver is not None\n"
    )
    good_write = client.post(
        "/api/modules/mobile/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "write_staging_file", "arguments": {"rel_path": "case.py", "content": valid_script}},
        },
    )
    assert good_write.json()["result"]["isError"] is False

    # Mock server dry-run and run it
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
    dry_res = client.post(
        "/api/modules/mobile/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "run_server_dry_run", "arguments": {}}},
    )
    assert dry_res.json()["result"]["isError"] is False

    # Commit staging script -> version 1, CaseStatus.IMPLEMENTED, lease released
    commit_res = client.post(
        "/api/modules/mobile/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "commit_staging_script", "arguments": {}}},
    )
    assert commit_res.json()["result"]["isError"] is False
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
