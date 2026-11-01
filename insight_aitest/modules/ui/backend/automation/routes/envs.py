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
    get_project_auth_script,
    set_project_auth_script,
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


class ProjectAuthScriptIn(BaseModel):
    auth_script: str


class ProjectAuthScriptTestPayload(BaseModel):
    env_id: int | None = None
    base_url: str | None = None
    username: str | None = None
    password: str | None = None
    auth_script: str | None = None


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


@router.get("/projects/{project_id}/auth-script")
def get_project_script(
    project_id: int,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    """获取项目级统一前置获取 Token 脚本。"""
    script = get_project_auth_script(project_id)
    if not script:
        # 兼容老数据：从该项目下已有的环境中寻找曾保存过的脚本
        envs = db.list_envs(project_id)
        for e in envs:
            if getattr(e, "auth_script", "").strip():
                script = e.auth_script.strip()
                break
    # 若依然为空，返回默认模板
    if not script and AUTH_SCRIPT_TEMPLATES:
        script = AUTH_SCRIPT_TEMPLATES[0]["code"]

    return {
        "project_id": project_id,
        "auth_script": script,
        "has_script": bool(get_project_auth_script(project_id)),
    }


@router.put("/projects/{project_id}/auth-script")
def update_project_script(
    project_id: int,
    body: ProjectAuthScriptIn,
) -> dict:
    """保存项目级统一前置获取 Token 脚本。"""
    set_project_auth_script(project_id, body.auth_script)
    return {
        "project_id": project_id,
        "auth_script": body.auth_script,
        "saved": True,
    }


@router.post("/projects/{project_id}/auth-script/test")
async def test_project_script(
    project_id: int,
    body: ProjectAuthScriptTestPayload,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    """调试项目级前置脚本（可选用已有环境的账号，或临时覆盖参数）。"""
    target_env = None
    if body.env_id:
        target_env = db.get_env(body.env_id)

    if target_env is None:
        # 若未指定或找不到，尝试取默认环境，若无则使用临时环境
        target_env = db.default_env(project_id)

    if target_env is None:
        class _TempEnv:
            pass
        target_env = _TempEnv()
        target_env.id = 0
        target_env.project_id = project_id
        target_env.name = "临时调试环境"
        target_env.base_url = body.base_url or ""
        target_env.username = body.username or ""
        target_env.password_ref = ""
        target_env.token_inject = "cookie"
        target_env.token_name = "token"
        target_env.token_prefix = ""

    overrides = body.model_dump(exclude_none=True)
    if body.auth_script:
        overrides["auth_script"] = body.auth_script

    return await asyncio.to_thread(test_env, target_env, overrides)

