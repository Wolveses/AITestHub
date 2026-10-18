# -*- coding: utf-8 -*-
"""用户认证依赖注入（FastAPI Dependencies）。"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from insight_aitest.platform.auth.database import UserDatabase
from insight_aitest.platform.auth.models import User, UserRole
from insight_aitest.platform.auth.security import decode_access_token

_user_db: UserDatabase | None = None
security_bearer = HTTPBearer(auto_error=False)


def get_user_db() -> UserDatabase:
    global _user_db
    if _user_db is None:
        base = os.path.expanduser("~/.insight_eye")
        _user_db = UserDatabase(os.path.join(base, "users.db"))
    return _user_db


def get_current_user_optional(
    auth: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    db: UserDatabase = Depends(get_user_db),
) -> Optional[User]:
    """获取当前登录用户（可选，若未登录返回 None）。"""
    if not auth or not auth.credentials:
        return None
    token = auth.credentials
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    user_id = payload["sub"]
    user = db.get_user_by_id(user_id)
    if not user or not user.is_active:
        return None
    return user


def get_current_user(
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    """强制要求登录。若未提供或 Token 无效返回 401。"""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录系统",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """强制要求管理员角色，否则返回 403。"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足，仅管理员可执行此操作",
        )
    return user

