# -*- coding: utf-8 -*-
"""平台 LLM 自动化辅助能力总开关（ai_assist_enabled）全链路单测与隔离回归。"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from insight_aitest.platform.services.llm.config import LLMConfig, load_config, save_config


@pytest.fixture(autouse=True)
def _reset_platform_config_singletons(tmp_path, monkeypatch):
    """隔离每个用例的配置文件路径与单例缓存。"""
    import insight_aitest.modules.ai.backend.deps as ai_deps
    import insight_aitest.platform.services.kb.deps as kb_deps

    cfg_path = str(tmp_path / "llm_config.json")
    monkeypatch.delenv("INSIGHT_EYE_AI_ASSIST_ENABLED", raising=False)
    monkeypatch.setenv("INSIGHT_EYE_AI_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("INSIGHT_EYE_AI_EMBED_DIM", "4")

    kb_deps._llm_config = None
    kb_deps._llm = None
    kb_deps._vector_store = None
    kb_deps._retriever = None
    kb_deps._kb_db = None
    kb_deps.set_config_file(cfg_path)
    ai_deps._db = None
    ai_deps._agent = None

    yield cfg_path

    kb_deps._llm_config = None
    kb_deps._llm = None
    kb_deps._vector_store = None
    kb_deps._retriever = None
    kb_deps._kb_db = None
    kb_deps.set_config_file(None)


def _set_assist_enabled(enabled: bool) -> None:
    import insight_aitest.platform.services.kb.deps as kb_deps

    cfg = kb_deps.get_llm_config()
    cfg.ai_assist_enabled = enabled


# ===== 1. 配置模型、持久化、环境变量覆盖与 API 读写 =====


def test_config_default_save_load_and_env_override(tmp_path, monkeypatch):
    cfg_path = str(tmp_path / "llm_config.json")
    cfg = LLMConfig()
    assert cfg.ai_assist_enabled is True

    cfg.ai_assist_enabled = False
    save_config(cfg, cfg_path)
    loaded = load_config(cfg_path)
    assert loaded.ai_assist_enabled is False

    # 环境变量优先级最高
    monkeypatch.setenv("INSIGHT_EYE_AI_ASSIST_ENABLED", "true")
    overridden = load_config(cfg_path)
    assert overridden.ai_assist_enabled is True

    monkeypatch.setenv("INSIGHT_EYE_AI_ASSIST_ENABLED", "false")
    overridden_false = load_config(cfg_path)
    assert overridden_false.ai_assist_enabled is False


def test_platform_capabilities_and_ai_config_route(tmp_path):
    import insight_aitest.platform.services.kb.deps as kb_deps
    from insight_aitest.modules.ai.backend.routes import router as ai_router
    from insight_aitest.platform.api.platform import build_platform_router

    cfg = kb_deps.get_llm_config()
    cfg.db_path = str(tmp_path / "kb.db")
    cfg.docs_dir = str(tmp_path / "docs")

    app = FastAPI()
    app.include_router(build_platform_router(), prefix="/api/platform")
    app.include_router(ai_router, prefix="/api/modules/ai")
    c = TestClient(app)

    assert c.get("/api/platform/capabilities").json() == {"ai_assist_enabled": True}
    assert c.get("/api/modules/ai/config").json()["ai_assist_enabled"] is True

    r = c.put("/api/modules/ai/config", json={"ai_assist_enabled": False})
    assert r.status_code == 200
    assert r.json()["ai_assist_enabled"] is False
    assert c.get("/api/platform/capabilities").json() == {"ai_assist_enabled": False}

    # 重新加载文件确认已持久化
    assert load_config(cfg.config_file).ai_assist_enabled is False


# ===== 2. UI 自动化 LLM 脚本生成/修复/重新生成 vs 本地 Agent 隔离 =====


def test_ui_automation_llm_blocked_but_local_agent_unaffected(tmp_path):
    import insight_aitest.modules.ui.backend.automation.deps as auto_deps
    from insight_aitest.modules.ui.backend.automation.database import UIAutomationDatabase
    from insight_aitest.modules.ui.backend.automation.generator import start_job
    from insight_aitest.modules.ui.backend.automation.routes import router as automation_router

    db = UIAutomationDatabase(str(tmp_path / "ui_auto.db"))
    auto_deps._db = db
    case_id = db.create_case(
        project_id=1,
        kb_document_id=101,
        title="登录验证",
        steps=["打开登录页", "点击登录"],
        expected="进入首页",
    )

    app = FastAPI()
    app.include_router(automation_router, prefix="/api/modules/ui")
    c = TestClient(app)

    _set_assist_enabled(False)

    for action in ("generate", "fix", "regenerate"):
        r = c.post(f"/api/modules/ui/automation/cases/{case_id}/{action}")
        assert r.status_code == 403
        assert "本地 Agent" in r.json()["detail"]

    with pytest.raises(RuntimeError, match="已关闭 LLM 自动化辅助能力"):
        start_job(case_id, "generate")

    # 本地 Agent authoring 链路不受任何影响
    r_local = c.post(
        "/api/modules/ui/automation/authoring/prompt",
        json={"project_id": 1, "case_ids": [case_id], "mode": "auto"},
    )
    assert r_local.status_code == 200
    assert r_local.json()["ok"] is True
    assert r_local.json()["prompt"]

    auto_deps._db = None


# ===== 3. UI 旧版 Midscene 视觉执行 & 批量执行 & 定时批量 =====


def test_ui_midscene_runs_batch_and_schedule_blocked_when_disabled(tmp_path, monkeypatch):
    import insight_aitest.modules.ui.backend.deps as ui_deps
    from insight_aitest.modules.ui.backend.persistence.batch_database import UIBatchRunDatabase
    from insight_aitest.modules.ui.backend.persistence.database import UIRunDatabase
    from insight_aitest.modules.ui.backend.routes import router as ui_router
    from insight_aitest.modules.ui.backend.scheduler.manager import _run_scheduled_ui_batch

    ui_deps._run_db = UIRunDatabase(str(tmp_path / "ui.db"))
    ui_deps._batch_db = UIBatchRunDatabase(str(tmp_path / "ui.db"))

    monkeypatch.setattr(
        "insight_aitest.modules.ui.backend.routes.runs._fetch_case_from_d",
        lambda case_id: {"id": case_id, "title": "t", "content": {"base_url": "http://x", "steps": []}},
    )
    agent_called = {"count": 0}
    monkeypatch.setattr(
        "insight_aitest.modules.ui.backend.routes.runs._make_agent_factory",
        lambda: agent_called.__setitem__("count", agent_called["count"] + 1),
    )

    app = FastAPI()
    app.include_router(ui_router, prefix="/api/modules/ui")
    c = TestClient(app)

    _set_assist_enabled(False)

    r_exec = c.post("/api/modules/ui/runs/execute", json={"case_id": 1})
    assert r_exec.status_code == 403
    assert agent_called["count"] == 0

    r_batch = c.post("/api/modules/ui/batch/execute", json={"case_ids": [1, 2]})
    assert r_batch.status_code == 403
    assert c.get("/api/modules/ui/batch/runs").json() == []

    # 定时回调也直接跳过，不创建任何 batch run 记录
    _run_scheduled_ui_batch(999)
    assert c.get("/api/modules/ui/batch/runs").json() == []


# ===== 4. API 整理（手动 / HAR / UI 抓包）& 5. API 用例生成规则降级 =====


def test_api_enhance_blocked_and_har_capture_skip_ai_and_compose_fallback(tmp_path, monkeypatch):
    import insight_aitest.modules.api.backend.deps as api_deps
    from insight_aitest.modules.api.backend.persistence.asset_database import AssetDatabase
    from insight_aitest.modules.api.backend.routes import router as api_router
    from insight_aitest.modules.ui.backend.automation.capture import (
        _auto_enhance_assets,
        import_captured_api_assets,
    )

    asset_db = AssetDatabase(str(tmp_path / "api.db"))
    api_deps._asset_db = asset_db

    asset_db.upsert_many(
        [
            {
                "project_id": 1,
                "fingerprint": "POST /api/items",
                "title": "创建商品",
                "method": "POST",
                "path": "/api/items",
                "path_template": "/api/items",
                "base_url": "https://demo.test",
                "headers": {"Content-Type": "application/json"},
                "body": {"name": "apple"},
                "response_status": 200,
                "response_headers": {"Content-Type": "application/json"},
                "response_body": {"code": 0, "data": {"id": 42}},
                "times_seen": 1,
            },
            {
                "project_id": 1,
                "fingerprint": "GET /api/items/{id}",
                "title": "查询商品",
                "method": "GET",
                "path": "/api/items/42",
                "path_template": "/api/items/{id}",
                "base_url": "https://demo.test",
                "headers": {},
                "body": None,
                "response_status": 200,
                "response_headers": {"Content-Type": "application/json"},
                "response_body": {"code": 0, "data": {"id": 42}},
                "times_seen": 1,
            },
        ]
    )
    items, _ = asset_db.list_assets(project_id=1)
    asset_ids = [a.id for a in items]

    # 确保绝不会调用到 get_llm
    monkeypatch.setattr(
        "insight_aitest.modules.ai.backend.deps.get_llm",
        MagicMock(side_effect=AssertionError("不应该调用 get_llm")),
    )

    _set_assist_enabled(False)

    app = FastAPI()
    app.include_router(api_router, prefix="/api/modules/api")
    c = TestClient(app)

    # 手动整理 -> HTTP 403
    r_enhance = c.post(f"/api/modules/api/assets/{asset_ids[0]}/enhance")
    assert r_enhance.status_code == 403

    # HAR 导入（带 auto_enhance=True）-> 正常入库且不启动 AI 整理线程
    r_har = c.post(
        "/api/modules/api/assets/import-har",
        json={
            "project_id": 1,
            "auto_enhance": True,
            "items": [
                {
                    "fingerprint": "DELETE /api/items/{id}",
                    "method": "DELETE",
                    "path": "/api/items/42",
                    "path_template": "/api/items/{id}",
                    "base_url": "https://demo.test",
                    "title": "删除商品",
                }
            ],
        },
    )
    assert r_har.status_code == 200
    assert r_har.json()["imported"] == 1

    # 多资产组装（即使传 ai_order=True）-> 优雅退化为纯规则编排且 ai_used=False
    r_compose = c.post(
        "/api/modules/api/assets/compose",
        json={"asset_ids": asset_ids, "title": "商品创建查询流", "ai_order": True},
    )
    assert r_compose.status_code == 200
    assert r_compose.json()["ai_used"] is False
    assert len(r_compose.json()["steps"]) == 2

    # UI 抓包导入（auto_enhance=True）-> 正常保存但跳过队列；直接调用 _auto_enhance_assets 也安全跳过
    cap_path = str(tmp_path / "captured.jsonl")
    with open(cap_path, "w", encoding="utf-8") as f:
        f.write(
            '{"url":"https://demo.test/api/orders","method":"POST","status":200,'
            '"resource_type":"xhr","request_headers":{},"request_body":{"x":1},'
            '"response_headers":{"content-type":"application/json"},"response_body":{"ok":true}}\n'
        )
    cap_stats = import_captured_api_assets(
        project_id=1,
        ui_case_id=10,
        ui_case_title="下单",
        network_path=cap_path,
        auto_enhance=True,
    )
    assert cap_stats["imported"] == 1
    assert cap_stats["enhance_queued"] == 0

    enhance_stats = _auto_enhance_assets(
        asset_db, project_id=1, fingerprints=["POST /api/orders"], limit=10
    )
    assert enhance_stats["enhanced"] == 0
    assert enhance_stats["enhance_skipped"] == 1


# ===== 6. Performance 性能方案 AI 挑选接口 =====


def test_performance_ai_blocked_and_service_skips_llm_when_disabled(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(os.path.abspath("insight_aitest/modules"))
    import insight_aitest.modules.api.backend.deps as api_deps
    from insight_aitest.modules.api.backend.persistence.asset_database import AssetDatabase
    from insight_aitest.modules.performance.backend.routes.server_perf import router as perf_router
    from insight_aitest.modules.performance.backend.services.ai_service import PerfAIService

    asset_db = AssetDatabase(str(tmp_path / "api.db"))
    api_deps._asset_db = asset_db
    asset_db.upsert_many(
        [
            {
                "project_id": 1,
                "fingerprint": "GET /api/ping",
                "title": "健康检查",
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
        ]
    )

    _set_assist_enabled(False)

    app = FastAPI()
    app.include_router(perf_router, prefix="/api/modules/performance")
    c = TestClient(app)

    r = c.post(
        "/api/modules/performance/server/scripts/generate-from-plan",
        json={"project_id": 1, "plan_description": "压测健康检查", "concurrency": 10},
    )
    assert r.status_code == 403

    # Service 内核防御：即便传入 llm 对象也不调用 llm.chat
    fake_llm = MagicMock()
    fake_llm.chat.side_effect = AssertionError("关闭开关后不应调用 llm.chat")
    res = PerfAIService.generate_script_from_plan(
        project_id=1, plan_description="ping", asset_db=asset_db, llm=fake_llm
    )
    assert fake_llm.chat.call_count == 0
    assert res["steps"]


# ===== 7. 测试 Agent（modules/ai）完全不受影响 =====


def test_test_agent_chat_unaffected_when_ai_assist_disabled(tmp_path):
    import insight_aitest.modules.ai.backend.deps as ai_deps
    import insight_aitest.modules.ai.backend.persistence.database as ai_db_mod
    import insight_aitest.platform.services.kb.deps as kb_deps
    from insight_aitest.modules.ai.backend.agent.rag import StreamEvent
    from insight_aitest.modules.ai.backend.deps import get_agent
    from insight_aitest.modules.ai.backend.routes import router as ai_router

    cfg = kb_deps.get_llm_config()
    cfg.db_path = str(tmp_path / "kb.db")
    cfg.docs_dir = str(tmp_path / "docs")
    ai_deps._db = ai_db_mod.AIDatabase(str(tmp_path / "ai.db"))

    async def fake_stream(*a, **kw):
        yield StreamEvent(type="citations", data=[])
        yield StreamEvent(type="token", data="Agent正常响应")
        yield StreamEvent(type="done", data=None)

    fake_agent = MagicMock()
    fake_agent.stream_answer_async = fake_stream

    _set_assist_enabled(False)

    app = FastAPI()
    app.include_router(ai_router, prefix="/api/modules/ai")
    app.dependency_overrides[get_agent] = lambda: fake_agent
    c = TestClient(app)

    conv_id = c.post("/api/modules/ai/conversations", json={}).json()["id"]
    with c.stream(
        "POST",
        "/api/modules/ai/chat/stream",
        json={"conversation_id": conv_id, "query": "帮我写一条接口用例"},
    ) as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "Agent正常响应" in body
