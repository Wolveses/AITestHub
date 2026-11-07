# -*- coding: utf-8 -*-
"""性能测试任务执行调度管理器。

协调后台压测任务的启动、引擎实例化、实时时序指标收集与状态终态落库。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from logzero import logger

from insight_aitest.modules.performance.backend.engine.async_engine import AsyncPerfEngine
from insight_aitest.modules.performance.backend.engine.jmeter_engine import JMeterCliEngine
from insight_aitest.modules.performance.backend.persistence.database import PerfDatabase
from insight_aitest.modules.performance.backend.persistence.models import PerfRun


class TaskExecutorManager:
    """任务执行管理器（全局单例）。"""

    def __init__(self) -> None:
        self._active_engines: dict[int, Any] = {}  # run_id -> engine
        self._timeline_buffers: dict[int, list[dict]] = {}  # run_id -> timeline

    def stop_run(self, run_id: int) -> bool:
        engine = self._active_engines.get(run_id)
        if engine:
            engine.stop()
            return True
        return False

    async def execute_task(
        self,
        task_id: int,
        run_id: int,
        perf_db: PerfDatabase,
    ) -> None:
        """异步执行后台压测任务。"""
        task = perf_db.get_task(task_id)
        if not task:
            logger.error(f"Task {task_id} 不存在")
            return

        task_scripts = perf_db.get_task_scripts(task_id)
        if not task_scripts:
            perf_db.update_run_metrics(
                run_id, status="failed", error_message="任务未关联任何有效压测脚本"
            )
            perf_db.update_task_status(task_id, "failed", run_id)
            return

        self._timeline_buffers[run_id] = []

        def on_tick(metric: dict[str, Any]) -> None:
            buf = self._timeline_buffers.get(run_id)
            if buf is not None:
                buf.append(metric)

        engine_type = task.engine_type or "builtin"
        engine: Any = None

        if engine_type == "jmeter_cli":
            # 取首个脚本的 JMX
            primary_jmx = task_scripts[0]["jmx_content"]
            engine = JMeterCliEngine(
                task_id=task_id,
                run_id=run_id,
                jmx_content=primary_jmx,
                concurrency=task.concurrency,
                ramp_up_seconds=task.ramp_up_seconds,
                duration_seconds=task.duration_seconds,
                on_metrics_tick=on_tick,
            )
        else:
            engine = AsyncPerfEngine(
                task_id=task_id,
                run_id=run_id,
                script_items=task_scripts,
                concurrency=task.concurrency,
                ramp_up_seconds=task.ramp_up_seconds,
                duration_seconds=task.duration_seconds,
                loop_count=task.loop_count,
                strategy_type=task.strategy_type,
                on_metrics_tick=on_tick,
            )

        self._active_engines[run_id] = engine

        try:
            perf_db.update_task_status(task_id, "running", run_id)
            report = await engine.run()
            timeline = self._timeline_buffers.get(run_id, [])

            perf_db.update_run_metrics(
                run_id=run_id,
                status="completed",
                total_samples=report.get("total_samples", 0),
                failed_samples=report.get("failed_samples", 0),
                error_rate=report.get("error_rate", 0.0),
                avg_tps=report.get("avg_tps", 0.0),
                avg_rt_ms=report.get("avg_rt_ms", 0.0),
                p90_rt_ms=report.get("p90_rt_ms", 0.0),
                p95_rt_ms=report.get("p95_rt_ms", 0.0),
                p99_rt_ms=report.get("p99_rt_ms", 0.0),
                timeline_metrics=timeline,
                sampler_summary=report.get("sampler_summary", []),
                ended_at=datetime.now(),
            )
            perf_db.update_task_status(task_id, "completed", run_id)
        except Exception as exc:
            logger.exception(f"压测任务执行异常 task={task_id} run={run_id}: {exc}")
            perf_db.update_run_metrics(
                run_id=run_id,
                status="failed",
                error_message=str(exc),
                ended_at=datetime.now(),
            )
            perf_db.update_task_status(task_id, "failed", run_id)
        finally:
            self._active_engines.pop(run_id, None)
            self._timeline_buffers.pop(run_id, None)


_executor_manager = TaskExecutorManager()


def get_executor_manager() -> TaskExecutorManager:
    return _executor_manager
