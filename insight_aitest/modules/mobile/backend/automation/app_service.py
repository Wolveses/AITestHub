# -*- coding: utf-8 -*-
"""App 环境配置辅助：密码脱敏存储（envs.json）与公共视图序列化。"""

from __future__ import annotations

import json
import threading

from insight_aitest.modules.mobile.backend.automation import paths

_SECRET_LOCK = threading.Lock()


def _read_secrets() -> dict:
    p = paths.env_secrets_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_secrets(data: dict) -> None:
    p = paths.env_secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass


def get_password(ref: str) -> str:
    if not ref:
        return ""
    with _SECRET_LOCK:
        return str(_read_secrets().get(ref, ""))


def set_password(ref: str, password: str) -> None:
    if not ref:
        return
    with _SECRET_LOCK:
        data = _read_secrets()
        data[ref] = password
        _write_secrets(data)


def delete_password(ref: str) -> None:
    if not ref:
        return
    with _SECRET_LOCK:
        data = _read_secrets()
        if ref in data:
            data.pop(ref)
            _write_secrets(data)


def app_public(app) -> dict:
    """App 环境配置的可回显字典（绝不包含密码明文）。"""
    pwd_set = bool(getattr(app, "password_ref", "") and get_password(app.password_ref))
    return {
        "id": app.id,
        "project_id": app.project_id,
        "name": app.name,
        "platform": app.platform,
        "app_package": app.app_package,
        "app_activity": app.app_activity,
        "app_file_rel": app.app_file_rel,
        "has_app_file": bool(app.app_file_rel and paths.resolve_rel(app.app_file_rel).exists()),
        "reset_mode": app.reset_mode,
        "appium_url": app.appium_url,
        "test_username": app.test_username,
        "password_set": pwd_set,
        "extra_caps": dict(app.extra_caps_json or {}),
        "is_default": bool(app.is_default),
        "created_at": app.created_at.isoformat() if app.created_at else None,
        "updated_at": app.updated_at.isoformat() if app.updated_at else None,
    }


def build_runtime_env_payload(app) -> dict:
    """构造注入给 pytest 脚手架的运行期环境信息（含账号密码，仅进程内部传参）。"""
    return {
        "app_id": app.id,
        "name": app.name,
        "platform": app.platform,
        "app_package": app.app_package,
        "app_activity": app.app_activity,
        "reset_mode": app.reset_mode,
        "test_username": app.test_username,
        "test_password": get_password(app.password_ref) if app.password_ref else "",
    }
