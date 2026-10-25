# -*- coding: utf-8 -*-
"""用例 CRUD + 状态切换 API 集成测试。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("INSIGHT_EYE_AI_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("INSIGHT_EYE_AI_EMBED_DIM", "4")
    import insight_aitest.modules.testcase.backend.deps as tc_deps
    tc_deps._tc_db = None
    # 注入 tmp db
    from insight_aitest.modules.testcase.backend.persistence.database import TestCaseDatabase
    tc_deps._tc_db = TestCaseDatabase(str(tmp_path / "testcase.db"))
    from insight_aitest.modules.testcase.backend.routes import router as tc_router
    app = FastAPI()
    app.include_router(tc_router, prefix="/api/modules/testcase")
    return TestClient(app)


def test_create_get_list_update_status_delete(tmp_path, monkeypatch):
    c = _setup_app(tmp_path, monkeypatch)
    r = c.post("/api/modules/testcase/testcases", json={
        "title": "登录测试", "type": "functional",
        "content": {"steps": [], "expected": "成功"}, "preconditions": "已开登录页"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert r.json()["status"] == "draft"

    assert c.get(f"/api/modules/testcase/testcases/{cid}").json()["title"] == "登录测试"
    assert len(c.get("/api/modules/testcase/testcases").json()) == 1

    r = c.patch(f"/api/modules/testcase/testcases/{cid}/status", json={"status": "reviewed"})
    assert r.json()["status"] == "reviewed"

    r = c.put(f"/api/modules/testcase/testcases/{cid}", json={"title": "登录正向"})
    assert r.json()["title"] == "登录正向"

    assert c.delete(f"/api/modules/testcase/testcases/{cid}").status_code == 200
    assert c.get(f"/api/modules/testcase/testcases/{cid}").status_code == 404


def test_list_filter(tmp_path, monkeypatch):
    c = _setup_app(tmp_path, monkeypatch)
    c.post("/api/modules/testcase/testcases", json={"title": "a", "type": "functional"})
    c.post("/api/modules/testcase/testcases", json={"title": "b", "type": "api"})
    assert len(c.get("/api/modules/testcase/testcases").json()) == 2
    assert len(c.get("/api/modules/testcase/testcases?type=functional").json()) == 1
    assert len(c.get("/api/modules/testcase/testcases?type=api").json()) == 1


def test_update_result_endpoint(tmp_path, monkeypatch):
    c = _setup_app(tmp_path, monkeypatch)
    cid = c.post("/api/modules/testcase/testcases", json={
        "title": "API 用例", "type": "api",
        "content": {"base_url": "http://x", "steps": []}}).json()["id"]
    r = c.patch(f"/api/modules/testcase/testcases/{cid}/result",
                json={"result": "passed", "run_at": "2026-06-25T10:00:00"})
    assert r.status_code == 200
    body = r.json()
    assert body["last_result"] == "passed"
    assert body["last_run_at"] is not None

    # 404
    assert c.patch("/api/modules/testcase/testcases/9999/result",
                   json={"result": "failed"}).status_code == 404


def test_update_content_and_tags(tmp_path, monkeypatch):
    c = _setup_app(tmp_path, monkeypatch)
    cid = c.post("/api/modules/testcase/testcases", json={"title": "x"}).json()["id"]
    r = c.put(f"/api/modules/testcase/testcases/{cid}", json={
        "content": {"steps": [{"no": 1, "action": "点"}], "expected": "ok"},
        "tags": ["登录", "正向"]})
    body = r.json()
    assert body["content"]["expected"] == "ok"
    assert body["tags"] == ["登录", "正向"]


def test_health(tmp_path, monkeypatch):
    c = _setup_app(tmp_path, monkeypatch)
    assert c.get("/api/modules/testcase/health").json()["status"] == "healthy"


def test_folders_and_batch_operations(tmp_path, monkeypatch):
    c = _setup_app(tmp_path, monkeypatch)
    # 创建目录
    r = c.post("/api/modules/testcase/testcases/folders", json={"name": "用户模块", "project_id": 1})
    assert r.status_code == 201
    f1_id = r.json()["id"]

    # 创建子目录
    r = c.post("/api/modules/testcase/testcases/folders", json={"name": "注册子模块", "parent_id": f1_id, "project_id": 1})
    assert r.status_code == 201
    f2_id = r.json()["id"]

    # 查目录树
    tree = c.get("/api/modules/testcase/testcases/folders?project_id=1").json()
    assert len(tree) == 1
    assert tree[0]["id"] == f1_id
    assert len(tree[0]["children"]) == 1
    assert tree[0]["children"][0]["id"] == f2_id

    # 创建带目录的用例
    c1 = c.post("/api/modules/testcase/testcases", json={"title": "用例1", "project_id": 1, "folder_id": f1_id}).json()["id"]
    c2 = c.post("/api/modules/testcase/testcases", json={"title": "用例2", "project_id": 1, "folder_id": f2_id}).json()["id"]
    c3 = c.post("/api/modules/testcase/testcases", json={"title": "用例3", "project_id": 1}).json()["id"]

    # 按目录筛选
    assert len(c.get(f"/api/modules/testcase/testcases?folder_id={f1_id}").json()) == 1
    assert len(c.get(f"/api/modules/testcase/testcases?folder_id={f2_id}").json()) == 1
    assert len(c.get("/api/modules/testcase/testcases?folder_id=-1").json()) == 1  # 未分类

    # 批量分配目录
    r = c.post("/api/modules/testcase/testcases/batch-assign", json={"case_ids": [c3], "folder_id": f1_id})
    assert r.status_code == 200
    assert r.json()["updated"] == 1
    assert len(c.get(f"/api/modules/testcase/testcases?folder_id={f1_id}").json()) == 2

    # 批量修改所属项目
    r = c.post("/api/modules/testcase/testcases/batch-assign", json={"case_ids": [c3], "project_id": 2, "folder_id": -1, "version_id": -1})
    assert r.status_code == 200
    assert r.json()["updated"] == 1
    c3_data = c.get("/api/modules/testcase/testcases?project_id=2").json()
    assert len(c3_data) == 1
    assert c3_data[0]["id"] == c3
    assert c3_data[0]["folder_id"] is None
    assert c3_data[0]["version_id"] is None

    # 批量清空项目
    r = c.post("/api/modules/testcase/testcases/batch-assign", json={"case_ids": [c3], "project_id": -1})
    assert r.status_code == 200
    c3_data_cleared = c.get("/api/modules/testcase/testcases").json()
    c3_item = next(x for x in c3_data_cleared if x["id"] == c3)
    assert c3_item["project_id"] is None

    # 批量删除
    r = c.post("/api/modules/testcase/testcases/batch-delete", json={"case_ids": [c1, c2]})
    assert r.status_code == 200
    assert r.json()["deleted"] == 2
    assert len(c.get("/api/modules/testcase/testcases").json()) == 1

