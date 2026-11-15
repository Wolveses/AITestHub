# -*- coding: utf-8 -*-
"""本地 Agent 编写的契约校验与入库状态机测试。"""

import asyncio
import inspect
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from insight_aitest.modules.ui.backend.automation import authoring_service as svc
from insight_aitest.modules.ui.backend.automation import (
    contract,
    example_service,
    lessons,
    paths,
    prompt_builder,
)
from insight_aitest.modules.ui.backend.automation.database import UIAutomationDatabase
from insight_aitest.modules.ui.backend.automation.models import AuthoringStage, CaseStatus

GOOD_CASE = '''# -*- coding: utf-8 -*-
from playwright.sync_api import expect

from insight_aitest.modules.ui.backend.automation.env import base_url


def test_login_page(page):
    print("[步骤] 打开登录页")
    page.goto(base_url() + "/login")
    print("[操作] 检查登录按钮可见")
    button = page.get_by_role("button", name="登录")
    expect(button).to_be_visible()
    print("[断言] 登录按钮可见，预期可见")
'''

GOOD_ASSET = '''# -*- coding: utf-8 -*-
def open_login(page):
    page.goto("/login")
'''


@pytest.fixture()
def db(tmp_path):
    return UIAutomationDatabase(str(tmp_path / "ui.db"))


@pytest.fixture()
def case(db):
    case_id = db.create_case(
        project_id=1,
        kb_document_id=101,
        title="登录页展示",
        precondition="",
        steps=["打开登录页", "确认登录按钮可见"],
        expected="登录按钮可见",
        site="frontend",
    )
    return db.get_case(case_id)


def _files():
    return [
        {"path": "case.py", "content": GOOD_CASE},
        {"path": "pages/login_page.py", "content": GOOD_ASSET},
    ]


def test_normalize_files_rejects_bad_path():
    files, problems = contract.normalize_files(
        [{"path": "case.py", "content": "x"}, {"path": "views/a.py", "content": "x"}]
    )
    assert "case.py" in files
    assert problems and problems[0]["code"] == "BAD_PATH"


def test_lint_detects_hardcode_and_token():
    source = GOOD_CASE.replace(
        'page.goto(base_url() + "/login")',
        'page.goto("https://prod.example.com/login")  # Bearer abcdefghijklmnopqrstuvwxyz',
    )
    problems = contract.lint_files({"case.py": source}, 1)
    codes = {p["code"] for p in problems}
    assert "HARDCODE_HOST" in codes
    assert "TOKEN_IN_SOURCE" in codes


def test_lint_accepts_minimal_case():
    files, _ = contract.normalize_files(_files())
    assert contract.lint_files(files, 1) == []


def test_lint_allows_future_annotations():
    files = {"case.py": "from __future__ import annotations\n" + GOOD_CASE}
    assert contract.lint_files(files, 1) == []


def test_lint_requires_execution_logs():
    """本地 Agent 常漏 print：无日志直接拒绝，日志过少/缺前缀给出明确错误码。"""
    no_log = '''from playwright.sync_api import expect
from insight_aitest.modules.ui.backend.automation.env import base_url

def test_x(page):
    page.goto(base_url() + "/login")
    expect(page.get_by_role("button", name="登录")).to_be_visible()
'''
    codes = [v["code"] for v in contract.lint_files({"case.py": no_log}, 1)]
    assert "LOG_MISSING" in codes

    one_log = '''from playwright.sync_api import expect
from insight_aitest.modules.ui.backend.automation.env import base_url

def test_x(page):
    print("打开登录页")
    page.goto(base_url() + "/login")
    expect(page.get_by_role("button", name="登录")).to_be_visible()
'''
    codes = [v["code"] for v in contract.lint_files({"case.py": one_log}, 1)]
    assert "LOG_TOO_FEW" in codes
    assert "LOG_FORMAT_PREFIX" in codes


def test_agent_first_contact_marks_generating(monkeypatch, tmp_path, db, case):
    """Agent 首次调用 contract.get 后，用例进入「生成中」，且重复调用幂等。"""
    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    svc.mark_generating(db, case)
    assert db.get_authoring_state(case.id).stage == "generating"
    svc.mark_generating(db, case)
    assert db.get_authoring_state(case.id).stage == "generating"


def test_waiting_agent_counted_before_validate(db, case):
    """点了「本地 Agent 编写」但还没 validate 时，应能在进行中列表看到（stage=waiting）。"""
    db.add_authoring_event(case.id, 1, "prompt_ready", "已生成本地编写文案")
    rows = db.list_prompt_ready_cases(1, since=datetime.now() - timedelta(hours=6))
    assert [c.id for c, _ in rows] == [case.id]
    # 超出窗口则不返回
    assert db.list_prompt_ready_cases(1, since=datetime.now() + timedelta(minutes=1)) == []


def test_case_can_reuse_existing_asset(monkeypatch, tmp_path, db, case):
    """存量 common 资产（含 future import）可直接复用，无需随 case.py 一起提交。"""
    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    (paths.common_dir(1) / "ui.py").write_text(
        "from __future__ import annotations\n\ndef dialog_of(page):\n    return page\n",
        encoding="utf-8",
    )
    source = (
        "from __future__ import annotations\n"
        "from common.ui import dialog_of\n" + GOOD_CASE
    )
    assert contract.lint_files({"case.py": source}, 1) == []


def test_case_rev_changes_with_steps(db, case):
    before = contract.case_rev(case)
    db.update_case(case.id, steps=["改过的步骤"])
    assert contract.case_rev(db.get_case(case.id)) != before


def test_submit_happy_path(monkeypatch, tmp_path, db, case):
    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    monkeypatch.setattr(contract, "collect_only", lambda *a, **k: None)
    files = _files()

    result = svc.validate(db, case, files)
    assert result["ok"], result
    digest = result["source_hash"]

    # 跳过真实浏览器，直接把状态推进到 DRY_RUN_OK
    db.upsert_authoring_state(
        case.id,
        project_id=1,
        source_hash=digest,
        stage=AuthoringStage.DRY_RUN_OK,
        dry_run_at=datetime.now(),
    )

    submitted = svc.submit(
        db,
        db.get_case(case.id),
        files,
        digest,
        expect_case_rev=contract.case_rev(case),
        expect_script_version=0,
    )
    assert submitted["ok"], submitted
    assert submitted["script_version"] == 1
    assert submitted["assets_written"][0]["action"] == "created"

    saved = db.get_case(case.id)
    assert saved.status == CaseStatus.IMPLEMENTED
    assert saved.source == "local_agent"
    assert saved.script_version == 1
    assert (tmp_path / "ws").joinpath(saved.script_rel_path).is_file()


