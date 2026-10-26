# -*- coding: utf-8 -*-
"""用户认证与管理路由（/api/platform/auth）。"""

from __future__ import annotations

from typing import List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status

from insight_aitest.platform.auth.database import UserDatabase
from insight_aitest.platform.auth.deps import get_current_user, get_user_db, require_admin
from insight_aitest.platform.auth.models import User, UserRole
from insight_aitest.platform.auth.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["platform-auth"])


# ===== Pydantic Schemas =====

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, description="用户登录账号")
    display_name: str = Field(..., min_length=1, max_length=50, description="显示名称")
    password: str = Field(..., min_length=6, max_length=100, description="登录密码")


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=100)


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=100)


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=50)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    created_at: str

    @classmethod
    def from_orm(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            is_active=user.is_active,
            created_at=user.created_at.isoformat() if user.created_at else "",
        )


class LoginResponse(BaseModel):
    token: str
    user: UserOut


class AuditLogOut(BaseModel):
    id: int
    user_id: int | None = None
    username: str
    action: str
    target_type: str
    target_id: str
    detail: str
    client_ip: str
    status_code: int
    created_at: str


class AuditLogListResponse(BaseModel):
    items: List[AuditLogOut]
    total: int


# ===== 路由接口 =====

@router.post("/register", response_model=LoginResponse)
def register(req: RegisterRequest, db: UserDatabase = Depends(get_user_db)):
    """测试人员自行注册接口。"""
    username = req.username.strip()
    display_name = req.display_name.strip()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="账号与密码不能为空")

    try:
        user = db.create_user(
            username=username,
            password=req.password,
            display_name=display_name,
            role=UserRole.TESTER,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    token = create_access_token({"sub": user.id, "username": user.username, "role": user.role.value})
    return LoginResponse(token=token, user=UserOut.from_orm(user))


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: UserDatabase = Depends(get_user_db)):
    """用户登录接口。"""
    username = req.username.strip()
    user = db.get_user_by_username(username)
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="该账号已被停用，请联系管理员")

    token = create_access_token({"sub": user.id, "username": user.username, "role": user.role.value})
    return LoginResponse(token=token, user=UserOut.from_orm(user))


@router.get("/me", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return UserOut.from_orm(user)


@router.put("/me", response_model=UserOut)
def update_me(
    req: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: UserDatabase = Depends(get_user_db),
):
    """更新个人显示名称。"""
    db.update_display_name(user.id, req.display_name.strip())
    updated = db.get_user_by_id(user.id)
    return UserOut.from_orm(updated or user)


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: UserDatabase = Depends(get_user_db),
):
    """用户个人修改密码。"""
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")

    db.update_password(user.id, req.new_password)
    return {"message": "密码修改成功，请使用新密码重新登录"}


# ===== 管理员专属接口 =====

@router.get("/users", response_model=List[UserOut])
def list_users(
    admin: User = Depends(require_admin),
    db: UserDatabase = Depends(get_user_db),
):
    """管理员查看用户列表。"""
    users = db.list_users()
    return [UserOut.from_orm(u) for u in users]


@router.post("/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: int,
    req: AdminResetPasswordRequest,
    admin: User = Depends(require_admin),
    db: UserDatabase = Depends(get_user_db),
):
    """管理员重置任意用户密码。"""
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    db.update_password(user_id, req.new_password)
    return {"message": f"用户 {target.username} 的密码已重置成功"}


@router.post("/users/{user_id}/toggle-active")
def admin_toggle_active(
    user_id: int,
    active: bool,
    admin: User = Depends(require_admin),
    db: UserDatabase = Depends(get_user_db),
):
    """管理员启停用户账号。"""
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标用户不存在")
    if target.username == "admin":
        raise HTTPException(status_code=400, detail="系统管理员账号不允许停用")

    db.toggle_user_active(user_id, active)
    action_text = "启用" if active else "停用"
    return {"message": f"用户 {target.username} 已成功{action_text}"}


@router.get("/audit-logs", response_model=AuditLogListResponse)
def list_audit_logs(
    limit: int = 50,
    offset: int = 0,
    username: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    admin: User = Depends(require_admin),
    db: UserDatabase = Depends(get_user_db),
):
    """管理员查看用户操作审计日志。"""
    logs, total = db.list_audit_logs(
        limit=limit,
        offset=offset,
        username=username,
        action=action,
        target_type=target_type,
    )
    return AuditLogListResponse(
        items=[
            AuditLogOut(
                id=log.id,
                user_id=log.user_id,
                username=log.username,
                action=log.action,
                target_type=log.target_type,
                target_id=log.target_id,
                detail=log.detail,
                client_ip=log.client_ip,
                status_code=log.status_code,
                created_at=log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "",
            )
            for log in logs
        ],
        total=total,
    )

