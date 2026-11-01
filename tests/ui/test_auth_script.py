# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock
from insight_aitest.modules.ui.backend.automation.env_service import (
    execute_auth_script,
    _handle_script_result,
    prepare_auth,
    _sanitize_error,
)

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

def test_valid_token_string():
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

    auth = _handle_script_result(env, res, "http://test.com")
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

    auth = _handle_script_result(env, res, "http://test.com")
    assert auth.ok
    assert auth.token == "tok_999"
    assert auth.headers.get("Authorization") == "Bearer tok_999"
    assert auth.storage_state_path

