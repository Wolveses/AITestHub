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

