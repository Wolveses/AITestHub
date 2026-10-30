# -*- coding: utf-8 -*-
"""AI 自动化脚本数据模型（ui_cases / ui_envs / ui_generations）。

与旧 Midscene 表同库（ui.db），互不干扰：
- ui_cases：从知识库用例文档导入的自动化用例资产（快照式，后续不随源同步）；
- ui_envs：环境配置（主机地址 + 登录接口 + token 注入方式），密码不落库；
- ui_generations：每次生成/修复的尝试记录（含失败分类与工具日志路径）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column

from insight_aitest.platform.persistence import Base


class CaseStatus:
    """用例状态常量（用 TEXT 存储，不引入枚举迁移成本）。"""

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


class ErrorCategory:
    """失败四分类（前端展示与文案映射共用）。"""

    ENV = "environment"  # 环境问题：浏览器/MCP/登录/网络
    CASE = "case_info"  # 用例信息不完善
    MODEL = "model"  # 模型调用失败/输出不可解析
    SCRIPT = "script"  # 脚本缺陷（断言/定位/超时）


class Site:
    """被测系统的端：前台走 base_url 根路径，后台走 base_url + /manage。"""

    FRONTEND = "frontend"
    BACKEND = "backend"

    ALL = (FRONTEND, BACKEND)


class UiCase(MappedAsDataclass, Base, kw_only=True):
    """自动化用例资产（从知识库 kind=case 文档导入的快照）。"""

    __tablename__ = "ui_cases"
    __table_args__ = (
        UniqueConstraint("project_id", "kb_document_id", name="uq_ui_cases_project_doc"),
        Index("idx_ui_cases_project", "project_id"),
        Index("idx_ui_cases_status", "status"),
    )

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    project_id: Mapped[int] = mapped_column(Integer)
    kb_document_id: Mapped[int] = mapped_column(Integer)
    source_case_id: Mapped[str] = mapped_column(Text, default="")
    source_workspace_id: Mapped[str] = mapped_column(Text, default="")

    # 导入时的字段快照（后续不同步源用例，可由用户在详情里编辑）
    title: Mapped[str] = mapped_column(Text, default="")
    precondition: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[list] = mapped_column("steps_json", JSON, default_factory=list)
    expected: Mapped[str] = mapped_column(Text, default="")
    category_path: Mapped[str] = mapped_column(Text, default="")
    kb_folder_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # 端：frontend（根路径）/ backend（base_url + /manage），导入时按关键字推断，可手动改
    site: Mapped[str] = mapped_column(Text, default=Site.FRONTEND)

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


class UiEnv(MappedAsDataclass, Base, kw_only=True):
    """环境配置：被测系统地址 + 登录接口 + token 注入方式。

    password_ref 指向 ~/.insight_eye/ui/envs.json 里的密码键；
    接口只回 password_set 布尔值，任何场景都不返回明文密码。
    """

    __tablename__ = "ui_envs"
    __table_args__ = (Index("idx_ui_envs_project", "project_id"),)

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    project_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(Text, default="")
    login_api_path: Mapped[str] = mapped_column(Text, default="")
    login_method: Mapped[str] = mapped_column(Text, default="POST")
    username: Mapped[str] = mapped_column(Text, default="")
    password_ref: Mapped[str] = mapped_column(Text, default="")
    # token 在登录响应 JSON 中的路径，如 data.token / access_token
    token_json_path: Mapped[str] = mapped_column(Text, default="")
    token_inject: Mapped[str] = mapped_column(Text, default="cookie")  # cookie|header|localStorage
    token_name: Mapped[str] = mapped_column(Text, default="token")
    storage_state_rel: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


class UiGeneration(MappedAsDataclass, Base, kw_only=True):
    """一次生成/修复尝试（工具日志落盘，表里只存路径与摘要）。"""

    __tablename__ = "ui_generations"
    __table_args__ = (Index("idx_ui_generations_case", "ui_case_id"),)

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    ui_case_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text, default=GenerationKind.GENERATE)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(Text, default=GenerationStatus.RUNNING)
    error_category: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    log_rel_path: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
