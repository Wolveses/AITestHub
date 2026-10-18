# -*- coding: utf-8 -*-
"""平台用户与认证模块导出。"""

from insight_aitest.platform.auth.database import UserDatabase
from insight_aitest.platform.auth.deps import get_current_user, get_current_user_optional, get_user_db, require_admin
from insight_aitest.platform.auth.models import User, UserRole
from insight_aitest.platform.auth.routes import router as auth_router

__all__ = [
    "User",
    "UserRole",
    "UserDatabase",
    "auth_router",
    "get_user_db",
    "get_current_user",
    "get_current_user_optional",
    "require_admin",
]

