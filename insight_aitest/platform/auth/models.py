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


class AuditLog(MappedAsDataclass, Base):
    """用户操作审计日志表。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, init=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # CREATE / UPDATE / DELETE / LOGIN 等
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    username: Mapped[str] = mapped_column(Text, default="anonymous")
    target_type: Mapped[str] = mapped_column(Text, default="")  # user / conversation / task / project / kb 等
    target_id: Mapped[str] = mapped_column(Text, default="")  # 操作对象ID
    detail: Mapped[str] = mapped_column(Text, default="")  # 操作描述或参数详情
    client_ip: Mapped[str] = mapped_column(Text, default="")  # 客户端IP
    status_code: Mapped[int] = mapped_column(Integer, default=200)  # HTTP响应状态或结果状态
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
