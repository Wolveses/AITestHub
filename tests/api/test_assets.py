# -*- coding: utf-8 -*-
"""接口资产：独立库写入/查询、AI 整理提示词脱敏与结果解析。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from insight_aitest.modules.api.backend.persistence.asset_database import AssetDatabase
from insight_aitest.modules.api.backend.services.asset_enhance import (
    build_messages,
    build_payload,
    enhance,
    infer_schema,
    jsonpath_samples,
    parse_result,
)


def _asset(**kwargs):
    base = {
        "title": "",
        "method": "GET",
        "path": "/api/users/1?token=abc",
        "path_template": "/api/users/{id}",
        "base_url": "https://demo.test",
        "headers": {"Authorization": "Bearer x", "Content-Type": "application/json"},
        "body": None,
        "response_status": 200,
        "response_headers": {"Set-Cookie": "sid=1", "Content-Type": "application/json"},
        "response_body": {"code": 0, "data": {"id": 1, "name": "tom"}},
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_database_upsert_dedupes_and_updates(tmp_path):
    db = AssetDatabase(str(tmp_path / "api.db"))
    item = {
        "project_id": 1,
        "fingerprint": "GET /api/users/{id}",
        "title": "查询用户",
        "method": "GET",
        "path": "/api/users/1",
        "path_template": "/api/users/{id}",
        "base_url": "https://demo.test",
        "headers": {"Accept": "application/json"},
        "body": None,
        "response_status": 200,
        "response_headers": {},
        "response_body": {"code": 0},
        "times_seen": 1,
    }
    assert db.upsert_many([item]) == {"imported": 1, "updated": 0}
    assert db.upsert_many([{**item, "response_body": {"code": 1}, "times_seen": 2}]) == {
        "imported": 0,
        "updated": 1,
    }
    items, total = db.list_assets(project_id=1)
    assert total == 1
    assert items[0].times_seen == 3
    assert items[0].response_body == {"code": 1}

    asset = db.get(items[0].id)
    assert asset is not None
    db.update(asset.id, is_noise=True, title="用户详情")
    filtered, noise_total = db.list_assets(project_id=1, hide_noise=True)
    assert filtered == [] and noise_total == 0
    assert db.delete(asset.id) is True
    assert db.list_assets(project_id=1)[1] == 0


def test_database_project_null_isolated(tmp_path):
    db = AssetDatabase(str(tmp_path / "api.db"))
    item = {
        "project_id": None,
        "fingerprint": "GET /api/ping",
        "method": "GET",
        "path": "/api/ping",
        "path_template": "/api/ping",
        "base_url": "https://demo.test",
        "headers": {},
        "body": None,
        "response_status": 200,
        "response_headers": {},
        "response_body": {"ok": True},
        "times_seen": 1,
    }
    assert db.upsert_many([item])["imported"] == 1
    assert db.upsert_many([item])["updated"] == 1
    items, _ = db.list_assets()
    assert items[0].times_seen == 2


def test_build_payload_strips_credentials():
    payload = build_payload(_asset(body={"password": "p", "name": "tom"}))
    assert "Authorization" not in payload["request_headers"]
    assert "Set-Cookie" not in payload["response_headers"]
    assert payload["request_headers"]["Content-Type"] == "application/json"
    assert "token=abc" not in payload["path"]
    assert payload["path"].endswith("token=<redacted>")


def test_parse_result_tolerates_trailing_text():
    text = (
        '{"title":"用户详情","summary":"查询单个用户","is_noise":false,'
        '"path_template":"/api/users/{{user_id}}",'
        '"variables":[{"name":"user_id","in":"path","example":"1"}]}}'
        "\n以上是整理结果。"
    )
    result = parse_result(text)
    assert result["title"] == "用户详情"
    assert result["path_template"] == "/api/users/{{user_id}}"
    assert result["variables"][0]["name"] == "user_id"


def test_enhance_uses_single_chat_call():
    calls: list[dict] = []

    class FakeLLM:
        _config = SimpleNamespace(chat_model="fake-model")

        def chat(self, messages, **kwargs):
            calls.append({"messages": messages, **kwargs})
            return json.dumps({"title": "用户详情", "summary": "查询单个用户"})

    result = enhance(_asset(), FakeLLM())
    assert len(calls) == 1
    assert calls[0]["temperature"] == 0
    assert result["model"] == "fake-model"
    assert result["title"] == "用户详情"


def test_infer_schema_and_samples():
    schema = infer_schema({"code": 0, "data": {"list": [{"id": 1, "ok": True}]}})
    assert schema["type"] == "object"
    assert schema["properties"]["code"] == {"type": "integer"}
    assert schema["properties"]["data"]["properties"]["list"]["items"]["type"] == "object"

    samples = jsonpath_samples({"code": 0, "data": {"name": "tom"}})
    assert samples[0] == {"path": "$.code", "type": "int", "sample": 0}
    assert any(s["path"] == "$.data.name" for s in samples)


def test_build_messages_keeps_single_json_contract():
    messages = build_messages(build_payload(_asset()))
    assert messages[0]["role"] == "system"
    assert "只输出一个 JSON 对象" in messages[0]["content"]
    assert "Bearer x" not in messages[1]["content"]
