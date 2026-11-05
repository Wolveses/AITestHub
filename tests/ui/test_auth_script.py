# -*- coding: utf-8 -*-
import json
import pytest
from unittest.mock import MagicMock
from insight_aitest.modules.ui.backend.automation.env_service import (
    execute_auth_script,
    BrowserAuthPacker,
    prepare_auth,
    _sanitize_error,
    AUTH_SCRIPT_TEMPLATES,
)


def test_templates_only_one_generic():
    """验证模板仅保留一个通用的 POST 登录模板。"""
    assert len(AUTH_SCRIPT_TEMPLATES) == 1
    tpl = AUTH_SCRIPT_TEMPLATES[0]
    assert tpl["id"] == "generic_post"
    assert "get_token" in tpl["code"]


def test_sanitize_error():
    err = "Exception: failed login with secret_pwd123 and token_xyz890"
    res = _sanitize_error(err, "secret_pwd123", "token_xyz890")
    assert "secret_pwd123" not in res
    assert "token_xyz890" not in res
    assert "***" in res


def test_syntax_error():
    bad_code = "def get_token(base_url, username, password):\n    return token ("
    ok, msg, res = execute_auth_script(bad_code, "http://test.com", "user", "pass")
    assert not ok
    assert "语法错误" in msg


def test_missing_function():
    code = "def other_func(): pass"
    ok, msg, res = execute_auth_script(code, "http://test.com", "user", "pass")
    assert not ok
    assert "未定义可调用的函数 get_token" in msg


def test_valid_token_string_pack():
    code = '''
def get_token(base_url, username, password):
    assert base_url == "http://test.com"
    assert username == "admin"
    assert password == "123456"
    return "my_token_123"
'''
    ok, msg, res = execute_auth_script(code, "http://test.com", "admin", "123456")
    assert ok
    assert res == "my_token_123"

    env = MagicMock()
    env.project_id = 1
    env.id = 10
    env.token_inject = "header"
    env.token_name = "X-Auth-Token"
    env.token_prefix = "Token "

    auth = BrowserAuthPacker.process(env, res, "http://test.com")
    assert auth.ok
    assert auth.token == "my_token_123"
    assert auth.headers.get("X-Auth-Token") == "Token my_token_123"


def test_valid_dict_result(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "insight_aitest.modules.ui.backend.automation.paths.storage_state_path",
        lambda pid, eid: tmp_path / f"state_{pid}_{eid}.json",
    )
    code = '''
def get_token(base_url, username, password):
    return {
        "token": "tok_999",
        "headers": {"Authorization": "Bearer tok_999"},
        "cookies": [{"name": "sid", "value": "s123"}],
        "local_storage": {"flag": "true"}
    }
'''
    ok, msg, res = execute_auth_script(code, "http://test.com", "u", "p")
    assert ok
    assert isinstance(res, dict)

    env = MagicMock()
    env.project_id = 2
    env.id = 20
    env.token_inject = "custom"
    env.token_name = "token"
    env.token_prefix = ""

    auth = BrowserAuthPacker.process(env, res, "http://test.com")
    assert auth.ok
    assert auth.token == "tok_999"
    assert auth.headers.get("Authorization") == "Bearer tok_999"
    assert auth.storage_state_path

    # 验证落盘的 storageState 结构
    saved = json.loads((tmp_path / "state_2_20.json").read_text(encoding="utf-8"))
    assert saved["cookies"][0]["name"] == "sid"
    assert saved["cookies"][0]["domain"] == "test.com"
    assert saved["origins"][0]["localStorage"][0]["name"] == "flag"


def test_prepare_auth_without_script():
    """验证未配置脚本时的行为：无认证跳过，有账号密码提示配置脚本。"""
    env_free = MagicMock()
    env_free.project_id = 0
    env_free.auth_script = ""
    env_free.username = ""
    env_free.password_ref = ""
    res = prepare_auth(env_free)
    assert res.ok
    assert "跳过" in res.message

    env_need = MagicMock()
    env_need.project_id = 9999
    env_need.auth_script = ""
    env_need.username = "admin"
    env_need.password_ref = "ref1"
    res = prepare_auth(env_need, override_password="pwd")
    assert not res.ok
    assert "尚未配置前置获取 Token 脚本" in res.message


