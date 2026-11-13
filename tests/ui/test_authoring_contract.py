# -*- coding: utf-8 -*-
"""本地 Agent 编写的契约校验与入库状态机测试。"""

from datetime import datetime, timedelta

import pytest

from insight_aitest.modules.ui.backend.automation import authoring_service as svc
from insight_aitest.modules.ui.backend.automation import contract, example_service, lessons, paths
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


def test_agent_first_contact_marks_generating(db, case):
    """Agent 首次调用 contract.get 后，用例进入「生成中」，且重复调用幂等。"""
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
    assert result["code"] == "VALIDATION_REQUIRED"


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
    assert [p.name for p in asyncio.run(server.list_prompts())] == ["ui.create", "ui.fix"]
    assert [str(r.uri) for r in asyncio.run(server.list_resources())] == [
        "insight://rules",
        "insight://template",
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


def test_triage_skip_cases(case):
    _implemented(case)
    assert svc.case_action(case, None) == ("skip", "无执行记录，视为通过")
    assert svc.case_action(case, {"status": "passed"}) == ("skip", "最近执行通过")
    assert svc.case_action(case, {"status": "running"})[0] == "skip"


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
    passed_case = _implemented(db.get_case(passed_id))
    failed_case = _implemented(db.get_case(failed_id))
    case = db.get_case(case.id)  # 未实现 → create

    runs = _FakeRunsDb({passed_id: {"status": "passed"}, failed_id: {"status": "failed", "error": "boom"}})
    result = svc.triage_cases(runs, [case, passed_case, failed_case])
    assert result["summary"] == {"create": 1, "fix": 1, "skip": 1}
    by_id = {item["case_id"]: item for item in result["items"]}
    assert by_id[int(case.id)]["action"] == "create"
    assert by_id[passed_id]["action"] == "skip"
    assert by_id[failed_id]["action"] == "fix"
    assert by_id[failed_id]["next_tool"] == "ui.run.latest"
    assert by_id[passed_id]["next_tool"] is None


def test_fail_envelope_guides_next_tool():
    err = svc.fail("STALE_CASE", "用例已变更")
    assert err["ok"] is False
    assert err["retryable"] is True
    assert err["required_next"] == "ui.contract.get"

    fatal = svc.fail("PERMISSION_DENIED", "无权限")
    assert fatal["retryable"] is False
    assert fatal["required_next"] is None


def test_error_result_marks_is_error():
    from insight_aitest.modules.ui.backend.automation.mcp_server import _error

    result = _error(svc.fail("BUSY", "该用例正被其他本地 Agent 操作"))
    assert result.is_error is True
    assert result.structured_content["code"] == "BUSY"
    assert result.structured_content["retryable"] is True
