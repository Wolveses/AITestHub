# -*- coding: utf-8 -*-
"""UI 自动化任务管理测试。"""

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from insight_aitest.modules.ui.backend.automation.database import UIAutomationDatabase
from insight_aitest.modules.ui.backend.automation.models import CaseStatus, Site
from insight_aitest.modules.ui.backend.automation.routes.tasks import router as tasks_router
from insight_aitest.modules.ui.backend.automation.task_models import TaskStatus, TriggerType
from insight_aitest.modules.ui.backend.automation.task_runner import execute_task


@pytest.fixture
def test_setup(tmp_path):
    db_path = str(tmp_path / "ui.db")
    db = UIAutomationDatabase(db_path)

    # 创建测试环境
    env_id = db.create_env(
        project_id=1,
        name="测试测试环境",
        base_url="http://test.local",
    )
    env = db.get_env(env_id)

    # patch get_automation_db
    with patch(
        "insight_aitest.modules.ui.backend.automation.routes.tasks.get_automation_db",
        return_value=db,
    ), patch(
        "insight_aitest.modules.ui.backend.automation.task_runner.get_automation_db",
        return_value=db,
    ), patch(
        "insight_aitest.modules.ui.backend.automation.deps.get_automation_db",
        return_value=db,
    ):
        app = FastAPI()
        app.include_router(tasks_router, prefix="/api/ui")
        client = TestClient(app)
        yield db, client, env