def test_submit_rejects_stale_case(monkeypatch, tmp_path, db, case):
    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    monkeypatch.setattr(contract, "collect_only", lambda *a, **k: None)
    files = _files()
    digest = svc.validate(db, case, files)["source_hash"]
    db.upsert_authoring_state(
        case.id, source_hash=digest, stage=AuthoringStage.DRY_RUN_OK, dry_run_at=datetime.now()
    )
    db.update_case(case.id, steps=["用例被改过了"])
    result = svc.submit(
        db,
        db.get_case(case.id),
        files,
        digest,
        expect_case_rev="stale-rev",
        expect_script_version=0,
    )
    assert result["ok"] is False
    assert result["code"] == "STALE_CASE"


def test_submit_requires_dry_run(db, case):
    files, _ = contract.normalize_files(_files())
    digest = contract.source_hash(files)
    result = svc.submit(
        db,
        db.get_case(case.id),
        _files(),
        digest,
        expect_case_rev=contract.case_rev(case),
        expect_script_version=0,
    )
    assert result["ok"] is False
    assert result["code"] == "DRY_RUN_REQUIRED"
    assert result["retryable"] is True
    assert result["required_next"] == "ui.script.dry_run"


def test_asset_conflict_requires_force(monkeypatch, tmp_path, db, case):
    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    monkeypatch.setattr(contract, "collect_only", lambda *a, **k: None)
    files = _files()
    digest = svc.validate(db, case, files)["source_hash"]
    db.upsert_authoring_state(
        case.id, source_hash=digest, stage=AuthoringStage.DRY_RUN_OK, dry_run_at=datetime.now()
    )
    first = svc.submit(
        db, db.get_case(case.id), files, digest, contract.case_rev(case), 0
    )
    assert first["ok"]

    # 同一资产内容不同的第二次提交：未开 force 应冲突
    changed = [
        {"path": "case.py", "content": GOOD_CASE},
        {"path": "pages/login_page.py", "content": GOOD_ASSET + "\n# changed\n"},
    ]
    changed_hash = contract.source_hash(contract.normalize_files(changed)[0])
    db.upsert_authoring_state(
        case.id,
        source_hash=changed_hash,
        stage=AuthoringStage.DRY_RUN_OK,
        dry_run_at=datetime.now(),
    )
    conflict = svc.submit(
        db, db.get_case(case.id), changed, changed_hash, contract.case_rev(case), 1
    )
    assert conflict["ok"] is False
    assert conflict["code"] == "ASSET_CONFLICT"

    forced = svc.submit(
        db,
        db.get_case(case.id),
        changed,
        changed_hash,
        contract.case_rev(case),
        1,
        force_assets=True,
    )
    assert forced["ok"], forced
    assert forced["assets_written"][0]["action"] == "overwritten"


def test_lease_blocks_other_owner(db, case):
    assert svc.acquire_lease(db, case, "token:1") is True
    assert svc.acquire_lease(db, case, "token:2") is False
    assert svc.acquire_lease(db, case, "token:1") is True
    svc.release_lease(db, case)
    assert svc.acquire_lease(db, case, "token:2") is True


# ===== example.get：范例库 / 错题库 =====


def test_example_payload_without_history(db, case):
    payload = example_service.build_example_payload(case, db)
    assert payload["hard_rules"]
    assert payload["examples"] == []
    assert payload["template"].startswith("from playwright.sync_api import expect")
    # 前端用例不应收到仅适用于后台的坑
    assert payload["known_traps"]
    assert all(t["site"] == "any" for t in payload["known_traps"])
    assert payload["stats"]["examples"] == 0


def test_example_redacts_lessons(db, case):
    lessons.record_failure(
        db,
        case,
        "script",
        "SELECTOR_NOT_FOUND: admin@example.com 13812345678 Bearer abcdef https://10.1.2.3:8000/login",
    )
    payload = example_service.build_example_payload(case, db)
    assert payload["lessons"], payload
    body = payload["lessons"][0]["content"]
    for leaked in ("admin@example.com", "13812345678", "abcdef", "10.1.2.3"):
        assert leaked not in body
    assert payload["lessons"][0]["hits"] >= 1


def test_example_collects_snippets_routes_and_assets(monkeypatch, tmp_path, db, case):
    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    other_id = db.create_case(
        project_id=1,
        kb_document_id=102,
        title="登录页提交",
        precondition="",
        steps=["打开登录页", "点击登录"],
        expected="登录成功",
        site="frontend",
    )
    script = paths.case_script(1, other_id)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "def test_submit(page):\n"
        '    page.goto(base_url() + "/#/usm/users")\n'
        '    page.get_by_role("button", name="登录").click()\n'
        "    expect(page.get_by_text(\"成功\")).to_be_visible()\n",
        encoding="utf-8",
    )
    db.update_case(
        other_id, status=CaseStatus.IMPLEMENTED, script_rel_path=paths.to_rel(script)
    )
    pages = paths.pages_dir(1) / "users_page.py"
    pages.write_text(
        'class UsersPage:\n    """用户管理页"""\n\n    def open(self, page, dept=None):\n        page.goto("/")\n',
        encoding="utf-8",
    )

    payload = example_service.build_example_payload(case, db)
    assert payload["examples"], payload
    assert payload["examples"][0]["source_case_id"] == other_id
    assert payload["known_routes"][0] == "/#/usm/users"
    assert payload["assets"][0]["path"] == "pages/users_page.py"
    method = payload["assets"][0]["classes"][0]["methods"][0]
    assert method["name"] == "open"
    assert "dept" in method["sig"]
    assert "page.goto" not in str(method)  # 只给签名，不给实现


def test_example_budget_trims(monkeypatch, tmp_path, db, case):
    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    monkeypatch.setattr(example_service, "TOTAL_CHAR_LIMIT", 1200)
    for index in range(6):
        lessons.record_failure(db, case, "script", f"错误 {index} " + "x" * 400)

    payload = example_service.build_example_payload(case, db)
    assert payload["stats"]["truncated"] is True
    assert len(payload["lessons"]) <= example_service.MAX_LESSONS


