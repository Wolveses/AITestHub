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
