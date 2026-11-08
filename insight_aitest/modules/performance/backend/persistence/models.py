# -*- coding: utf-8 -*-
"""服务端性能测试持久化数据模型（perf_scripts / perf_tasks / perf_task_scripts / perf_runs）。

用于支持：
1. JMeter 脚本资产管理（JMX 内容、由 AI 方案挑选生成的接口编排与依赖信息）；
2. 性能测试任务（多脚本组合编排、权重、并发数、运行时长或循环次数策略）；
3. 性能测试执行历史与测试报告（聚合 TPS、RT 耗时分布、时序指标）。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Float, Integer, JSON, Text, DateTime, Index
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column

from insight_aitest.platform.persistence import Base


class StrategyType(str, Enum):
    DURATION = "duration"
    LOOPS = "loops"


class EngineType(str, Enum):
    BUILTIN = "builtin"
    JMETER_CLI = "jmeter_cli"


class TaskRunStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class PerfScript(MappedAsDataclass, Base, kw_only=True):
    """JMeter 性能脚本资产表。"""

    __tablename__ = "perf_scripts"
    __table_args__ = (Index("idx_perf_scripts_project", "project_id"),)

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    project_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    plan_description: Mapped[str] = mapped_column(Text, default="")

    # 结构化编排信息（JSON）：选取的 asset_ids, steps(接口顺序, extract, inject), concurrency 等
    config: Mapped[dict] = mapped_column("config_json", JSON, default_factory=dict)

    # 完整的标准 JMX XML 内容文本
    jmx_content: Mapped[str] = mapped_column(Text, default="")

    # 关联的接口资产 ID 列表
    asset_ids: Mapped[list[int]] = mapped_column("asset_ids_json", JSON, default_factory=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


class PerfTask(MappedAsDataclass, Base, kw_only=True):
    """性能测试任务表。"""

    __tablename__ = "perf_tasks"
    __table_args__ = (Index("idx_perf_tasks_project", "project_id"),)

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    project_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")

    # 调度策略：duration (按时长, 秒) 或 loops (按循环次数)
    strategy_type: Mapped[str] = mapped_column(Text, default="duration")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=60)
    loop_count: Mapped[int] = mapped_column(Integer, default=1)

    # 并发及加压控制
    concurrency: Mapped[int] = mapped_column(Integer, default=10)
    ramp_up_seconds: Mapped[int] = mapped_column(Integer, default=5)

    # 引擎类型：jmeter_cli (本地原生JMeter，优先默认) 或 builtin (Python轻量备用)
    engine_type: Mapped[str] = mapped_column(Text, default="jmeter_cli")

    # 执行模式：local (本机单机执行，默认) 或 distributed (Master调度Slave分布式执行)
    exec_mode: Mapped[str] = mapped_column(Text, default="local")
    # 分布式模式下选中的从机IP/地址列表（形如 "192.168.1.101:1099,192.168.1.102:1099"）
    slave_hosts: Mapped[str] = mapped_column(Text, default="")

    last_status: Mapped[str] = mapped_column(Text, default="idle")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    last_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)


class PerfTaskScript(MappedAsDataclass, Base, kw_only=True):
    """任务与脚本多对多关联及权重配置。"""

    __tablename__ = "perf_task_scripts"
    __table_args__ = (
        Index("idx_perf_task_scripts_task", "task_id"),
        Index("idx_perf_task_scripts_script", "script_id"),
    )

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    task_id: Mapped[int] = mapped_column(Integer)
    script_id: Mapped[int] = mapped_column(Integer)
    weight: Mapped[int] = mapped_column(Integer, default=100)
    order_no: Mapped[int] = mapped_column(Integer, default=0)


class PerfRun(MappedAsDataclass, Base, kw_only=True):
    """任务与场景执行记录与测试报告表。"""

    __tablename__ = "perf_runs"
    __table_args__ = (
        Index("idx_perf_runs_task", "task_id"),
        Index("idx_perf_runs_script", "script_id"),
        Index("idx_perf_runs_project", "project_id"),
    )

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    script_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    project_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="running")

    engine_used: Mapped[str] = mapped_column(Text, default="builtin")
    exec_mode: Mapped[str] = mapped_column(Text, default="local")
    slave_hosts: Mapped[str] = mapped_column(Text, default="")
    concurrency_actual: Mapped[int] = mapped_column(Integer, default=0)
    total_samples: Mapped[int] = mapped_column(Integer, default=0)
    failed_samples: Mapped[int] = mapped_column(Integer, default=0)
    error_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_tps: Mapped[float] = mapped_column(Float, default=0.0)
    avg_rt_ms: Mapped[float] = mapped_column(Float, default=0.0)
    p90_rt_ms: Mapped[float] = mapped_column(Float, default=0.0)
    p95_rt_ms: Mapped[float] = mapped_column(Float, default=0.0)
    p99_rt_ms: Mapped[float] = mapped_column(Float, default=0.0)

    # 每秒时序指标数据（[{"timestamp": ..., "threads": 10, "tps": 52.3, "rt": 45, "errors": 0}]）
    timeline_metrics: Mapped[list[dict]] = mapped_column(
        "timeline_metrics_json", JSON, default_factory=list
    )
    # 按接口维度的统计报表
    sampler_summary: Mapped[list[dict]] = mapped_column(
        "sampler_summary_json", JSON, default_factory=list
    )
    # 结构化 JTL 样本明细行（前数千条）
    jtl_rows: Mapped[list[dict]] = mapped_column(
        "jtl_rows_json", JSON, default_factory=list
    )
    # 原始 JTL 文件内容文本（CSV 格式）
    jtl_content: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    # 运行时控制台完整输出文本
    console_output: Mapped[str | None] = mapped_column(Text, nullable=True, default="")

    started_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)


class PerfSlaveNode(MappedAsDataclass, Base, kw_only=True):
    """分布式 JMeter Slave 从机节点池管理表。"""

    __tablename__ = "perf_slave_nodes"
    __table_args__ = (
        Index("idx_perf_slave_nodes_project", "project_id"),
    )

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    name: Mapped[str] = mapped_column(Text)
    host: Mapped[str] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer, default=1099)
    status: Mapped[str] = mapped_column(Text, default="offline")  # online, offline, busy
    description: Mapped[str] = mapped_column(Text, default="")
    cpu_cores: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    memory_gb: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