def test_dry_run_failure_records_lesson(monkeypatch, tmp_path, db, case):
    from types import SimpleNamespace

    from insight_aitest.modules.ui.backend.automation import runner

    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    monkeypatch.setattr(contract, "collect_only", lambda *a, **k: None)
    monkeypatch.setattr(
        svc,
        "resolve_current_env",
        lambda *a, **k: SimpleNamespace(
            id=1, name="测试环境", base_url="http://127.0.0.1", allow_local_agent=1
        ),
    )
    monkeypatch.setattr(
        runner,
        "run_script",
        lambda *a, **k: {
            "status": "failed",
            "error_message": "Timeout 30000ms exceeded",
            "duration_ms": 12,
        },
    )
    files = _files()
    digest = svc.validate(db, case, files)["source_hash"]
    result = svc.dry_run(db, case, files, digest)
    assert result["ok"] is False
    assert result["code"] == "TIMEOUT"

    entries = db.list_lessons(1)
    assert entries
    assert any("TIMEOUT" in entry.content for entry in entries)


def test_submit_records_solution_after_failure(monkeypatch, tmp_path, db, case):
    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    monkeypatch.setattr(contract, "collect_only", lambda *a, **k: None)
    files = _files()
    digest = svc.validate(db, case, files)["source_hash"]

    db.add_authoring_event(case.id, 1, "dry_run_failed", "Timeout 30000ms exceeded")
    db.add_authoring_event(case.id, 1, "dry_run_passed", "试跑通过")
    db.upsert_authoring_state(
        case.id, source_hash=digest, stage=AuthoringStage.DRY_RUN_OK, dry_run_at=datetime.now()
    )
    submitted = svc.submit(
        db, db.get_case(case.id), files, digest, contract.case_rev(case), 0
    )
    assert submitted["ok"], submitted

    titles = {entry.title for entry in db.list_lessons(1)}
    assert any("修复通过" in title for title in titles)


# ===== MCP 工具元信息 / 返回契约 =====

EXPECTED_TOOLS = [
    "ui.contract.get",
    "ui.env.get",
    "ui.case.get",
    "ui.case.triage",
    "ui.example.get",
    "ui.script.validate",
    "ui.script.dry_run",
    "ui.script.submit",
    "ui.run.latest",
]


def _tools() -> dict:
    import asyncio

    from insight_aitest.modules.ui.backend.automation.mcp_server import get_mcp_server

    return {tool.name: tool for tool in asyncio.run(get_mcp_server().list_tools())}


def test_tool_metadata_follows_conventions():
    tools = _tools()
    assert list(tools) == EXPECTED_TOOLS
    for name, tool in tools.items():
        assert tool.title, name
        assert tool.description, name
        # 流程只放 instructions / workflow，工具描述不写步骤
        assert "【第" not in tool.description, name
        assert "下一步" not in tool.description, name
        assert tool.output_schema, name
        for prop, spec in (tool.input_schema.get("properties") or {}).items():
            assert spec.get("description"), f"{name}.{prop} 缺少参数描述"

    assert tools["ui.case.get"].annotations.read_only_hint is True
    assert tools["ui.script.submit"].annotations.destructive_hint is True
    assert tools["ui.script.dry_run"].annotations.open_world_hint is True
    assert tools["ui.example.get"].annotations.open_world_hint is False


def test_prompts_and_resources_registered():
    import asyncio

    from insight_aitest.modules.ui.backend.automation.mcp_server import get_mcp_server

    server = get_mcp_server()
    assert [p.name for p in asyncio.run(server.list_prompts())] == [
        "ui.auto",
        "ui.create",
        "ui.fix",
        "ui.regenerate",
    ]
    assert [str(r.uri) for r in asyncio.run(server.list_resources())] == [
        "insight://rules",
        "insight://template",
        "insight://instructions",
    ]


def test_contract_payload_carries_workflow(case):
    payload = contract.contract_payload(case, None)
    workflow = payload["workflow"]
    assert payload["intent"] == "create"
    assert workflow["id"] == "ui.create@1"
    assert workflow["steps"][0]["tool"] == "ui.contract.get"
    assert workflow["max_retry_same_error"] == 3
    assert "flow" not in payload["rules"]


def test_contract_payload_switches_to_fix_workflow(case):
    payload = contract.contract_payload(case, None, intent="fix")
    assert payload["intent"] == "fix"
    assert payload["workflow"]["id"] == "ui.fix@1"
    assert payload["workflow"]["steps"][0]["tool"] == "ui.run.latest"


# ===== 统一入口分诊 =====


class _FakeRunsDb:
    def __init__(self, runs: dict[int, dict]):
        self._runs = runs

    def latest_script_runs(self, case_ids):
        return {k: v for k, v in self._runs.items() if k in case_ids}


def _implemented(case, version: int = 3):
    case.status = CaseStatus.IMPLEMENTED
    case.script_rel_path = f"scripts/{case.project_id}/case.py"
    case.script_version = version
    return case


def test_triage_create_when_no_script(case):
    action, reason = svc.case_action(case, None)
    assert action == "create"
    assert "无可用脚本" in reason


def test_triage_skip_and_regenerate_cases(case):
    _implemented(case)
    # 已实现且无执行记录 / 最近执行通过 → 走 regenerate（不再 skip）
    assert svc.case_action(case, None)[0] == "regenerate"
    assert svc.case_action(case, {"status": "passed"})[0] == "regenerate"
    # 执行中 / 活跃态才 skip
    assert svc.case_action(case, {"status": "running"})[0] == "skip"
    case.status = CaseStatus.RUNNING
    assert svc.case_action(case, {"status": "passed"})[0] == "skip"


def test_triage_fix_when_last_run_failed(case):
    _implemented(case)
    action, reason = svc.case_action(case, {"status": "failed", "error": "SELECTOR_NOT_FOUND: 登录按钮"})
    assert action == "fix"
    assert "SELECTOR_NOT_FOUND" in reason


def test_triage_summary_counts(db, case):
    passed_id = db.create_case(
        project_id=1, kb_document_id=102, title="已通过", precondition="",
        steps=["a"], expected="b", site="frontend",
    )
    failed_id = db.create_case(
        project_id=1, kb_document_id=103, title="待修复", precondition="",
        steps=["a"], expected="b", site="frontend",
    )
    running_id = db.create_case(
        project_id=1, kb_document_id=104, title="执行中", precondition="",
        steps=["a"], expected="b", site="frontend",
    )
    passed_case = _implemented(db.get_case(passed_id))
    failed_case = _implemented(db.get_case(failed_id))
    running_case = _implemented(db.get_case(running_id))
    case = db.get_case(case.id)  # 未实现 → create

    runs = _FakeRunsDb(
        {
            passed_id: {"status": "passed"},
            failed_id: {"status": "failed", "error": "boom"},
            running_id: {"status": "running"},
        }
    )
    result = svc.triage_cases(runs, [case, passed_case, failed_case, running_case])
    assert result["summary"] == {"create": 1, "fix": 1, "regenerate": 1, "skip": 1}
    by_id = {item["case_id"]: item for item in result["items"]}
    assert by_id[int(case.id)]["action"] == "create"
    assert by_id[passed_id]["action"] == "regenerate"
    assert by_id[passed_id]["next_tool"] == "ui.contract.get"
    assert by_id[failed_id]["action"] == "fix"
    assert by_id[failed_id]["next_tool"] == "ui.run.latest"
    assert by_id[running_id]["action"] == "skip"
    assert by_id[running_id]["next_tool"] is None


