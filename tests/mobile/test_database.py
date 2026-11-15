# -*- coding: utf-8 -*-
from __future__ import annotations

from insight_aitest.modules.mobile.backend.persistence.database import MobileDatabase
from insight_aitest.modules.mobile.backend.persistence.models import (
    CaseStatus,
    GenerationKind,
    GenerationStatus,
    MobilePlatform,
    ResetMode,
    RunStatus,
)


def test_mobile_app_crud_and_default_switch(tmp_path):
    db = MobileDatabase(str(tmp_path / "mobile.db"))

    app1_id = db.create_app(
        project_id=10,
        name="Demo App 1",
        platform=MobilePlatform.ANDROID,
        app_package="com.demo.one",
        app_activity=".MainActivity",
        reset_mode=ResetMode.NO_RESET,
        is_default=1,
    )
    app2_id = db.create_app(
        project_id=10,
        name="Demo App 2",
        platform=MobilePlatform.ANDROID,
        app_package="com.demo.two",
        is_default=1,
    )

    apps = db.list_apps(project_id=10)
    assert len(apps) == 2
    by_id = {a.id: a for a in apps}
    assert by_id[app1_id].is_default == 0
    assert by_id[app2_id].is_default == 1
    assert db.get_default_app(10).id == app2_id

    updated = db.update_app(app1_id, name="Renamed", is_default=1)
    assert updated is not None
    assert updated.name == "Renamed"
    assert db.get_default_app(10).id == app1_id

    assert db.delete_app(app2_id) is True
    assert db.get_app(app2_id) is None


def test_mobile_case_generation_run_and_lessons(tmp_path):
    db = MobileDatabase(str(tmp_path / "mobile.db"))

    case_id = db.create_case(
        project_id=1,
        kb_document_id=1001,
        title="用户登录成功",
        precondition="已安装 App",
        steps=["点击登录按钮", "输入账号密码", "校验首页元素"],
        expected="进入首页",
        category_path="账号/登录",
        platform=MobilePlatform.ANDROID,
    )
    case = db.get_case(case_id)
    assert case is not None
    assert case.status == CaseStatus.NOT_IMPLEMENTED
    assert db.imported_doc_ids(1) == {1001}

    cases, total = db.list_cases(1, keyword="登录", category_path="账号")
    assert total == 1 and len(cases) == 1

    gen_id = db.create_generation(
        mobile_case_id=case_id,
        kind=GenerationKind.GENERATE,
        device_id="emulator-5554",
        session_token_hash="abc123",
    )
    assert db.count_generations(case_id) == 1
    assert db.get_generation_by_token_hash("abc123").id == gen_id
    db.update_generation(gen_id, status=GenerationStatus.SUCCESS, tool_calls=5)
    assert db.get_generation_by_token_hash("abc123") is None

    run_id = db.create_run(
        case_id=case_id,
        project_id=1,
        case_title="用户登录成功",
        status=RunStatus.RUNNING,
        device_id="emulator-5554",
    )
    db.update_run(run_id, status=RunStatus.PASSED, duration_ms=1234)
    runs = db.list_runs(case_id=case_id)
    assert len(runs) == 1
    assert runs[0]["status"] == "passed"
    assert runs[0]["duration_ms"] == 1234

    db.upsert_lesson(1, "fp-login-popup", "popup", "权限弹窗", "先处理权限弹窗")
    db.upsert_lesson(1, "fp-login-popup", "popup", "权限弹窗", "先处理权限弹窗")
    lessons = db.list_lessons(1)
    assert len(lessons) == 1
    assert lessons[0].hits == 2

    assert db.delete_case(case_id) is True
    assert db.get_case(case_id) is None
