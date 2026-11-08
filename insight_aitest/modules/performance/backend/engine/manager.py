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
    """任务与场景执行管理器（全局单例）。"""

    def __init__(self) -> None:
        self._active_engines: dict[int, Any] = {}  # run_id -> engine
        self._timeline_buffers: dict[int, list[dict]] = {}  # run_id -> timeline
        self._log_buffers: dict[int, list[str]] = {}  # run_id -> log lines
        self._subscribers: dict[int, list[asyncio.Queue]] = {}  # run_id -> queues

    def stop_run(self, run_id: int) -> bool:
        engine = self._active_engines.get(run_id)
        if engine:
            self._emit_log(run_id, f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 收到用户手动停止指令，正在停止执行...")
            engine.stop()
            return True
        return False

    def _emit_log(self, run_id: int, text: str) -> None:
        buf = self._log_buffers.setdefault(run_id, [])
        buf.append(text)
        subs = self._subscribers.get(run_id, [])
        for q in subs:
            try:
                q.put_nowait({"type": "log", "text": text})
            except Exception:
                pass

    def subscribe_logs(self, run_id: int) -> tuple[list[str], asyncio.Queue]:
        q: asyncio.Queue = asyncio.Queue()
        existing = list(self._log_buffers.get(run_id, []))
        subs = self._subscribers.setdefault(run_id, [])
        subs.append(q)
        return existing, q

    def unsubscribe_logs(self, run_id: int, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(run_id)
        if subs and q in subs:
            subs.remove(q)
            if not subs:
                self._subscribers.pop(run_id, None)

    def get_run_logs(self, run_id: int) -> list[str]:
        return list(self._log_buffers.get(run_id, []))

    async def execute_script(
        self,
        script_id: int,
        run_id: int,
        perf_db: PerfDatabase,
        engine_type: str = "jmeter_cli",
        env_base_url: str = "",
        exec_mode: str = "local",
        slave_hosts: str = "",
    ) -> None:
        """异步执行单脚本/测试场景，按照脚本原生定义执行并实时流式输出控制台日志与 JTL 报告。"""
        from datetime import datetime
        from insight_aitest.modules.performance.backend.services.jmx_parser import JmxParser

        script = perf_db.get_script(script_id)
        if not script or not script.jmx_content:
            err = "场景或 JMX 内容不存在"
            self._emit_log(run_id, f"[ERROR] {err}")
            perf_db.update_run_metrics(
                run_id, status="failed", error_message=err, ended_at=datetime.now()
            )
            return

        self._log_buffers[run_id] = []
        self._timeline_buffers[run_id] = []
        now_str = datetime.now().strftime("%H:%M:%S")

        self._emit_log(run_id, f"============================================================")
        self._emit_log(run_id, f"[{now_str}] 🚀 启动性能测试场景执行 #{run_id}")
        self._emit_log(run_id, f"[{now_str}] 场景名称: {script.name} (ID: {script_id})")
        self._emit_log(run_id, f"[{now_str}] 执行模式: 按照脚本内容原生配置执行 (引擎: {engine_type})")
        if env_base_url:
            self._emit_log(run_id, f"[{now_str}] 目标环境地址: {env_base_url} (同步覆盖 HTTP Request Defaults 与 HTTP Request)")
        self._emit_log(run_id, f"============================================================")

        jmx_to_run = script.jmx_content
        if env_base_url:
            jmx_to_run = JmxParser.override_base_url(jmx_to_run, env_base_url)

        def on_tick(metric: dict[str, Any]) -> None:
            buf = self._timeline_buffers.get(run_id)
            if buf is not None:
                buf.append(metric)

        def on_log(text: str) -> None:
            self._emit_log(run_id, text)

        engine: Any = None
        if engine_type == "jmeter_cli":
            engine = JMeterCliEngine(
                task_id=0,
                run_id=run_id,
                jmx_content=jmx_to_run,
                exec_mode=exec_mode,
                slave_hosts=slave_hosts,
                on_metrics_tick=on_tick,
                on_log=on_log,
            )
        else:
            cfg = script.config or {}
            script_concurrency = cfg.get("concurrency", 1)
            script_duration = cfg.get("duration", 10)
            engine = AsyncPerfEngine(
                task_id=0,
                run_id=run_id,
                script_items=[{"jmx_content": jmx_to_run, "weight": 100}],
                concurrency=script_concurrency,
                ramp_up_seconds=min(5, max(1, script_duration // 3)),
                duration_seconds=script_duration,
                loop_count=1,
                strategy_type="duration" if script_duration > 0 else "loops",
                on_metrics_tick=on_tick,
            )

        self._active_engines[run_id] = engine

        try:
            perf_db.update_run_metrics(run_id=run_id, status="running")
            report = await engine.run()
            timeline = self._timeline_buffers.get(run_id, [])
            console_log_text = "\n".join(self._log_buffers.get(run_id, []))

            final_status = "completed"
            if getattr(engine, "_stopped", False) or report.get("stopped"):
                final_status = "stopped"

            perf_db.update_run_metrics(
                run_id=run_id,
                status=final_status,
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
                jtl_rows=report.get("jtl_rows", []),
                jtl_content=report.get("jtl_content", ""),
                console_output=console_log_text,
                ended_at=datetime.now(),
            )
            self._emit_log(run_id, f"============================================================")
            if final_status == "stopped":
                self._emit_log(run_id, f"[{datetime.now().strftime('%H:%M:%S')}] ⏹ 性能测试已由用户手动停止，已落库阶段性指标。")
            else:
                self._emit_log(run_id, f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 性能测试执行成功完成！执行记录与 JTL 报表已落库。")
            self._emit_log(run_id, f"============================================================")
            subs = self._subscribers.get(run_id, [])
            for q in subs:
                try:
                    q.put_nowait({"type": "done", "status": final_status, "run_id": run_id})
                except Exception:
                    pass
        except Exception as exc:
            logger.exception(f"执行脚本异常 script={script_id} run={run_id}: {exc}")
            self._emit_log(run_id, f"[ERROR] 执行异常退出: {exc}")
            console_log_text = "\n".join(self._log_buffers.get(run_id, []))
            perf_db.update_run_metrics(
                run_id=run_id,
                status="failed",
                error_message=str(exc),
                console_output=console_log_text,
                ended_at=datetime.now(),
            )
            subs = self._subscribers.get(run_id, [])
            for q in subs:
                try:
                    q.put_nowait({"type": "done", "status": "failed", "run_id": run_id, "error": str(exc)})
                except Exception:
                    pass
        finally:
            self._active_engines.pop(run_id, None)

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

        engine_type = task.engine_type or "jmeter_cli"
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
                exec_mode=getattr(task, "exec_mode", "local") or "local",
                slave_hosts=getattr(task, "slave_hosts", "") or "",
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