def test_fail_envelope_guides_next_tool():
    err = svc.fail("STALE_CASE", "用例已变更")
    assert err["ok"] is False
    assert err["retryable"] is True
    assert err["required_next"] == "ui.contract.get"

    conflict = svc.fail("SCRIPT_CONFLICT", "脚本版本冲突")
    assert conflict["required_next"] == "ui.contract.get"
    assert "ui.contract.get" in conflict["fix"]

    dry_run = svc.fail("DRY_RUN_REQUIRED", "尚未试跑")
    assert dry_run["retryable"] is True
    assert dry_run["required_next"] == "ui.script.dry_run"
    assert "dry_run" in dry_run["fix"]

    fatal = svc.fail("PERMISSION_DENIED", "无权限")
    assert fatal["retryable"] is False
    assert fatal["required_next"] is None


def test_error_result_marks_is_error():
    from insight_aitest.modules.ui.backend.automation.mcp_server import _error

    result = _error(svc.fail("BUSY", "该用例正被其他本地 Agent 操作"))
    assert result.is_error is True
    # 严格客户端会用成功态 outputSchema 校验 structuredContent，所以错误体只走 text
    assert result.structured_content is None
    body = result.content[0].text
    assert '"code": "BUSY"' in body
    assert '"retryable": true' in body


def test_read_only_annotations_for_contract_and_validate():
    tools = _tools()
    assert tools["ui.contract.get"].annotations.read_only_hint is True
    assert tools["ui.script.validate"].annotations.read_only_hint is True
    assert tools["ui.script.submit"].annotations.read_only_hint is False


def test_files_input_schema_is_modeled():
    tools = _tools()
    for name in ("ui.script.validate", "ui.script.dry_run", "ui.script.submit"):
        schema = tools[name].input_schema
        files = schema["properties"]["files"]
        ref = files["items"].get("$ref") or ""
        item = schema["$defs"][ref.rsplit("/", 1)[-1]] if ref else files["items"]
        assert set(item["properties"]) == {"path", "content"}, name
        assert set(item["required"]) == {"path", "content"}, name
        assert files.get("maxItems") == 20, name


def test_summary_result_keeps_payload_out_of_text():
    from insight_aitest.modules.ui.backend.automation.mcp_server import _result

    payload = {"ok": True, "blob": "x" * 5000}
    result = _result("【摘要】ok", payload)
    assert result.is_error is False
    assert result.structured_content["blob"] == "x" * 5000
    assert len(result.content[0].text) < 200


# ===== v4：文案精简 / MCP 协议降级兜底 =====


class _FakeRequest:
    """最小 Request 替身：只覆盖 _client_base 与 create_prompt 用到的属性。"""

    def __init__(self, base_url: str = "http://127.0.0.1:8001/api/", headers: dict | None = None):
        self.base_url = base_url
        self.headers = headers or {}


@pytest.fixture()
def mcp_srv(monkeypatch, tmp_path, db):
    """进程内 MCP 上下文：项目 1 / owner token:1 / fixture DB / 临时工作区。"""
    from insight_aitest.modules.ui.backend.automation import mcp_server

    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    monkeypatch.setattr(mcp_server, "get_automation_db", lambda: db)
    monkeypatch.setattr(mcp_server, "resolve_current_env", lambda *a, **k: None)
    project_reset = mcp_server._current_project.set(1)
    owner_reset = mcp_server._current_owner.set("token:1")
    try:
        yield mcp_server
    finally:
        mcp_server._current_owner.reset(owner_reset)
        mcp_server._current_project.reset(project_reset)


def _call(server, name: str, arguments: dict):
    return asyncio.run(server.call_tool(name, arguments))


def _prompt_text(server, name: str, arguments: dict) -> str:
    result = asyncio.run(server.get_prompt(name, arguments))
    return result.messages[0].content.text


def _exc_chain_text(exc: BaseException) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        parts.append(str(current))
        current = current.__cause__
    return " | ".join(parts)


def test_prompt_builder_rest_variants():
    texts = [
        prompt_builder.render_auto_prompt([1, 2], "ins_tok", "http://192.168.1.20:8001/mcp"),
        prompt_builder.render_create_prompt([1, 2], "ins_tok", "http://192.168.1.20:8001/mcp"),
        prompt_builder.render_fix_prompt([1, 2], "ins_tok", "http://192.168.1.20:8001/mcp"),
    ]
    for text in texts:
        assert "- case_ids: 1,2" in text
        assert "- Authorization: Bearer ins_tok" in text
        assert len(text.splitlines()) <= 5
        assert "【前置检查】" not in text
        assert "【处理顺序】" not in text
        assert "```" not in text


def test_prompt_builder_native_no_fake_token():
    text = prompt_builder.render_auto_prompt([1])
    assert "Bearer" not in text
    assert "沿用当前 MCP 会话（无需额外 Token）" in text
    assert "MCP:" not in text


def test_prompt_builder_dedup_and_batch_hint():
    assert prompt_builder.parse_case_ids("1,1,abc,2") == [1, 2]
    text = prompt_builder.render_auto_prompt(range(1, 52))
    assert "- triage 分批: 每批最多 50 个" in text


def test_mcp_auto_prompt_registered_and_small():
    from insight_aitest.modules.ui.backend.automation.mcp_server import get_mcp_server

    server = get_mcp_server()
    text = _prompt_text(server, "ui.auto", {"case_ids": "1,2"})
    assert "ui.case.triage" in text
    assert len(text) < 1500
    with pytest.raises(Exception) as exc:
        _prompt_text(server, "ui.auto", {"case_ids": "abc"})
    assert "case_ids" in _exc_chain_text(exc.value)


def test_mcp_create_prompt_no_cross_layer_import():
    from insight_aitest.modules.ui.backend.automation import mcp_server

    source = inspect.getsource(mcp_server)
    assert "routes.authoring" not in source
    text = _prompt_text(mcp_server.get_mcp_server(), "ui.create", {"case_ids": "1,2"})
    assert "ui.create workflow" in text
    assert "【前置检查】" not in text
    assert len(text) < 1500


