# -*- coding: utf-8 -*-
"""UI 自动化任务管理数据模型（ui_tasks / ui_task_cases / ui_task_runs）。

用于支持：
1. UI 自动化任务配置（任务名、执行环境、定时 Cron 表达式及启用开关）；
2. 任务关联用例（同一任务同一用例防重）；
3. 任务执行记录（手动执行/定时触发的批次历史与测试报告快照）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column

from insight_aitest.platform.persistence import Base


class TaskStatus:
    """任务与任务运行状态常量。"""

    IDLE = "idle"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    CANCELLED = "cancelled"


class TriggerType:
    """触发类型。"""

    MANUAL = "manual"
    CRON = "cron"


class UiTask(MappedAsDataclass, Base, kw_only=True):
    """UI 自动化任务表。"""

    __tablename__ = "ui_tasks"
    __table_args__ = (
        Index("idx_ui_tasks_project", "project_id"),
        Index("idx_ui_tasks_cron", "cron_enabled"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, init=False
    )
    project_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    env_id: Mapped[int] = mapped_column(Integer)
    cron_expression: Mapped[str] = mapped_column(Text, default="")
    cron_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_status: Mapped[str] = mapped_column(Text, default=TaskStatus.IDLE)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    last_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


class UiTaskCase(MappedAsDataclass, Base, kw_only=True):
    """任务关联用例表（同一任务、同一用例唯一约束）。"""

    __tablename__ = "ui_task_cases"
    __table_args__ = (
        UniqueConstraint("task_id", "case_id", name="uq_ui_task_cases_task_case"),
        Index("idx_ui_task_cases_task", "task_id"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, init=False
    )
    task_id: Mapped[int] = mapped_column(Integer)
    case_id: Mapped[int] = mapped_column(Integer)
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


class UiTaskRun(MappedAsDataclass, Base, kw_only=True):
    """任务运行历史与测试报告记录。"""

    __tablename__ = "ui_task_runs"
    __table_args__ = (
        Index("idx_ui_task_runs_task", "task_id"),
        Index("idx_ui_task_runs_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, init=False
    )
    task_id: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[int] = mapped_column(Integer)
    env_id: Mapped[int] = mapped_column(Integer)
    trigger_type: Mapped[str] = mapped_column(Text, default=TriggerType.MANUAL)
    status: Mapped[str] = mapped_column(Text, default=TaskStatus.RUNNING)
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    passed_cases: Mapped[int] = mapped_column(Integer, default=0)
    failed_cases: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[str] = mapped_column(Text, default="[]")
    error_message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
