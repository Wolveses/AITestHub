# -*- coding: utf-8 -*-
"""UI 生成期抓包 → 接口资产规则测试（不依赖浏览器与大模型）。"""

from __future__ import annotations

import json

from insight_aitest.modules.ui.backend.automation.capture import (
    build_assets,
    clean_headers,
    fingerprint,
    import_captured_api_assets,
    load_records,
    path_template,
    redact_body,
)


def test_path_template_normalizes_ids():
    assert path_template("/api/users/123") == "/api/users/{id}"
    assert path_template("/api/orders/550e8400-e29b-41d4-a716-446655440000") == "/api/orders/{uuid}"
    assert path_template("/api/files/0123456789abcdef0123") == "/api/files/{hash}"
    assert fingerprint("post", "/api/users/42") == "POST /api/users/{id}"


def test_clean_headers_drops_credentials_and_noise():
    cleaned = clean_headers(
        {
            "Authorization": "Bearer abc",
            "Cookie": "sid=1",
            "X-Csrf-Token": "xyz",
            "User-Agent": "Mozilla",
            "Content-Type": "application/json",
            "X-Trace-Id": "t1",
        }
    )
    assert cleaned == {"Content-Type": "application/json", "X-Trace-Id": "t1"}


def test_redact_body_hides_sensitive_fields():
    data = redact_body({"user": "tom", "password": "p", "nested": {"token": "t"}})
    assert data == {"user": "tom", "password": "<redacted>", "nested": {"token": "<redacted>"}}


def _record(url, method="GET", status=200, rtype="xhr", body=None, headers=None):
    return {
        "url": url,
        "method": method,
        "status": status,
        "resource_type": rtype,
        "request_headers": headers or {},
        "request_body": body,
        "response_headers": {"content-type": "application/json"},
        "response_body": {"ok": True},
    }


def test_build_assets_filters_and_merges():
    records = [
        _record("https://demo.test/api/users/1"),
        _record("https://demo.test/api/users/2"),  # 同指纹，合并计数
        _record("https://demo.test/api/users/1", method="POST"),
        _record("https://demo.test/static/app.js", rtype="script"),  # 静态资源
        _record("https://other.test/api/users/1"),  # 跨域
        _record("https://demo.test/api/users/1", method="OPTIONS", status=204),
        _record("https://demo.test/api/users/1", status=500),
        _record("https://demo.test/api/login", method="POST"),  # 鉴权路径
        _record("https://demo.test/api/orders?token=abc", method="POST", body="a=1&b=2"),
    ]
    assets = build_assets(records, base_origin="https://demo.test", login_api_path="/api/login")
    by_fp = {a["fingerprint"]: a for a in assets}
    assert set(by_fp) == {"GET /api/users/{id}", "POST /api/users/{id}", "POST /api/orders"}
    assert by_fp["GET /api/users/{id}"]["times_seen"] == 2
    assert by_fp["POST /api/orders"]["path"].endswith("token=<redacted>")


def test_load_records_skips_broken_lines(tmp_path):
    path = tmp_path / "network.jsonl"
    path.write_text(
        json.dumps(_record("https://demo.test/api/x")) + "\nnot-json\n\n",
        encoding="utf-8",
    )
    assert len(load_records(path)) == 1
    assert load_records(tmp_path / "missing.jsonl") == []


def test_import_captured_api_assets_writes_to_db(tmp_path, monkeypatch):
    from insight_aitest.modules.api.backend.persistence.asset_database import AssetDatabase

    db = AssetDatabase(str(tmp_path / "api.db"))
    monkeypatch.setattr(
        "insight_aitest.modules.api.backend.deps.get_asset_db", lambda: db, raising=False
    )
    network = tmp_path / "network.jsonl"
    network.write_text(
        json.dumps(_record("https://demo.test/api/users/1", body='{"password":"p"}'))
        + "\n",
        encoding="utf-8",
    )
    stats = import_captured_api_assets(
        project_id=1,
        ui_case_id=9,
        ui_case_title="查询用户",
        network_path=network,
        base_origin="https://demo.test",
    )
    assert stats["captured"] == 1
    assert stats["imported"] == 1
    items, total = db.list_assets(project_id=1)
    assert total == 1
    assert items[0].source_case_id == 9
    assert items[0].body == {"password": "<redacted>"}
