# -*- coding: utf-8 -*-
"""接口资产组合成 API 流程：排序、依赖提取/传递、断言生成。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from insight_aitest.modules.api.backend.services.flow_compose import compose_case


def _asset(index: int, method: str, path: str, *, body=None, response=None, headers=None):
    return SimpleNamespace(
        id=index,
        project_id=1,
        title=f"{method} {path}",
        method=method,
        path=path,
        path_template=path,
        base_url="https://demo.test",
        headers=headers or {"Content-Type": "application/json", "Authorization": "Bearer secret"},
        body=body,
        response_status=200,
        response_headers={"Content-Type": "application/json"},
        response_body=response if response is not None else {"code": 0},
        ai_meta=None,
    )


def _create_flow():
    create = _asset(
        1,
        "POST",
        "/api/users",
        body={"name": "auto"},
        response={"code": 0, "data": {"id": "u-1001", "name": "auto"}},
    )
    update = _asset(
        2,
        "PUT",
        "/api/users/u-1001",
        body={"name": "auto2"},
        response={"code": 0, "data": {"id": "u-1001", "name": "auto2"}},
    )
    query = _asset(3, "GET", "/api/users/u-1001", response={"code": 0, "data": {"id": "u-1001"}})
    delete = _asset(4, "DELETE", "/api/users/u-1001", response={"code": 0})
    return [update, delete, create, query]  # 传入顺序故意打乱


def test_rule_order_and_dependency_extraction():
    result = compose_case(_create_flow(), "用户增改查删流程", llm=None)
    steps = result["content"]["steps"]

    # 规则排序：新增 → 修改 → 查询 → 删除
    assert [s["method"] for s in steps] == ["POST", "PUT", "GET", "DELETE"]
    assert result["ai_used"] is False

    # 创建步骤按业务语义提取 ID，后续步骤引用 {{user_id}}
    assert steps[0]["extract"] == {"user_id": "$.data.id"}
    assert steps[1]["path"] == "/api/users/{{user_id}}"
    assert steps[2]["path"] == "/api/users/{{user_id}}"
    assert steps[3]["path"] == "/api/users/{{user_id}}"
    assert result["dependencies"] == [{"asset_id": 1, "extract": {"user_id": "$.data.id"}}]

    # 每步都有状态码断言，关键字段用 jsonpath 对比抓包期望值
    assert steps[0]["assertions"][0] == {"type": "status_code", "expected": 200}
    assert steps[0]["assertions"][1] == {"type": "jsonpath", "path": "$.code", "expected": 0}
    assert "json_schema" not in [a["type"] for a in steps[0]["assertions"]]
    # 动态 id 不做等值断言
    assert all("data.id" not in (a.get("path") or "") for a in steps[0]["assertions"])

    # 凭证头不进入用例
    assert "Authorization" not in steps[0]["headers"]
    assert result["content"]["asset_ids"] == [1, 2, 3, 4]
    assert result["content"]["base_url"] == "https://demo.test"


def test_ai_plan_controls_order_and_dependencies():
    calls: list[dict] = []

    class FakeLLM:
        def chat(self, messages, **kwargs):
            calls.append({"messages": messages, **kwargs})
            return json.dumps(
                {
                    "steps": [
                        {"index": 2, "seq": 1, "name": "创建用户", "extract": {"user_id": "$.data.id"}},
                        {
                            "index": 0,
                            "seq": 2,
                            "name": "修改用户",
                            "inject": [{"var": "user_id", "in": "path"}],
                        },
                        {
                            "index": 1,
                            "seq": 3,
                            "name": "查询用户",
                            "inject": [{"var": "user_id", "in": "path"}],
                        },
                        {
                            "index": 3,
                            "seq": 4,
                            "name": "删除用户",
                            "inject": [{"var": "user_id", "in": "path"}],
                        },
                    ],
                    "reason": "先增后改，再查删",
                }
            )

    result = compose_case(_create_flow(), "用户增改查删流程", FakeLLM())
    steps = result["content"]["steps"]
    assert result["ai_used"] is True
    assert [s["method"] for s in steps] == ["POST", "PUT", "GET", "DELETE"]
    assert steps[0]["name"] == "创建用户"
    assert steps[0]["extract"] == {"user_id": "$.data.id"}
    assert steps[1]["path"] == "/api/users/{{user_id}}"
    assert steps[3]["path"] == "/api/users/{{user_id}}"
    assert calls[0]["temperature"] == 0
    # 提示词不携带凭证
    assert "Bearer secret" not in calls[0]["messages"][1]["content"]


def test_ai_declares_extract_and_uses_for_body():
    """模型声明 extract/uses 后，即使抓包值与新数据不同，也按字段名传递变量。"""

    class FakeLLM:
        def chat(self, messages, **kwargs):
            return json.dumps(
                {
                    "steps": [
                        {
                            "index": 0,
                            "seq": 1,
                            "name": "获取部门列表",
                            "extract": {"dept_id": "$[0].id"},
                        },
                        {
                            "index": 1,
                            "seq": 2,
                            "name": "新增用户",
                            "inject": [{"var": "dept_id", "in": "body", "field": "deptId"}],
                            "extract": {"user_id": "$.data.id"},
                        },
                    ],
                    "reason": "先查部门再新增用户",
                }
            )

    dept = _asset(1, "GET", "/api/depts", response=[{"id": "d-0001"}])
    create = _asset(
        2,
        "POST",
        "/api/users",
        body={"deptId": "d-9999", "name": "auto"},
        response={"code": 0, "data": {"id": "u-2002"}},
    )
    result = compose_case([dept, create], "新增用户", FakeLLM())
    steps = result["content"]["steps"]
    assert steps[0]["extract"] == {"dept_id": "$[0].id"}
    assert steps[1]["body"]["deptId"] == "{{dept_id}}"
    assert steps[1]["extract"] == {"user_id": "$.data.id"}


def test_ai_inject_query_and_header():
    """inject 声明的 query/header 位置能正确注入，而不是靠猜。"""

    class FakeLLM:
        def chat(self, messages, **kwargs):
            return json.dumps(
                {
                    "steps": [
                        {"index": 0, "seq": 1, "name": "获取部门列表", "extract": {"dept_id": "$[0].id"}},
                        {
                            "index": 1,
                            "seq": 2,
                            "name": "按部门查询用户",
                            "inject": [
                                {"var": "dept_id", "in": "query", "field": "deptId"},
                                {"var": "dept_id", "in": "header", "field": "X-Dept-Id"},
                            ],
                        },
                    ],
                    "reason": "查询参数和header都要部门ID",
                }
            )

    dept = _asset(1, "GET", "/api/depts", response=[{"id": "d-0001"}])
    users = _asset(2, "GET", "/api/users?deptId=old&page=1", headers={"X-Dept-Id": "old"})
    result = compose_case([dept, users], "按部门查用户", FakeLLM())
    steps = result["content"]["steps"]
    assert steps[1]["path"] == "/api/users?deptId={{dept_id}}&page=1"
    assert steps[1]["headers"]["X-Dept-Id"] == "{{dept_id}}"


def test_invalid_ai_order_falls_back_to_rules():
    class BadLLM:
        def chat(self, messages, **kwargs):
            return json.dumps({"order": [0, 0, 1], "steps": []})

    result = compose_case(_create_flow(), "流程", BadLLM())
    assert result["ai_used"] is False
    assert [s["method"] for s in result["content"]["steps"]] == ["POST", "PUT", "GET", "DELETE"]


def test_missing_delete_warns_about_leftover_data():
    assets = [_asset(1, "POST", "/api/users", response={"code": 0, "data": {"id": "u-1"}})]
    result = compose_case(assets, "仅创建", llm=None)
    assert "可能残留测试数据" in result["description"]


def test_dependency_provider_ordered_first():
    """部门列表提供 deptId → 必须排在新增用户之前，并自动提取传递。"""
    zero_id = "00000000000000000000000000000000"
    dept = _asset(1, "GET", "/api/depts", response=[{"id": zero_id, "name": "研发"}])
    create = _asset(
        2,
        "POST",
        "/api/users",
        body={"deptId": zero_id, "name": "auto"},
        response={"code": 0},
    )
    query = _asset(
        3,
        "POST",
        "/api/users/page",
        body={"deptId": zero_id, "page": 1},
        response={"code": 0},
    )
    result = compose_case([create, query, dept], "新增用户", llm=None)
    steps = result["content"]["steps"]

    assert steps[0]["method"] == "GET"
    assert steps[0]["extract"] == {"dept_id": "$[0].id"}
    assert steps[1]["body"]["deptId"] == "{{dept_id}}"
    assert steps[2]["body"]["deptId"] == "{{dept_id}}"
    assert result["dependencies"] == [{"asset_id": 1, "extract": {"dept_id": "$[0].id"}}]


def test_ai_order_is_corrected_by_dependency():
    """AI 给出的顺序若违反参数依赖，也会被校正为「提供方在前」。"""

    class WrongLLM:
        def chat(self, messages, **kwargs):
            return json.dumps(
                {
                    "steps": [
                        {"index": 0, "seq": 1, "name": "新增用户"},
                        {"index": 1, "seq": 2, "name": "获取部门列表"},
                    ],
                    "reason": "按方法排序",
                }
            )

    dept = _asset(1, "GET", "/api/depts", response=[{"id": "d-0001"}])
    create = _asset(2, "POST", "/api/users", body={"deptId": "d-0001"}, response={"code": 0})
    assets = [create, dept]  # AI 说 create 在前
    result = compose_case(assets, "新增用户", WrongLLM())
    assert result["ai_used"] is True
    assert result["content"]["steps"][0]["method"] == "GET"
    assert "自动校正顺序" in result["description"]


def test_detail_query_reuses_created_id():
    """获取用户详情：路径里的旧管理员 ID 换成新增用户提取的 {{user_id}}，并断言返回 ID 一致。"""
    create = _asset(
        1,
        "POST",
        "/api/users",
        body={"name": "auto", "deptId": "d-0001"},
        response={"code": 0, "data": {"id": "u-1001", "name": "auto"}},
    )
    detail = _asset(
        2,
        "GET",
        "/api/users/9?tab=basic",
        response={"code": 0, "data": {"id": "u-1001", "name": "auto"}},
    )
    result = compose_case([detail, create], "获取用户详情", llm=None)
    steps = result["content"]["steps"]
    detail_step = next(s for s in steps if s["method"] == "GET")

    assert steps[0]["method"] == "POST"  # 新增在前
    assert steps[0]["extract"] == {"user_id": "$.data.id"}
    assert detail_step["path"] == "/api/users/{{user_id}}?tab=basic"
    assert {"type": "jsonpath", "path": "$.data.id", "expected": "{{user_id}}"} in detail_step["assertions"]