def test_mcp_fix_prompt_no_inline_script_or_log(db, case, mcp_srv):
    text = _prompt_text(mcp_srv.get_mcp_server(), "ui.fix", {"case_id": str(case.id)})
    assert "ui.run.latest" in text
    assert "【现有脚本】" not in text
    assert "```python" not in text
    assert len(text) < 1500

    with pytest.raises(Exception) as exc:
        _prompt_text(mcp_srv.get_mcp_server(), "ui.fix", {"case_id": "99999"})
    assert "CASE_NOT_FOUND" in _exc_chain_text(exc.value)


def test_instructions_and_resource_are_identical():
    from insight_aitest.modules.ui.backend.automation import mcp_server

    server = mcp_server.get_mcp_server()
    text = asyncio.run(server.read_resource("insight://instructions"))[0].content
    assert text == mcp_server.INSTRUCTIONS
    for keyword in (
        "Playwright",
        "ui.case.triage",
        "DRY_RUN_REQUIRED",
        "insight://rules",
        "insight://template",
        "CASE_NOT_FOUND",
    ):
        assert keyword in text


def test_contract_summary_has_dynamic_workflow(db, case, mcp_srv):
    result = _call(mcp_srv.get_mcp_server(), "ui.contract.get", {"case_id": int(case.id)})
    assert result.is_error is False
    text = result.content[0].text
    assert "ui.create@1:" in text
    assert "ui.script.validate → ui.script.dry_run → ui.script.submit" in text
    assert "ui.example.get?" in text
    assert "硬规则：" in text
    assert "完整 rules / env / assets / workflow 见 structuredContent" not in text


def test_contract_assets_metadata_by_default(monkeypatch, tmp_path, case):
    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    (paths.pages_dir(1) / "login_page.py").write_text(
        "def open_login(page):\n    pass\n", encoding="utf-8"
    )
    payload = contract.contract_payload(case, None)
    assert payload["assets"]
    assert all("content" not in item for item in payload["assets"])
    assert all({"path", "sha256", "size"} <= set(item) for item in payload["assets"])

    with_content = contract.contract_payload(case, None, include_assets_content=True)
    assert all("content" in item for item in with_content["assets"])


def test_contract_rules_pruned_and_resource_full(case):
    from insight_aitest.modules.ui.backend.automation.mcp_server import get_mcp_server

    assert "error_codes" in contract.contract_rules()
    payload = contract.contract_payload(case, None)
    assert "error_codes" not in payload["rules"]
    assert payload["rules"]["digest"]

    rules_text = asyncio.run(get_mcp_server().read_resource("insight://rules"))[0].content
    rules = json.loads(rules_text)
    assert {"error_codes", "hard_rules", "known_traps", "digest"} <= set(rules)


def test_contract_case_includes_params_and_status(case):
    payload = contract.contract_payload(case, None)
    assert {"params", "category_path", "status"} <= set(payload["case"])
    assert isinstance(payload["case"]["params"], dict)


def test_case_get_omits_script_content_by_default(db, case, mcp_srv):
    server = mcp_srv.get_mcp_server()
    default = _call(server, "ui.case.get", {"case_id": int(case.id)})
    assert default.is_error is False
    assert "content" not in default.structured_content["script"]

    full = _call(server, "ui.case.get", {"case_id": int(case.id), "include_script_content": True})
    assert "content" in full.structured_content["script"]


def test_env_get_failure_is_error(monkeypatch, db, case, mcp_srv):
    monkeypatch.setattr(
        svc, "env_payload", lambda _db, _case: svc.fail("ENV_NOT_CONFIGURED", "项目未配置环境")
    )
    result = _call(mcp_srv.get_mcp_server(), "ui.env.get", {"case_id": int(case.id)})
    assert result.is_error is True
    assert result.structured_content is None
    assert '"code": "ENV_NOT_CONFIGURED"' in result.content[0].text


def test_case_triage_reports_missing_and_next_tool(monkeypatch, db, mcp_srv):
    ids = [
        db.create_case(
            project_id=1,
            kb_document_id=2000 + index,
            title=f"用例 {index}",
            precondition="",
            steps=["a"],
            expected="b",
            site="frontend",
        )
        for index in range(25)
    ]
    for cid in ids[22:]:
        db.update_case(
            cid,
            status=CaseStatus.IMPLEMENTED,
            script_rel_path="scripts/1/case.py",
            script_version=2,
        )
    monkeypatch.setattr(
        db,
        "latest_script_runs",
        lambda _ids: {
            ids[22]: {"status": "running"},
            ids[23]: {"status": "failed", "error": "SELECTOR_NOT_FOUND: 登录按钮"},
            ids[24]: {"status": "passed"},
        },
    )

    result = _call(mcp_srv.get_mcp_server(), "ui.case.triage", {"case_ids": ids + [999999]})
    assert result.is_error is False
    data = result.structured_content
    assert data["missing_case_ids"] == [999999]
    assert data["summary"] == {"create": 22, "fix": 1, "regenerate": 1, "skip": 1}

    text = result.content[0].text
    assert "→ ui.contract.get" in text
    assert "→ ui.run.latest" in text
    assert f"- {ids[22]} skip（" in text
    assert f"- {ids[24]} regenerate → ui.contract.get（" in text
    assert "None" not in text
    item_lines = [
        line for line in text.splitlines() if line.startswith("- ") and "missing_case_ids:" not in line
    ]
    assert len(item_lines) == 25
    assert "- missing_case_ids: 999999" in text


def test_case_triage_dedup(db, mcp_srv):
    cid = db.create_case(
        project_id=1,
        kb_document_id=3001,
        title="重复勾选",
        precondition="",
        steps=["a"],
        expected="b",
        site="frontend",
    )
    result = _call(mcp_srv.get_mcp_server(), "ui.case.triage", {"case_ids": [cid, cid]})
    data = result.structured_content
    assert data["missing_case_ids"] == []
    assert data["summary"]["create"] == 1
    assert len(data["items"]) == 1
    assert result.content[0].text.count(f"- {cid} ") == 1


