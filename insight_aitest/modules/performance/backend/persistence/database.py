# -*- coding: utf-8 -*-
"""服务端性能测试持久化访问层。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import desc, select

from insight_aitest.modules.performance.backend.persistence.models import (
    PerfRun,
    PerfScript,
    PerfTask,
    PerfTaskScript,
)
from insight_aitest.platform.persistence import Base, ensure_schema, get_engine, session_scope


class PerfDatabase:
    """性能测试持久化数据库。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        engine = get_engine(db_path)
        Base.metadata.create_all(
            engine,
            tables=[
                PerfScript.__table__,
                PerfTask.__table__,
                PerfTaskScript.__table__,
                PerfRun.__table__,
            ],
        )
        ensure_schema(db_path, [])

    # ===== 脚本管理 (Scripts) =====
    def create_script(self, script: PerfScript) -> int:
        with session_scope(self.db_path) as session:
            session.add(script)
            session.flush()
            return script.id

    def get_script(self, script_id: int) -> Optional[PerfScript]:
        with session_scope(self.db_path) as session:
            stmt = select(PerfScript).where(PerfScript.id == script_id)
            return session.execute(stmt).scalar_one_or_none()

    def update_script(
        self,
        script_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        jmx_content: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> Optional[PerfScript]:
        with session_scope(self.db_path) as session:
            stmt = select(PerfScript).where(PerfScript.id == script_id)
            script = session.execute(stmt).scalar_one_or_none()
            if script is None:
                return None
            if name is not None:
                script.name = name
            if description is not None:
                script.description = description
            if jmx_content is not None:
                script.jmx_content = jmx_content
            if config is not None:
                script.config = config
            script.updated_at = datetime.now()
            session.flush()
            return script

    def list_scripts(
        self,
        project_id: Optional[int] = None,
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PerfScript], int]:
        with session_scope(self.db_path) as session:
            stmt = select(PerfScript)
            if project_id is not None:
                stmt = stmt.where(PerfScript.project_id == project_id)
            if keyword:
                kw = f"%{keyword}%"
                stmt = stmt.where(PerfScript.name.ilike(kw) | PerfScript.description.ilike(kw))

            # total
            all_items = session.execute(stmt).scalars().all()
            total = len(all_items)

            stmt = (
                stmt.order_by(desc(PerfScript.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = session.execute(stmt).scalars().all()
            return list(items), total

    def delete_script(self, script_id: int) -> bool:
        with session_scope(self.db_path) as session:
            stmt = select(PerfScript).where(PerfScript.id == script_id)
            script = session.execute(stmt).scalar_one_or_none()
            if not script:
                return False
            # 同时清理关联关系
            del_assoc = select(PerfTaskScript).where(PerfTaskScript.script_id == script_id)
            for assoc in session.execute(del_assoc).scalars().all():
                session.delete(assoc)
            session.delete(script)
            return True

    # ===== 任务管理 (Tasks) =====
    def create_task(self, task: PerfTask, script_ids: list[dict]) -> int:
        """创建任务并关联脚本配置 [{'script_id': 1, 'weight': 100}]."""
        with session_scope(self.db_path) as session:
            session.add(task)
            session.flush()
            for idx, item in enumerate(script_ids):
                assoc = PerfTaskScript(
                    task_id=task.id,
                    script_id=item["script_id"],
                    weight=item.get("weight", 100),
                    order_no=idx,
                )
                session.add(assoc)
            session.flush()
            return task.id

    def get_task(self, task_id: int) -> Optional[PerfTask]:
        with session_scope(self.db_path) as session:
            stmt = select(PerfTask).where(PerfTask.id == task_id)
            return session.execute(stmt).scalar_one_or_none()

    def get_task_scripts(self, task_id: int) -> list[dict]:
        with session_scope(self.db_path) as session:
            stmt = (
                select(PerfTaskScript, PerfScript)
                .join(PerfScript, PerfTaskScript.script_id == PerfScript.id)
                .where(PerfTaskScript.task_id == task_id)
                .order_by(PerfTaskScript.order_no)
            )
            results = session.execute(stmt).all()
            out = []
            for assoc, script in results:
                out.append(
                    {
                        "script_id": script.id,
                        "script_name": script.name,
                        "weight": assoc.weight,
                        "jmx_content": script.jmx_content,
                        "config": script.config,
                    }
                )
            return out

    def update_task(
        self,
        task_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        strategy_type: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        loop_count: Optional[int] = None,
        concurrency: Optional[int] = None,
        ramp_up_seconds: Optional[int] = None,
        engine_type: Optional[str] = None,
        script_items: Optional[list[dict]] = None,
    ) -> Optional[PerfTask]:
        with session_scope(self.db_path) as session:
            stmt = select(PerfTask).where(PerfTask.id == task_id)
            task = session.execute(stmt).scalar_one_or_none()
            if not task:
                return None
            if name is not None:
                task.name = name
            if description is not None:
                task.description = description
            if strategy_type is not None:
                task.strategy_type = strategy_type
            if duration_seconds is not None:
                task.duration_seconds = duration_seconds
            if loop_count is not None:
                task.loop_count = loop_count
            if concurrency is not None:
                task.concurrency = concurrency
            if ramp_up_seconds is not None:
                task.ramp_up_seconds = ramp_up_seconds
            if engine_type is not None:
                task.engine_type = engine_type
            task.updated_at = datetime.now()

            if script_items is not None:
                old_stmt = select(PerfTaskScript).where(PerfTaskScript.task_id == task_id)
                for old in session.execute(old_stmt).scalars().all():
                    session.delete(old)
                for idx, item in enumerate(script_items):
                    assoc = PerfTaskScript(
                        task_id=task_id,
                        script_id=item["script_id"],
                        weight=item.get("weight", 100),
                        order_no=idx,
                    )
                    session.add(assoc)

            session.flush()
            return task

    def list_tasks(
        self,
        project_id: Optional[int] = None,
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PerfTask], int]:
        with session_scope(self.db_path) as session:
            stmt = select(PerfTask)
            if project_id is not None:
                stmt = stmt.where(PerfTask.project_id == project_id)
            if keyword:
                kw = f"%{keyword}%"
                stmt = stmt.where(PerfTask.name.ilike(kw) | PerfTask.description.ilike(kw))

            all_items = session.execute(stmt).scalars().all()
            total = len(all_items)

            stmt = (
                stmt.order_by(desc(PerfTask.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = session.execute(stmt).scalars().all()
            return list(items), total

    def delete_task(self, task_id: int) -> bool:
        with session_scope(self.db_path) as session:
            stmt = select(PerfTask).where(PerfTask.id == task_id)
            task = session.execute(stmt).scalar_one_or_none()
            if not task:
                return False
            del_assoc = select(PerfTaskScript).where(PerfTaskScript.task_id == task_id)
            for assoc in session.execute(del_assoc).scalars().all():
                session.delete(assoc)
            session.delete(task)
            return True

    def update_task_status(
        self, task_id: int, status: str, run_id: Optional[int] = None
    ) -> None:
        with session_scope(self.db_path) as session:
            stmt = select(PerfTask).where(PerfTask.id == task_id)
            task = session.execute(stmt).scalar_one_or_none()
            if task:
                task.last_status = status
                if run_id:
                    task.last_run_id = run_id
                    task.last_run_at = datetime.now()

    # ===== 执行记录与测试报告 (Runs) =====
    def create_run(self, run: PerfRun) -> int:
        with session_scope(self.db_path) as session:
            session.add(run)
            session.flush()
            return run.id

    def get_run(self, run_id: int) -> Optional[PerfRun]:
        with session_scope(self.db_path) as session:
            stmt = select(PerfRun).where(PerfRun.id == run_id)
            return session.execute(stmt).scalar_one_or_none()

    def update_run_metrics(
        self,
        run_id: int,
        status: Optional[str] = None,
        total_samples: Optional[int] = None,
        failed_samples: Optional[int] = None,
        error_rate: Optional[float] = None,
        avg_tps: Optional[float] = None,
        avg_rt_ms: Optional[float] = None,
        p90_rt_ms: Optional[float] = None,
        p95_rt_ms: Optional[float] = None,
        p99_rt_ms: Optional[float] = None,
        timeline_metrics: Optional[list[dict]] = None,
        sampler_summary: Optional[list[dict]] = None,
        ended_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
    ) -> Optional[PerfRun]:
        with session_scope(self.db_path) as session:
            stmt = select(PerfRun).where(PerfRun.id == run_id)
            run = session.execute(stmt).scalar_one_or_none()
            if not run:
                return None
            if status is not None:
                run.status = status
            if total_samples is not None:
                run.total_samples = total_samples
            if failed_samples is not None:
                run.failed_samples = failed_samples
            if error_rate is not None:
                run.error_rate = error_rate
            if avg_tps is not None:
                run.avg_tps = avg_tps
            if avg_rt_ms is not None:
                run.avg_rt_ms = avg_rt_ms
            if p90_rt_ms is not None:
                run.p90_rt_ms = p90_rt_ms
            if p95_rt_ms is not None:
                run.p95_rt_ms = p95_rt_ms
            if p99_rt_ms is not None:
                run.p99_rt_ms = p99_rt_ms
            if timeline_metrics is not None:
                run.timeline_metrics = timeline_metrics
            if sampler_summary is not None:
                run.sampler_summary = sampler_summary
            if ended_at is not None:
                run.ended_at = ended_at
            if error_message is not None:
                run.error_message = error_message
            session.flush()
            return run

    def list_runs(
        self,
        project_id: Optional[int] = None,
        task_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PerfRun], int]:
        with session_scope(self.db_path) as session:
            stmt = select(PerfRun)
            if project_id is not None:
                stmt = stmt.where(PerfRun.project_id == project_id)
            if task_id is not None:
                stmt = stmt.where(PerfRun.task_id == task_id)

            all_items = session.execute(stmt).scalars().all()
            total = len(all_items)

            stmt = (
                stmt.order_by(desc(PerfRun.started_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = session.execute(stmt).scalars().all()
            return list(items), total