def test_task_crud_and_validation(test_setup):
    db, client, env = test_setup

    # 1. 错误环境创建任务 -> 400
    res = client.post(
        "/api/ui/automation/tasks",
        json={"project_id": 1, "name": "夜间全量任务", "env_id": 9999},
    )
    assert res.status_code == 400
    assert "选定的环境不存在" in res.json()["detail"]

    # 2. 启用定时但未填 cron 表达式 -> 400
    res = client.post(
        "/api/ui/automation/tasks",
        json={"project_id": 1, "name": "夜间任务", "env_id": env.id, "cron_enabled": True, "cron_expression": ""},
    )
    assert res.status_code == 400
    assert "必须输入 Cron" in res.json()["detail"]

    # 3. 错误 cron 表达式 -> 400
    res = client.post(
        "/api/ui/automation/tasks",
        json={"project_id": 1, "name": "夜间任务", "env_id": env.id, "cron_enabled": True, "cron_expression": "bad cron"},
    )
    assert res.status_code == 400

    # 4. 成功创建任务
    res = client.post(
        "/api/ui/automation/tasks",
        json={
            "project_id": 1,
            "name": "夜间全量回归",
            "env_id": env.id,
            "description": "每天凌晨2点定时运行全量已实现用例",
            "cron_enabled": True,
            "cron_expression": "0 2 * * *",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "夜间全量回归"
    assert data["env_name"] == env.name
    assert data["cron_enabled"] is True
    assert data["case_count"] == 0
    task_id = data["id"]

    # 5. 查询任务详情与列表
    get_res = client.get(f"/api/ui/automation/tasks/{task_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "夜间全量回归"

    list_res = client.get("/api/ui/automation/tasks?project_id=1")
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    # 6. 修改任务
    up_res = client.put(
        f"/api/ui/automation/tasks/{task_id}",
        json={"name": "修改后的夜间任务", "cron_enabled": False},
    )
    assert up_res.status_code == 200
    assert up_res.json()["name"] == "修改后的夜间任务"
    assert up_res.json()["cron_enabled"] is False

    # 7. 删除任务
    del_res = client.delete(f"/api/ui/automation/tasks/{task_id}")
    assert del_res.status_code == 200
    assert del_res.json() == {"ok": True}

    assert client.get(f"/api/ui/automation/tasks/{task_id}").status_code == 404


def test_importable_cases_filters_empty_categories_and_deduplicates(test_setup):
    """测试：导入时空目录不展示；同一任务、同一用例不可重复导入。"""
    db, client, env = test_setup

    # 创建任务
    task = db.create_task(project_id=1, name="核心主流程任务", env_id=env.id)

    # 创建用例：
    # 目录 A: 2个已实现用例
    c1_id = db.create_case(project_id=1, kb_document_id=101, title="正确账号登录", category_path="用户认证", site=Site.FRONTEND)
    db.update_case(c1_id, status=CaseStatus.IMPLEMENTED)

    c2_id = db.create_case(project_id=1, kb_document_id=102, title="退出登录", category_path="用户认证", site=Site.FRONTEND)
    db.update_case(c2_id, status=CaseStatus.IMPLEMENTED)

    # 目录 B: 仅有未实现用例（空目录 / 无已实现用例）
    c3_id = db.create_case(project_id=1, kb_document_id=103, title="修改密码", category_path="安全设置", site=Site.FRONTEND)
    assert db.get_case(c3_id).status == CaseStatus.NOT_IMPLEMENTED

    # 目录 C: 1个已实现用例
    c4_id = db.create_case(project_id=1, kb_document_id=104, title="商品加入购物车", category_path="商城交易", site=Site.FRONTEND)
    db.update_case(c4_id, status=CaseStatus.IMPLEMENTED)

    # 1. 验证可导入列表：空目录（安全设置）绝不展示！
    res = client.get(f"/api/ui/automation/tasks/{task.id}/importable-cases?project_id=1")
    assert res.status_code == 200
    data = res.json()
    assert data["total_implemented"] == 3
    cat_names = [cat["name"] for cat in data["categories"]]
    assert "用户认证" in cat_names
    assert "商城交易" in cat_names
    assert "安全设置" not in cat_names  # 空目录不展示

    # 2. 导入 c1, c2
    imp_res = client.post(
        f"/api/ui/automation/tasks/{task.id}/cases/import",
        json={"case_ids": [c1_id, c2_id]},
    )
    assert imp_res.status_code == 200
    assert imp_res.json()["imported_count"] == 2
    assert imp_res.json()["total_cases"] == 2

    # 3. 再次查询可导入列表：c1, c2 应标记已导入
    res2 = client.get(f"/api/ui/automation/tasks/{task.id}/importable-cases?project_id=1")
    user_cat = next(cat for cat in res2.json()["categories"] if cat["name"] == "用户认证")
    for case_item in user_cat["cases"]:
        assert case_item["already_imported"] is True

    # 4. 重复导入 c1, c2（同一任务同一用例不可重复导入）
    dup_res = client.post(
        f"/api/ui/automation/tasks/{task.id}/cases/import",
        json={"case_ids": [c1_id, c2_id, c4_id]},
    )
    assert dup_res.status_code == 200
    # 仅 c4 成功导入，c1 和 c2 被去重
    assert dup_res.json()["imported_count"] == 1
    assert dup_res.json()["total_cases"] == 3

    # 5. 查看任务已有关联用例
    cases_res = client.get(f"/api/ui/automation/tasks/{task.id}/cases")
    assert len(cases_res.json()) == 3

    # 6. 从任务中移除 c1
    del_c_res = client.delete(f"/api/ui/automation/tasks/{task.id}/cases/{c1_id}")
    assert del_c_res.status_code == 200
    assert del_c_res.json() == {"ok": True}
    assert len(client.get(f"/api/ui/automation/tasks/{task.id}/cases").json()) == 2


def test_task_execution_and_report(test_setup):
    """测试任务手动触发与测试报告生成。"""
    db, client, env = test_setup

    task = db.create_task(project_id=1, name="报告回归任务", env_id=env.id)
    c1_id = db.create_case(project_id=1, kb_document_id=201, title="用例1", category_path="模块A", site=Site.FRONTEND)
    db.update_case(c1_id, status=CaseStatus.IMPLEMENTED)
    db.import_cases_to_task(task.id, [c1_id])

    # Mock 脚本执行成功
    mock_run_script = MagicMock(return_value={
        "run_status": "passed",
        "error_message": "",
        "duration_ms": 1500,
        "artifacts_rel_path": "scripts/1/ui_cases/1/runs/1",
        "trace_rel_path": "",
    })

    with patch(
        "insight_aitest.modules.ui.backend.automation.task_runner.start_run",
        return_value=(1, MagicMock()),
    ), patch(
        "insight_aitest.modules.ui.backend.automation.task_runner.run_script",
        mock_run_script,
    ), patch(
        "insight_aitest.modules.ui.backend.automation.task_runner.finish_run",
    ):
        run = execute_task(task.id, trigger_type=TriggerType.MANUAL)
        assert run is not None
        assert run.status in (TaskStatus.RUNNING, TaskStatus.PASSED)

        # 等待 worker 完成
        import time
        for _ in range(20):
            time.sleep(0.05)
            r = db.get_task_run(run.id)
            if r and r.status != TaskStatus.RUNNING:
                break

        updated_run = db.get_task_run(run.id)
        assert updated_run.status == TaskStatus.PASSED
        assert updated_run.total_cases == 1
        assert updated_run.passed_cases == 1
        assert updated_run.failed_cases == 0

        # 查询测试报告 API
        rep_res = client.get(f"/api/ui/automation/tasks/runs/{run.id}/report")
        assert rep_res.status_code == 200
        rep_data = rep_res.json()
        assert rep_data["run"]["status"] == "passed"
        assert rep_data["task_name"] == "报告回归任务"
        assert len(rep_data["summary"]) == 1
        assert rep_data["summary"][0]["title"] == "用例1"
        assert rep_data["summary"][0]["status"] == "passed"
