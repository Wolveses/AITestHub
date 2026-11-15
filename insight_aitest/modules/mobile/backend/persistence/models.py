# -*- coding: utf-8 -*-
"""手机 App 自动化模块数据模型（mobile_apps / mobile_cases / mobile_generations / mobile_runs / mobile_lessons）。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SAEnum, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column

from insight_aitest.platform.persistence import Base
from insight_aitest.platform.persistence.types import enum_values


class MobilePlatform:
    ANDROID = "android"
    IOS = "ios"

    ALL = (ANDROID, IOS)


class ResetMode:
    NO_RESET = "no_reset"
    FAST_RESET = "fast_reset"

    ALL = (NO_RESET, FAST_RESET)


class CaseStatus:
    NOT_IMPLEMENTED = "not_implemented"
    GENERATING = "generating"
    IMPLEMENTED = "implemented"
    FIXING = "fixing"
    RUNNING = "running"


class GenerationKind:
    GENERATE = "generate"
    FIX = "fix"


class GenerationStatus:
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorCategory:
    ENV = "environment"
    CASE = "case_info"
    MODEL = "model"
    SCRIPT = "script"


class RunStatus(Enum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class MobileApp(MappedAsDataclass, Base, kw_only=True):
    """App 应用与测试环境配置。"""

    __tablename__ = "mobile_apps"
    __table_args__ = (Index("idx_mobile_apps_project", "project_id"),)

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    project_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[str] = mapped_column(Text, default=MobilePlatform.ANDROID)
    app_package: Mapped[str] = mapped_column(Text, default="")
    app_activity: Mapped[str] = mapped_column(Text, default="")
    app_file_rel: Mapped[str] = mapped_column(Text, default="")
    reset_mode: Mapped[str] = mapped_column(Text, default=ResetMode.NO_RESET)
    appium_url: Mapped[str] = mapped_column(Text, default="http://127.0.0.1:4723")
    test_username: Mapped[str] = mapped_column(Text, default="")
    password_ref: Mapped[str] = mapped_column(Text, default="")
    extra_caps_json: Mapped[dict] = mapped_column(JSON, default_factory=dict)
    is_default: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


class MobileCase(MappedAsDataclass, Base, kw_only=True):
    """App 自动化用例资产（从知识库 kind=case 文档导入的快照）。"""

    __tablename__ = "mobile_cases"
    __table_args__ = (
        UniqueConstraint("project_id", "kb_document_id", name="uq_mobile_cases_project_doc"),
        Index("idx_mobile_cases_project", "project_id"),
        Index("idx_mobile_cases_status", "status"),
    )

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    project_id: Mapped[int] = mapped_column(Integer)
    kb_document_id: Mapped[int] = mapped_column(Integer)
    source_case_id: Mapped[str] = mapped_column(Text, default="")
    source_workspace_id: Mapped[str] = mapped_column(Text, default="")

    title: Mapped[str] = mapped_column(Text, default="")
    precondition: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[list] = mapped_column("steps_json", JSON, default_factory=list)
    expected: Mapped[str] = mapped_column(Text, default="")
    category_path: Mapped[str] = mapped_column(Text, default="")
    kb_folder_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    platform: Mapped[str] = mapped_column(Text, default=MobilePlatform.ANDROID)
    default_app_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    params_json: Mapped[dict] = mapped_column("params_json", JSON, default_factory=dict)
    params_schema_json: Mapped[list] = mapped_column("params_schema_json", JSON, default_factory=list)
    params_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )

    status: Mapped[str] = mapped_column(Text, default=CaseStatus.NOT_IMPLEMENTED)
    script_rel_path: Mapped[str] = mapped_column(Text, default="")
    script_version: Mapped[int] = mapped_column(Integer, default=0)
    script_hash: Mapped[str] = mapped_column(Text, default="")
    last_error_category: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    last_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    last_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


class MobileGeneration(MappedAsDataclass, Base, kw_only=True):
    """一次脚本生成/修复会话记录。"""

    __tablename__ = "mobile_generations"
    __table_args__ = (Index("idx_mobile_generations_case", "mobile_case_id"),)

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    mobile_case_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text, default=GenerationKind.GENERATE)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(Text, default=GenerationStatus.RUNNING)
    engine_type: Mapped[str] = mapped_column(Text, default="local_agent")
    engine_detail: Mapped[str] = mapped_column(Text, default="remote_mcp")
    device_id: Mapped[str] = mapped_column(Text, default="")
    app_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    session_token_hash: Mapped[str] = mapped_column(Text, default="")

    error_category: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    log_rel_path: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    last_dry_run_passed: Mapped[int] = mapped_column(Integer, default=0)
    last_dry_run_hash: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


class MobileRun(MappedAsDataclass, Base, kw_only=True):
    """App 自动化单次执行历史。"""

    __tablename__ = "mobile_runs"
    __table_args__ = (
        Index("idx_mobile_runs_case", "case_id"),
        Index("idx_mobile_runs_status", "status"),
    )

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    case_id: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    app_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    case_title: Mapped[str] = mapped_column(Text, default="")
    case_snapshot: Mapped[dict] = mapped_column(JSON, default_factory=dict)
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, values_callable=enum_values), default=RunStatus.RUNNING
    )
    runner: Mapped[str] = mapped_column(Text, default="script")  # script | dry_run
    device_id: Mapped[str] = mapped_column(Text, default="")
    device_model: Mapped[str] = mapped_column(Text, default="")
    os_version: Mapped[str] = mapped_column(Text, default="")
    script_version: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    artifacts_rel_path: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


class MobileLesson(MappedAsDataclass, Base, kw_only=True):
    """移动端避坑错题库。"""

    __tablename__ = "mobile_lessons"
    __table_args__ = (
        UniqueConstraint("project_id", "fingerprint", name="uq_mobile_lessons_fp"),
        Index("idx_mobile_lessons_project", "project_id"),
    )

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    project_id: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
