# -*- coding: utf-8 -*-
"""用户数据模型（平台级共享）。

User 存储在 ~/.insight_eye/platform.db（或 users.db）中。
角色：admin (系统管理员) / tester (普通测试工程师)。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column

from insight_aitest.platform.persistence import Base
from insight_aitest.platform.persistence.types import enum_values


class UserRole(str, Enum):
    ADMIN = "admin"
    TESTER = "tester"


class User(MappedAsDataclass, Base):
    """平台用户表。"""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, init=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, values_callable=enum_values), default=UserRole.TESTER
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
