# -*- coding: utf-8 -*-
"""App 环境管理 API（CRUD + APK 上传），密码永不回显。"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from insight_aitest.modules.mobile.backend.automation import paths
from insight_aitest.modules.mobile.backend.automation.app_service import (
    app_public,
    delete_password,
    set_password,
)
from insight_aitest.modules.mobile.backend.deps import get_mobile_db
from insight_aitest.modules.mobile.backend.persistence.database import MobileDatabase
from insight_aitest.modules.mobile.backend.persistence.models import MobilePlatform, ResetMode

router = APIRouter(prefix="/automation/apps", tags=["mobile-apps"])


class AppIn(BaseModel):
    project_id: int
    name: str = ""
    platform: str = MobilePlatform.ANDROID
    app_package: str
    app_activity: str = ""
    reset_mode: str = ResetMode.NO_RESET
    appium_url: str = "http://127.0.0.1:4723"
    test_username: str = ""
    password: str | None = None
    extra_caps: dict = {}
    is_default: bool = False


class AppPatch(BaseModel):
    name: str | None = None
    platform: str | None = None
    app_package: str | None = None
    app_activity: str | None = None
    reset_mode: str | None = None
    appium_url: str | None = None
    test_username: str | None = None
    password: str | None = None
    clear_password: bool = False
    extra_caps: dict | None = None
    is_default: bool | None = None


@router.get("")
def list_apps(
    project_id: int | None = Query(None),
    db: MobileDatabase = Depends(get_mobile_db),
) -> list[dict]:
    return [app_public(a) for a in db.list_apps(project_id)]


@router.post("", status_code=201)
def create_app(body: AppIn, db: MobileDatabase = Depends(get_mobile_db)) -> dict:
    if not body.app_package.strip():
        raise HTTPException(400, "app_package 不能为空")
    if body.platform not in MobilePlatform.ALL:
        raise HTTPException(400, "platform 仅支持 android 或 ios")
    if body.reset_mode not in ResetMode.ALL:
        raise HTTPException(400, "reset_mode 仅支持 no_reset 或 fast_reset")

    ref = uuid.uuid4().hex
    if body.password:
        set_password(ref, body.password)
    app_id = db.create_app(
        project_id=body.project_id,
        name=body.name.strip() or body.app_package.strip(),
        platform=body.platform,
        app_package=body.app_package.strip(),
        app_activity=body.app_activity.strip(),
        reset_mode=body.reset_mode,
        appium_url=(body.appium_url or "http://127.0.0.1:4723").strip(),
        test_username=body.test_username.strip(),
        password_ref=ref,
        extra_caps_json=dict(body.extra_caps or {}),
        is_default=1 if body.is_default else 0,
    )
    return app_public(db.get_app(app_id))


@router.put("/{app_id}")
def update_app(
    app_id: int, body: AppPatch, db: MobileDatabase = Depends(get_mobile_db)
) -> dict:
    app = db.get_app(app_id)
    if app is None:
        raise HTTPException(404, "App 环境不存在")
    fields = body.model_dump(exclude_none=True)
    fields.pop("clear_password", None)
    if body.clear_password and app.password_ref:
        delete_password(app.password_ref)
    pwd = fields.pop("password", None)
    if pwd:
        ref = app.password_ref or uuid.uuid4().hex
        set_password(ref, pwd)
        fields["password_ref"] = ref
    if "extra_caps" in fields:
        fields["extra_caps_json"] = fields.pop("extra_caps")
    if "is_default" in fields:
        fields["is_default"] = 1 if fields["is_default"] else 0
    updated = db.update_app(app_id, **fields)
    return app_public(updated)


@router.delete("/{app_id}")
def delete_app(app_id: int, db: MobileDatabase = Depends(get_mobile_db)) -> dict:
    app = db.get_app(app_id)
    if app is None:
        raise HTTPException(404, "App 环境不存在")
    if app.password_ref:
        delete_password(app.password_ref)
    db.delete_app(app_id)
    return {"deleted": app_id}


@router.post("/{app_id}/upload")
async def upload_package(
    app_id: int,
    file: UploadFile = File(...),
    db: MobileDatabase = Depends(get_mobile_db),
) -> dict:
    app = db.get_app(app_id)
    if app is None:
        raise HTTPException(404, "App 环境不存在")
    filename = Path(file.filename or "app.apk").name
    if not (filename.endswith(".apk") or filename.endswith(".ipa")):
        raise HTTPException(400, "仅支持上传 .apk 或 .ipa 安装包")

    target = paths.apps_dir(int(app.project_id)) / f"{app_id}_{filename}"
    content = await file.read()
    target.write_bytes(content)
    db.update_app(app_id, app_file_rel=paths.to_rel(target))
    return app_public(db.get_app(app_id))
