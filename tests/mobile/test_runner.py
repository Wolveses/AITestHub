# -*- coding: utf-8 -*-
from __future__ import annotations

import types

from insight_aitest.modules.mobile.backend.automation import paths, runner
from insight_aitest.modules.mobile.backend.persistence.database import MobileDatabase
from insight_aitest.modules.mobile.backend.persistence.models import ErrorCategory


def test_classify_failure_categories():
    assert runner.classify_failure("Connection refused to Appium server") == ErrorCategory.ENV
    assert runner.classify_failure("adb: device offline") == ErrorCategory.ENV
    assert runner.classify_failure("前置条件缺失：未提供测试账号") == ErrorCategory.CASE
    assert runner.classify_failure("AssertionError: expected True") == ErrorCategory.SCRIPT


def test_build_params_coercion():
    case = types.SimpleNamespace(
        params_json={"count": "42", "flag": "true", "label": "ok"},
        params_schema_json=[
            {"name": "count", "type": "int", "required": True},
            {"name": "flag", "type": "bool"},
            {"name": "label", "type": "string"},
        ],
    )
    built = runner.build_params(case)
    assert built["values"] == {"count": 42, "flag": True, "label": "ok"}


def test_run_script_executes_real_pytest_and_prunes_old_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "_OVERRIDE_ROOT", tmp_path / "ws")
    monkeypatch.setattr(runner, "SCAFFOLD_PLUGIN", "no:warnings")

    db = MobileDatabase(str(tmp_path / "mobile.db"))
    app_id = db.create_app(
        project_id=7,
        name="TestApp",
        app_package="com.example.test",
        app_activity=".MainActivity",
    )
    app = db.get_app(app_id)
    case_id = db.create_case(
        project_id=7,
        kb_document_id=88,
        title="Smoke Check",
        steps=["Open app"],
    )
    case = db.get_case(case_id)

    script_file = paths.case_script_path(7, case_id)
    script_file.write_text(
        "import json, os\n\n"
        "def test_smoke():\n"
        "    with open(os.environ['INSIGHT_MOBILE_ENV'], encoding='utf-8') as f:\n"
        "        env = json.load(f)\n"
        "    assert env['app_package'] == 'com.example.test'\n",
        encoding="utf-8",
    )

    # Pre-seed RUN_RETAIN + 2 old run dirs to verify pruning
    art_parent = paths.workspace_root() / "artifacts" / "7" / str(case_id)
    art_parent.mkdir(parents=True, exist_ok=True)
    for idx in range(runner.RUN_RETAIN + 2):
        (art_parent / f"old_{idx:02d}").mkdir()

    res = runner.run_script(
        case,
        app,
        "emulator-5554",
        script_path=script_file,
        skip_doctor=True,
        timeout=30,
    )
    assert res["status"] == "passed"
    assert res["run_status"] == "passed"
    assert res["script_hash"]
    out_dir = paths.resolve_rel(res["artifacts_rel_path"])
    assert (out_dir / "junit.xml").exists()
    assert (out_dir / "stdout.log").exists()
    remaining_dirs = [p for p in art_parent.iterdir() if p.is_dir()]
    assert len(remaining_dirs) <= runner.RUN_RETAIN