def test_workflow_contract_consistency():
    for workflow in (
        contract.WORKFLOW_CREATE,
        contract.WORKFLOW_FIX,
        contract.WORKFLOW_REGENERATE,
    ):
        assert workflow["compatible"] == "additive"
        assert set(workflow["stop_on"]) == contract.SESSION_FATAL_CODES
        assert set(workflow["skip_case_on"]) == contract.CASE_FATAL_CODES
        assert "ui.script.dry_run" in workflow["resume"]["on_conflict"]
        assert "ui.contract.get" in workflow["resume"]["on_conflict"]
        assert "ui.contract.get" in workflow["resume"]["on_stale"]
    assert "CASE_NOT_FOUND" not in contract.WORKFLOW_CREATE["stop_on"]
    assert len(contract.WORKFLOW_FIX["constraints"]) == 3

    regenerate = contract.WORKFLOW_REGENERATE
    assert regenerate["id"] == "ui.regenerate@1"
    assert regenerate["steps"][0]["tool"] == "ui.contract.get"
    case_get = next(step for step in regenerate["steps"] if step["tool"] == "ui.case.get")
    assert case_get["required"] is True
    required_tools = {step["tool"] for step in regenerate["steps"] if step.get("required")}
    assert "ui.run.latest" not in required_tools
    assert len(regenerate["constraints"]) == 5


def test_tool_output_schemas_declare_stable_fields():
    tools = _tools()
    assert {"params", "category_path", "status", "script"} <= set(
        tools["ui.case.get"].output_schema["properties"]
    )
    assert "usage" in tools["ui.env.get"].output_schema["properties"]
    assert "assets_written" in tools["ui.script.submit"].output_schema["properties"]
    assert "files" in tools["ui.script.validate"].output_schema["properties"]
    assert "stats" in tools["ui.example.get"].output_schema["properties"]


def test_example_summary_contains_resource_pointers(db, case, mcp_srv):
    result = _call(mcp_srv.get_mcp_server(), "ui.example.get", {"case_id": int(case.id)})
    text = result.content[0].text
    assert "insight://rules" in text
    assert "insight://template" in text
    assert "truncated=" in text


def test_run_latest_no_run_points_to_contract(db, case, mcp_srv):
    result = _call(mcp_srv.get_mcp_server(), "ui.run.latest", {"case_id": int(case.id)})
    text = result.content[0].text
    assert "无执行记录" in text
    assert "ui.contract.get" in text
    assert "intent" in text


# ===== REST 入口：文案 / mode 校验 / 不产生孤儿 Token =====


def _rest_routes(monkeypatch, db):
    from insight_aitest.modules.ui.backend.automation.routes import authoring as routes

    monkeypatch.setattr(routes, "get_automation_db", lambda: db)
    monkeypatch.setattr(routes, "project_name", lambda pid: f"项目 {pid}")
    return routes


def test_rest_mode_validation_no_orphan_token(monkeypatch):
    from fastapi import HTTPException

    from insight_aitest.modules.ui.backend.automation.routes import authoring as routes

    created: list = []
    monkeypatch.setattr(routes.mcp_tokens, "create_token", lambda *a, **k: created.append(1))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            routes.create_prompt(_FakeRequest(), {"project_id": 1, "case_ids": [1], "mode": "bogus"})
        )
    assert exc.value.status_code == 400
    assert created == []


def test_rest_auto_all_skip_no_token(monkeypatch, db, case):
    db.update_case(
        case.id, status=CaseStatus.RUNNING, script_rel_path="scripts/1/case.py", script_version=1
    )
    routes = _rest_routes(monkeypatch, db)

    def _unexpected(*_a, **_k):
        raise AssertionError("全部 skip 时不应创建 Token")

    monkeypatch.setattr(routes.mcp_tokens, "create_token", _unexpected)
    result = asyncio.run(
        routes.create_prompt(_FakeRequest(), {"project_id": 1, "case_ids": [int(case.id)]})
    )
    assert result["prompt"] is None
    assert result["token"] is None
    assert result["action_required"] == 0
    assert result["summary"]["skip"] == 1


def test_rest_create_and_fix_prompt(monkeypatch, db, case):
    routes = _rest_routes(monkeypatch, db)
    created: list[int] = []
    row = SimpleNamespace(id=7, expires_at=None)

    def _fake_create_token(project_id, name=""):
        created.append(project_id)
        return "ins_tok", row

    monkeypatch.setattr(routes.mcp_tokens, "create_token", _fake_create_token)

    create_result = asyncio.run(
        routes.create_prompt(
            _FakeRequest(), {"project_id": 1, "case_ids": [int(case.id)], "mode": "create"}
        )
    )
    assert create_result["mode"] == "create"
    assert "为下列用例编写脚本并入库" in create_result["prompt"]
    assert "Bearer ins_tok" in create_result["prompt"]
    assert f"- case_ids: {int(case.id)}" in create_result["prompt"]

    fix_result = asyncio.run(
        routes.create_prompt(
            _FakeRequest(), {"project_id": 1, "case_ids": [int(case.id)], "mode": "fix"}
        )
    )
    assert fix_result["mode"] == "fix"
    assert "修复下列用例并重新入库" in fix_result["prompt"]
    assert created == [1, 1]


def test_client_base_forwarded_and_origin():
    from insight_aitest.modules.ui.backend.automation.routes.authoring import _client_base

    forwarded = _FakeRequest(
        headers={"x-forwarded-host": "192.168.1.20:8001", "x-forwarded-proto": "http"}
    )
    assert _client_base(forwarded) == "http://192.168.1.20:8001"

    origin = _FakeRequest(headers={"origin": "http://192.168.1.20:3000"})
    assert _client_base(origin) == "http://192.168.1.20:8001"


# ===== regenerate：分诊 / workflow / 会话记录（ui_generations）=====


def test_triage_regenerate_mode(case):
    _implemented(case)
    assert svc.case_action(case, {"status": "passed"}, mode="regenerate")[0] == "regenerate"
    assert svc.case_action(case, {"status": "failed", "error": "x"}, mode="regenerate")[0] == "regenerate"
    assert svc.case_action(case, None, mode="regenerate")[0] == "regenerate"
    assert svc.case_action(case, {"status": "running"}, mode="regenerate")[0] == "skip"

    blank = SimpleNamespace(
        id=99, project_id=1, status=CaseStatus.NOT_IMPLEMENTED, script_rel_path="", script_version=0
    )
    assert svc.case_action(blank, None, mode="regenerate")[0] == "create"

    # 活跃态在 auto 下也硬跳过（修正「GENERATING+无脚本 → create」的抢写风险）
    active = SimpleNamespace(
        id=100, project_id=1, status=CaseStatus.GENERATING, script_rel_path="", script_version=0
    )
    assert svc.case_action(active, None)[0] == "skip"


def test_triage_cases_regenerate_summary_and_mode_echo(case):
    _implemented(case)
    result = svc.triage_cases(_FakeRunsDb({int(case.id): {"status": "passed"}}), [case], mode="regenerate")
    assert result["summary"] == {"create": 0, "fix": 0, "regenerate": 1, "skip": 0}
    assert result["items"][0]["mode"] == "regenerate"
    assert result["items"][0]["next_tool"] == "ui.contract.get"


