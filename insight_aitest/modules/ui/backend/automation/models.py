# -*- coding: utf-8 -*-
"""AI 自动化脚本数据模型（ui_cases / ui_envs / ui_generations / ui_lessons）。

与旧 Midscene 表同库（ui.db），互不干扰：
- ui_cases：从知识库用例文档导入的自动化用例资产（快照式，后续不随源同步）；
- ui_envs：环境配置（主机地址 + 登录接口 + token 注入方式），密码不落库；
- ui_generations：每次生成/修复的尝试记录（含失败分类、工具日志路径与 token 消耗指标）；
- ui_lessons：反面样本（错题库），把失败日志/踩坑/解决方案沉淀为可注入的片段。
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


class CaseSource:
    """脚本来处：平台内 AI 生成 / 本地 Agent 编写后提交。"""

    AI = "ai"
    LOCAL_AGENT = "local_agent"


class AuthoringStage:
    """本地 Agent 编写脚本的校验状态机。"""

    NONE = ""
    VALIDATED = "validated"  # L1/L2 通过，30 分钟内可 dry_run/submit
    DRY_RUN_OK = "dry_run_ok"  # 本地试跑通过，24 小时内可 submit


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

    # 本用例的参数值（{name: value}）与参数结构（[{name,label,type,...}]）
    params_json: Mapped[dict] = mapped_column("params_json", JSON, default_factory=dict)
    params_schema_json: Mapped[list] = mapped_column("params_schema_json", JSON, default_factory=list)
    params_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )

    status: Mapped[str] = mapped_column(Text, default=CaseStatus.NOT_IMPLEMENTED)
    script_rel_path: Mapped[str] = mapped_column(Text, default="")
    script_version: Mapped[int] = mapped_column(Integer, default=0)
    script_hash: Mapped[str] = mapped_column(Text, default="")
    # 脚本来处：ai（平台内生成）/ local_agent（本地 Agent 通过 MCP 提交）
    source: Mapped[str] = mapped_column(Text, default=CaseSource.AI)
    authoring_by: Mapped[str] = mapped_column(Text, default="")
    authoring_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    last_error_category: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    last_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    last_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


class UiEnv(MappedAsDataclass, Base, kw_only=True):
    """环境配置：被测系统地址 + 前置获取 token 脚本 + token 注入方式。

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
    # 用户自定义前置获取 token 的 Python 脚本（入口函数 def get_token(base_url, username, password)）
    auth_script: Mapped[str] = mapped_column(Text, default="")
    # token 在登录响应 JSON 中的路径，如 data.token / access_token
    token_json_path: Mapped[str] = mapped_column(Text, default="")
    token_inject: Mapped[str] = mapped_column(Text, default="cookie")  # cookie|header|localStorage|custom
    token_name: Mapped[str] = mapped_column(Text, default="token")
    token_prefix: Mapped[str] = mapped_column(Text, default="")
    storage_state_rel: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[int] = mapped_column(Integer, default=0)
    # 是否允许本地 Agent 通过 MCP 获取该环境的认证信息（关闭后 env.get 直接拒绝）
    allow_local_agent: Mapped[int] = mapped_column(Integer, default=1)
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
    # 可观测指标：语料命中字符、发送给模型的字符、模型回复字符、失败修复轮次
    corpus_chars: Mapped[int] = mapped_column(Integer, default=0)
    prompt_chars: Mapped[int] = mapped_column(Integer, default=0)
    completion_chars: Mapped[int] = mapped_column(Integer, default=0)
    fix_rounds: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


class UiLesson(MappedAsDataclass, Base, kw_only=True):
    """反面样本（错题库）：失败日志 / 踩过的坑 / 解决方案。

    体积约束由 lessons.py 负责：单条截断、每项目限量、注入 top N 且总量封顶。
    """

    __tablename__ = "ui_lessons"
    __table_args__ = (
        UniqueConstraint("project_id", "fingerprint", name="uq_ui_lessons_fp"),
        Index("idx_ui_lessons_project", "project_id"),
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


class McpToken(MappedAsDataclass, Base, kw_only=True):
    """本地 Agent 访问平台 MCP 的静态 Bearer Token（只存哈希，明文只在创建时返回一次）。"""

    __tablename__ = "ui_mcp_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_ui_mcp_tokens_hash"),
        Index("idx_ui_mcp_tokens_project", "project_id"),
    )

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    project_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text, default="本地 Agent")
    token_hash: Mapped[str] = mapped_column(Text, default="")
    token_prefix: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


class AuthoringState(MappedAsDataclass, Base, kw_only=True):
    """每个用例当前轮本地编写的校验状态（哈希 + 阶段 + 租约 + 冷却）。"""

    __tablename__ = "ui_authoring_states"

    case_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    project_id: Mapped[int] = mapped_column(Integer, default=0)
    source_hash: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[str] = mapped_column(Text, default=AuthoringStage.NONE)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    dry_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    last_error: Mapped[str] = mapped_column(Text, default="")
    lease_owner: Mapped[str] = mapped_column(Text, default="")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


class AuthoringEvent(MappedAsDataclass, Base, kw_only=True):
    """本地编写的进度事件（前端 SSE/轮询回显用）。"""

    __tablename__ = "ui_authoring_events"
    __table_args__ = (Index("idx_ui_authoring_events_case", "case_id", "id"),)

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    case_id: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default_factory=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
