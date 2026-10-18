# -*- coding: utf-8 -*-
"""用户管理数据库操作（UserDatabase）。

数据存储在 ~/.insight_eye/users.db（遵循平台 P0-1 架构）。
初始内置 admin / digibird@123 用户。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from insight_aitest.platform.persistence import Base, get_engine, session_scope
from insight_aitest.platform.auth.models import User, UserRole, AuditLog
from insight_aitest.platform.auth.security import hash_password

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "digibird@123"


class UserDatabase:
    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            base = os.path.expanduser("~/.insight_eye")
            os.makedirs(base, exist_ok=True)
            db_path = os.path.join(base, "users.db")
        self.db_path = db_path

        # 初始化建表
        Base.metadata.create_all(
            get_engine(db_path),
            tables=[User.__table__, AuditLog.__table__],
        )
        # 确保内置管理员存在
        self._ensure_default_admin()

    def _ensure_default_admin(self) -> None:
        """确保系统内置管理员 admin 账号存在。"""
        with session_scope(self.db_path) as s:
            admin = s.scalar(select(User).where(User.username == DEFAULT_ADMIN_USERNAME))
            if admin is None:
                admin = User(
                    username=DEFAULT_ADMIN_USERNAME,
                    display_name="超级管理员",
                    password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                    role=UserRole.ADMIN,
                    is_active=True,
                )
                s.add(admin)

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        with session_scope(self.db_path) as s:
            return s.get(User, user_id)

    def get_user_by_username(self, username: str) -> Optional[User]:
        with session_scope(self.db_path) as s:
            return s.scalar(select(User).where(User.username == username))

    def create_user(
        self,
        username: str,
        password: str,
        display_name: str = "",
        role: UserRole = UserRole.TESTER,
    ) -> User:
        """注册新用户。如果账号已存在则抛出 ValueError。"""
        with session_scope(self.db_path) as s:
            existing = s.scalar(select(User).where(User.username == username))
            if existing is not None:
                raise ValueError(f"用户账号 '{username}' 已存在")

            user = User(
                username=username,
                password_hash=hash_password(password),
                display_name=display_name or username,
                role=role,
                is_active=True,
            )
            s.add(user)
            s.flush()
            user_id = user.id

        # 在 session 结束后重新通过 get 获取纯净实体
        return self.get_user_by_id(user_id)

    def list_users(self) -> list[User]:
        """获取所有用户列表（按创建时间排序）。"""
        with session_scope(self.db_path) as s:
            stmt = select(User).order_by(User.id.asc())
            return list(s.scalars(stmt))

    def update_password(self, user_id: int, new_password: str) -> bool:
        """修改指定用户的密码。"""
        with session_scope(self.db_path) as s:
            user = s.get(User, user_id)
            if user is None:
                return False
            user.password_hash = hash_password(new_password)
            user.updated_at = datetime.now()
            return True

    def reset_admin_password(self, new_password: str = DEFAULT_ADMIN_PASSWORD) -> bool:
        """CLI 或应急入口：重置 admin 密码。"""
        with session_scope(self.db_path) as s:
            admin = s.scalar(select(User).where(User.username == DEFAULT_ADMIN_USERNAME))
            if admin is None:
                admin = User(
                    username=DEFAULT_ADMIN_USERNAME,
                    display_name="超级管理员",
                    password_hash=hash_password(new_password),
                    role=UserRole.ADMIN,
                    is_active=True,
                )
                s.add(admin)
            else:
                admin.password_hash = hash_password(new_password)
                admin.is_active = True
                admin.updated_at = datetime.now()
            return True

    def toggle_user_active(self, user_id: int, is_active: bool) -> bool:
        """管理员启停账号（admin 不允许停用）。"""
        with session_scope(self.db_path) as s:
            user = s.get(User, user_id)
            if user is None or user.username == DEFAULT_ADMIN_USERNAME:
                return False
            user.is_active = is_active
            user.updated_at = datetime.now()
            return True

    def update_display_name(self, user_id: int, display_name: str) -> bool:
        """更新显示名称。"""
        with session_scope(self.db_path) as s:
            user = s.get(User, user_id)
            if user is None:
                return False
            user.display_name = display_name
            user.updated_at = datetime.now()
            return True

    # ===== 审计日志操作 =====

    def log_action(
        self,
        action: str,
        user_id: int | None = None,
        username: str = "anonymous",
        target_type: str = "",
        target_id: str = "",
        detail: str = "",
        client_ip: str = "",
        status_code: int = 200,
    ) -> AuditLog:
        """记录一条操作日志。"""
        with session_scope(self.db_path) as s:
            log = AuditLog(
                user_id=user_id,
                username=username,
                action=action,
                target_type=target_type,
                target_id=str(target_id),
                detail=detail,
                client_ip=client_ip,
                status_code=status_code,
            )
            s.add(log)
            s.flush()
            log_id = log.id

        with session_scope(self.db_path) as s:
            return s.get(AuditLog, log_id)

    def list_audit_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        username: str | None = None,
        action: str | None = None,
        target_type: str | None = None,
    ) -> tuple[list[AuditLog], int]:
        """查询审计日志列表，支持分页和多重筛选，返回 (logs, total)。"""
        from sqlalchemy import func

        with session_scope(self.db_path) as s:
            stmt = select(AuditLog)
            count_stmt = select(func.count(AuditLog.id))

            if username:
                stmt = stmt.where(AuditLog.username.like(f"%{username}%"))
                count_stmt = count_stmt.where(AuditLog.username.like(f"%{username}%"))
            if action:
                stmt = stmt.where(AuditLog.action == action)
                count_stmt = count_stmt.where(AuditLog.action == action)
            if target_type:
                stmt = stmt.where(AuditLog.target_type == target_type)
                count_stmt = count_stmt.where(AuditLog.target_type == target_type)

            total = s.scalar(count_stmt) or 0
            stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit)
            logs = list(s.scalars(stmt))
            return logs, total