def test_case_intent_regenerate_and_scripted_skip(db, case):
    implemented = _implemented(db.get_case(case.id))
    # 有脚本且无失败记录：auto 也返回 regenerate（不再假装从零创建）
    assert svc.case_intent(_FakeRunsDb({}), implemented) == "regenerate"
    assert svc.case_intent(_FakeRunsDb({}), implemented, mode="regenerate") == "regenerate"
    # 最近失败 → fix
    failed = _FakeRunsDb({int(implemented.id): {"status": "failed", "error": "boom"}})
    assert svc.case_intent(failed, implemented) == "fix"
    # 无脚本 → create
    assert svc.case_intent(_FakeRunsDb({}), case) == "create"


def test_contract_payload_regenerate_workflow(case):
    payload = contract.contract_payload(case, None, intent="regenerate")
    assert payload["intent"] == "regenerate"
    workflow = payload["workflow"]
    assert workflow["id"] == "ui.regenerate@1"
    required = {step["tool"] for step in workflow["steps"] if step.get("required")}
    assert {"ui.contract.get", "ui.case.get", "ui.script.validate", "ui.script.dry_run", "ui.script.submit"} <= required
    assert "ui.run.latest" not in required
    assert len(workflow["constraints"]) == 5


def _implemented_scripted(db, case, version: int = 1):
    db.update_case(
        case.id,
        status=CaseStatus.IMPLEMENTED,
        script_rel_path="scripts/1/case.py",
        script_version=version,
    )
    return db.get_case(case.id)


def test_local_agent_generation_session_lifecycle(monkeypatch, tmp_path, db, case):
    from types import SimpleNamespace as NS

    from insight_aitest.modules.ui.backend.automation import runner

    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    monkeypatch.setattr(contract, "collect_only", lambda *a, **k: None)
    scripted = _implemented_scripted(db, case)

    gen_id = svc.mark_generating(db, scripted, mode="regenerate")
    assert gen_id
    gen = db.get_generation(gen_id)
    assert gen.kind == "regenerate"
    assert gen.attempt == 1
    assert gen.model == "local_agent"
    assert gen.status == "running"
    assert gen.log_rel_path
    assert gen.started_at is not None
    assert db.count_generations(int(case.id)) == 1

    files = _files()
    assert svc.validate(db, scripted, files)["ok"]
    gen = db.get_generation(gen_id)
    assert gen.status == "running"
    assert gen.error_message is None
    assert gen.tool_calls >= 2

    monkeypatch.setattr(
        svc,
        "resolve_current_env",
        lambda *a, **k: NS(id=1, name="测试环境", base_url="http://127.0.0.1", allow_local_agent=1),
    )
    monkeypatch.setattr(
        runner,
        "run_script",
        lambda *a, **k: {"status": "failed", "error_message": "SELECTOR_NOT_FOUND: 登录按钮", "duration_ms": 12},
    )
    svc._dry_run_last.pop(int(case.id), None)
    failed = svc.dry_run(db, scripted, files, contract.source_hash(contract.normalize_files(files)[0]))
    assert failed["ok"] is False
    gen = db.get_generation(gen_id)
    assert gen.status == "running"
    assert gen.fix_rounds == 1
    assert "SELECTOR_NOT_FOUND" in (gen.error_message or "")

    # 直接推进到 DRY_RUN_OK，验证 submit 成功后会话收尾
    digest = contract.source_hash(contract.normalize_files(files)[0])
    db.upsert_authoring_state(
        int(case.id), source_hash=digest, stage=AuthoringStage.DRY_RUN_OK, dry_run_at=datetime.now()
    )
    submitted = svc.submit(
        db, db.get_case(case.id), files, digest, contract.case_rev(scripted), 1
    )
    assert submitted["ok"], submitted
    gen = db.get_generation(gen_id)
    assert gen.status == "success"
    assert gen.finished_at is not None
    assert gen.error_category is None and gen.error_message is None
    assert db.get_authoring_state(int(case.id)).generation_id is None
    # 下一次接入重新建行
    nxt = svc.mark_generating(db, db.get_case(case.id))
    assert nxt and nxt != gen_id


def test_local_agent_generation_reuses_single_row(monkeypatch, tmp_path, db, case):
    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    first = svc.mark_generating(db, case)
    second = svc.mark_generating(db, case)
    assert first == second
    assert db.count_generations(int(case.id)) == 1


def test_local_agent_generation_stale_sweep(monkeypatch, tmp_path, db, case):
    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    gen_id = svc.mark_generating(db, case)
    monkeypatch.setattr(svc, "GENERATION_TTL", timedelta(seconds=-1))
    assert svc.sweep_stale_generation(db, case) is True
    gen = db.get_generation(gen_id)
    assert gen.status == "failed"
    assert "超时" in (gen.error_message or "")
    assert db.get_authoring_state(int(case.id)).generation_id is None


def test_local_agent_generation_log_readable():
    from insight_aitest.modules.ui.backend.automation.routes.cases import _format_generation_log

    events = [
        {"type": "session", "kind": "regenerate", "mode": "regenerate"},
        {"type": "agent", "tool": "ui.case.get", "ok": True},
        {"type": "validate", "status": "failed", "message": "LOG_TOO_FEW"},
        {"type": "validate", "status": "passed", "message": "静态校验通过"},
        {"type": "dry_run", "status": "failed", "duration_ms": 18, "message": "SELECTOR_NOT_FOUND"},
        {"type": "submit", "status": "success", "script_version": 4},
        {"type": "session_end", "status": "success", "message": "脚本已入库 v4"},
    ]
    text = "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\nnot-json-line"
    out = _format_generation_log(text, 200_000)
    assert "not-json-line" in out
    assert "[会话] 本地 Agent 开始编写 · kind=regenerate mode=regenerate" in out
    assert "[调用] ui.case.get" in out
    assert "[校验] 失败：LOG_TOO_FEW" in out
    assert "[校验] 通过：静态校验通过" in out
    assert "[试跑] 失败（18ms）：SELECTOR_NOT_FOUND" in out
    assert "[入库] 脚本已入库 v4" in out
    assert "[会话结束] success：脚本已入库 v4" in out