def test_project_level_auth_script(tmp_path, monkeypatch):
    """验证项目级统一前置脚本读写及 prepare_auth 自动加载。"""
    from insight_aitest.modules.ui.backend.automation.env_service import (
        get_project_auth_script,
        set_project_auth_script,
    )
    monkeypatch.setattr(
        "insight_aitest.modules.ui.backend.automation.paths.project_auth_script_path",
        lambda pid: tmp_path / f"auth_{pid}.py",
    )
    monkeypatch.setattr(
        "insight_aitest.modules.ui.backend.automation.paths.storage_state_path",
        lambda pid, eid: tmp_path / f"storage_{pid}_{eid}.json",
    )

    code = '''
def get_token(base_url, username, password):
    return "proj_token_888"
'''
    set_project_auth_script(100, code)
    assert get_project_auth_script(100) == code

    # 环境未配置单独 auth_script，prepare_auth 自动使用项目级统一脚本
    env = MagicMock()
    env.project_id = 100
    env.id = 5
    env.base_url = "http://project-app.com"
    env.username = "testuser"
    env.password_ref = "ref_mock"
    env.auth_script = ""
    env.token_inject = "cookie"
    env.token_name = "token"
    env.token_prefix = ""

    res = prepare_auth(env, override_password="mock_password")
    assert res.ok
    assert res.token == "proj_token_888"
    assert res.storage_state_path


def test_test_custom_env_with_project_id(tmp_path, monkeypatch):
    """验证新建测试环境连通性测试时，携带 project_id 能够自动关联并调用项目统一脚本。"""
    import asyncio
    from insight_aitest.modules.ui.backend.automation.env_service import set_project_auth_script
    from insight_aitest.modules.ui.backend.automation.routes.envs import EnvTestPayload, test_custom_env

    monkeypatch.setattr(
        "insight_aitest.modules.ui.backend.automation.paths.project_auth_script_path",
        lambda pid: tmp_path / f"auth_{pid}.py",
    )
    monkeypatch.setattr(
        "insight_aitest.modules.ui.backend.automation.paths.storage_state_path",
        lambda pid, eid: tmp_path / f"storage_{pid}_{eid}.json",
    )

    code = '''
def get_token(base_url, username, password):
    return "custom_test_token"
'''
    set_project_auth_script(200, code)

    # 模拟探活 httpx.Client.get 成功
    class DummyResponse:
        status_code = 200

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url):
            return DummyResponse()

    monkeypatch.setattr("httpx.Client", DummyClient)

    payload = EnvTestPayload(
        project_id=200,
        base_url="http://mock-service.local",
        username="admin",
        password="password123",
    )
    result = asyncio.run(test_custom_env(payload))
    assert result["ok"] is True
    assert result["token"] == "custom_test_token"
    assert "站点可访问（HTTP 200）" in result["message"]


def test_clone_env_endpoint(tmp_path, monkeypatch):
    """验证克隆环境接口的功能与密码复制机制。"""
    from insight_aitest.modules.ui.backend.automation.database import UIAutomationDatabase
    from insight_aitest.modules.ui.backend.automation.routes.envs import clone_env, EnvCloneIn
    from insight_aitest.modules.ui.backend.automation.env_service import get_password, set_password

    db_path = str(tmp_path / "ui_test.db")
    db = UIAutomationDatabase(db_path)

    # 模拟全局 secrets 存取
    secrets_map = {}
    monkeypatch.setattr("insight_aitest.modules.ui.backend.automation.env_service._read_secrets", lambda: secrets_map)
    monkeypatch.setattr("insight_aitest.modules.ui.backend.automation.env_service._write_secrets", lambda d: secrets_map.update(d))

    # 创建初始环境
    ref = "original_ref_123"
    set_password(ref, "secret_pass_888")
    env_id = db.create_env(
        project_id=1,
        name="测试环境 A",
        base_url="http://10.0.0.1:8080",
        username="admin",
        password_ref=ref,
        auth_script="print('test')",
        token_inject="cookie",
        token_name="token",
        token_prefix="Bearer ",
        is_default=1,
    )

    # 1. 默认副本名称克隆
    cloned_res = clone_env(env_id, None, db=db)
    assert cloned_res["name"] == "测试环境 A-副本"
    assert cloned_res["base_url"] == "http://10.0.0.1:8080"
    assert cloned_res["username"] == "admin"
    assert cloned_res["is_default"] is False
    assert cloned_res["password_set"] is True
    # 确认克隆出的环境密码在新 ref 下保存，且内容一致
    cloned_obj = db.get_env(cloned_res["id"])
    assert cloned_obj.password_ref != ref
    assert get_password(cloned_obj.password_ref) == "secret_pass_888"

    # 2. 自定义名称克隆
    cloned_custom = clone_env(env_id, EnvCloneIn(new_name="自定义克隆环境"), db=db)
    assert cloned_custom["name"] == "自定义克隆环境"



