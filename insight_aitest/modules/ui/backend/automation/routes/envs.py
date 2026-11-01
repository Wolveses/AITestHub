# -*- coding: utf-8 -*-
"""环境管理 API：仅地址 + 用户名 + 密码（登录协议写死在 env_service），密码不回显。"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from insight_aitest.modules.ui.backend.automation.database import UIAutomationDatabase
from insight_aitest.modules.ui.backend.automation.deps import get_automation_db
from insight_aitest.modules.ui.backend.automation.env_service import (
    AUTH_SCRIPT_TEMPLATES,
    delete_password,
    env_public,
    set_password,
    test_env,
)

router = APIRouter(prefix="/automation/envs", tags=["ui-automation"])


class EnvIn(BaseModel):
    project_id: int
    name: str = ""
    base_url: str
    username: str = ""
    password: str | None = None
    auth_script: str = ""
    token_inject: str = "cookie"
    token_name: str = "token"
    token_prefix: str = ""
    is_default: bool = False


class EnvPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    username: str | None = None
    password: str | None = None
    auth_script: str | None = None
    token_inject: str | None = None
    token_name: str | None = None
    token_prefix: str | None = None
    clear_password: bool = False
    is_default: bool | None = None


class EnvTestPayload(BaseModel):
    base_url: str | None = None
    username: str | None = None
    password: str | None = None
    auth_script: str | None = None
    token_inject: str | None = None
    token_name: str | None = None
    token_prefix: str | None = None


@router.get("/templates")
def list_script_templates() -> list[dict]:
    """返回常用前置脚本模板列表。"""
    return AUTH_SCRIPT_TEMPLATES


@router.get("")
def list_envs(
    project_id: int | None = Query(None),
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> list[dict]:
    return [env_public(e) for e in db.list_envs(project_id)]


@router.post("")
def create_env(body: EnvIn, db: UIAutomationDatabase = Depends(get_automation_db)) -> dict:
    if not body.base_url.strip():
        raise HTTPException(400, "base_url 不能为空")
    ref = uuid.uuid4().hex
    if body.password:
        set_password(ref, body.password)
    env_id = db.create_env(
        project_id=body.project_id,
        name=body.name.strip() or body.base_url.strip(),
        base_url=body.base_url.strip(),
        username=body.username.strip(),
        password_ref=ref,
        auth_script=body.auth_script or "",
        token_inject=body.token_inject or "cookie",
        token_name=body.token_name or "token",
        token_prefix=body.token_prefix or "",
        is_default=1 if body.is_default else 0,
    )
    return env_public(db.get_env(env_id))


@router.put("/{env_id}")
def update_env(
    env_id: int, body: EnvPatch, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    env = db.get_env(env_id)
    if env is None:
        raise HTTPException(404, "环境不存在")
    fields = body.model_dump(exclude_none=True)
    fields.pop("clear_password", None)
    if body.clear_password and env.password_ref:
        delete_password(env.password_ref)
    elif body.password:
        ref = env.password_ref or uuid.uuid4().hex
        set_password(ref, body.password)
        fields["password_ref"] = ref
    fields.pop("password", None)
    if "is_default" in fields:
        fields["is_default"] = 1 if fields["is_default"] else 0
    db.update_env(env_id, **fields)
    return env_public(db.get_env(env_id))


@router.delete("/{env_id}")
def delete_env(env_id: int, db: UIAutomationDatabase = Depends(get_automation_db)) -> dict:
    env = db.get_env(env_id)
    if env is None:
        raise HTTPException(404, "环境不存在")
    if env.password_ref:
        delete_password(env.password_ref)
    db.delete_env(env_id)
    return {"deleted": env_id}


@router.post("/test-custom")
async def test_custom_env(body: EnvTestPayload) -> dict:
    """对表单中填写的临时环境与前置脚本进行调试与连通性测试。"""
    class _TempEnv:
        id = 0
        project_id = 0
        name = "temp"
        base_url = body.base_url or ""
        username = body.username or ""
        password_ref = ""
        auth_script = body.auth_script or ""
        token_inject = body.token_inject or "cookie"
        token_name = body.token_name or "token"
        token_prefix = body.token_prefix or ""

    overrides = body.model_dump(exclude_none=True)
    return await asyncio.to_thread(test_env, _TempEnv(), overrides)


@router.post("/{env_id}/test")
async def test_connection(
    env_id: int,
    body: EnvTestPayload | None = None,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    env = db.get_env(env_id)
    if env is None:
        raise HTTPException(404, "环境不存在")
    overrides = body.model_dump(exclude_none=True) if body else None
    return await asyncio.to_thread(test_env, env, overrides)