def test_local_agent_generation_screenshot_copied(monkeypatch, tmp_path, db, case):
    from types import SimpleNamespace as NS

    from insight_aitest.modules.ui.backend.automation import runner

    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    monkeypatch.setattr(contract, "collect_only", lambda *a, **k: None)
    monkeypatch.setattr(
        svc,
        "resolve_current_env",
        lambda *a, **k: NS(id=1, name="测试环境", base_url="http://127.0.0.1", allow_local_agent=1),
    )

    def _fake_run(*_a, **kwargs):
        run_dir = kwargs.get("run_dir")
        if run_dir is not None:
            (run_dir / "final.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return {"status": "passed", "duration_ms": 5, "screenshots": ["final.png"]}

    monkeypatch.setattr(runner, "run_script", _fake_run)
    gen_id = svc.mark_generating(db, case)
    files = _files()
    assert svc.validate(db, case, files)["ok"]
    svc._dry_run_last.pop(int(case.id), None)
    result = svc.dry_run(db, case, files, contract.source_hash(contract.normalize_files(files)[0]))
    assert result["ok"], result
    assert paths.generation_shot(int(case.id), int(gen_id)).is_file()


def test_rest_regenerate_mode_prompt(monkeypatch, db, case):
    """重新生成与新建/修复共用同一套文案；已实现通过用例在 auto 下也分诊为 regenerate。"""
    routes = _rest_routes(monkeypatch, db)
    scripted = _implemented_scripted(db, case)
    row = SimpleNamespace(id=9, expires_at=None)
    monkeypatch.setattr(routes.mcp_tokens, "create_token", lambda *a, **k: ("ins_tok", row))

    auto_result = asyncio.run(
        routes.create_prompt(
            _FakeRequest(), {"project_id": 1, "case_ids": [int(scripted.id)], "mode": "auto"}
        )
    )
    assert auto_result["mode"] == "auto"
    assert auto_result["action_required"] == 1
    assert auto_result["summary"]["regenerate"] == 1
    assert "ui.case.triage" in auto_result["prompt"]
    assert "ui.contract.get" in auto_result["prompt"]

    regen_result = asyncio.run(
        routes.create_prompt(
            _FakeRequest(), {"project_id": 1, "case_ids": [int(scripted.id)], "mode": "regenerate"}
        )
    )
    assert regen_result["mode"] == "regenerate"
    assert regen_result["action_required"] == 1
    assert regen_result["summary"]["regenerate"] == 1
    assert regen_result["prompt"] == auto_result["prompt"]
    assert (
        prompt_builder.render_regenerate_prompt([int(scripted.id)], "ins_tok", "http://x/mcp")
        == prompt_builder.render_auto_prompt([int(scripted.id)], "ins_tok", "http://x/mcp")
    )


def test_rest_triage_mode_validation(monkeypatch, db, case):
    from fastapi import HTTPException

    routes = _rest_routes(monkeypatch, db)
    with pytest.raises(HTTPException) as exc:
        routes.triage(project_id=1, case_ids=str(case.id), mode="regen")
    assert exc.value.status_code == 400

    ok = routes.triage(project_id=1, case_ids=str(case.id), mode="regenerate")
    assert ok["summary"]["regenerate"] == 0  # 用例没有脚本 → create
    assert ok["items"][0]["mode"] == "regenerate"


# ===== REST /cases：来源字段与 regenerate 分诊 =====


def test_case_out_exposes_authoring_source(db, case):
    """CaseDetailDrawer 的「本地 Agent 入库」徽标依赖 _case_out 返回 source。"""
    from insight_aitest.modules.ui.backend.automation.models import CaseSource
    from insight_aitest.modules.ui.backend.automation.routes import cases as case_routes

    authored_at = datetime(2026, 11, 14, 10, 30, 0)
    db.update_case(
        case.id,
        source=CaseSource.LOCAL_AGENT,
        authoring_by="local_agent",
        authoring_at=authored_at,
    )
    out = case_routes._case_out(db.get_case(case.id), db)
    assert out["source"] == "local_agent"
    assert out["authoring_by"] == "local_agent"
    assert out["authoring_at"] == authored_at.isoformat()

    # 未入库过的用例保持默认值，前端不会误显示徽标
    fresh_id = db.create_case(
        project_id=1,
        kb_document_id=102,
        title="新用例",
        precondition="",
        steps=[],
        expected="",
        site="frontend",
    )
    fresh = case_routes._case_out(db.get_case(fresh_id), db)
    assert fresh["source"] == "ai"
    assert fresh["authoring_by"] == ""
    assert fresh["authoring_at"] is None


def test_regenerate_without_script_returns_400(monkeypatch, db, case):
    from fastapi import HTTPException

    from insight_aitest.modules.ui.backend.automation.routes import cases as case_routes

    def _unexpected(*_a, **_k):
        raise AssertionError("无脚本时不应启动重新生成任务")

    monkeypatch.setattr(case_routes, "start_job", _unexpected)
    with pytest.raises(HTTPException) as exc:
        case_routes.regenerate(int(case.id), db)
    assert exc.value.status_code == 400
    assert "该用例还没有脚本，无法重新生成，请先生成脚本" in str(exc.value.detail)


def test_generate_upgrades_to_regenerate_when_script_exists(monkeypatch, db, case):
    """AC-18：旧客户端仍打 /generate，已有脚本时按 regenerate 记账并如实回显。"""
    from insight_aitest.modules.ui.backend.automation.routes import cases as case_routes

    scripted = _implemented_scripted(db, case)
    started: list[str] = []

    monkeypatch.setattr(case_routes.concurrency, "acquire", lambda _pid: True)
    monkeypatch.setattr(case_routes.concurrency, "release", lambda _pid: None)
    monkeypatch.setattr(case_routes.concurrency, "set_progress", lambda *_a, **_k: None)
    monkeypatch.setattr(case_routes, "start_job", lambda _cid, kind: started.append(kind))

    result = case_routes.generate(int(scripted.id), db)
    assert result["kind"] == "regenerate"
    assert started == ["regenerate"]

    # 无脚本时 /generate 仍是 generate，不做转换
    plain = db.create_case(
        project_id=1,
        kb_document_id=103,
        title="无脚本用例",
        precondition="",
        steps=[],
        expected="",
        site="frontend",
    )
    result = case_routes.generate(int(plain), db)
    assert result["kind"] == "generate"
    assert started == ["regenerate", "generate"]


def test_cancel_closes_local_generation(monkeypatch, tmp_path, db, case):
    from insight_aitest.modules.ui.backend.automation.routes import cases as case_routes

    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path / "ws")
    monkeypatch.setattr(case_routes, "cancel_job", lambda _case_id: False)
    gen_id = svc.mark_generating(db, case)

    result = case_routes.cancel_generate(int(case.id), db)
    assert result["accepted"] is True
    assert result.get("local_abandoned") is True
    gen = db.get_generation(gen_id)
    assert gen.status == "failed"
    assert "用户已终止" in (gen.error_message or "")
    assert db.get_authoring_state(int(case.id)).generation_id is None
