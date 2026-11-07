# -*- coding: utf-8 -*-
"""内置轻量高并发压测执行引擎（AsyncIO Engine）。

无需 Java 与 JMeter 环境，直接解析 JMX 步骤并调度并发协程进行高负载施压。
具备完整的实时指标聚合计算（秒级时序切片、TPS、RT 分位值、错误率）。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from typing import Any, Callable, Optional

import httpx
from logzero import logger

from insight_aitest.modules.performance.backend.services.jmx_parser import JmxParser


class SampleResult:
    """单次请求执行结果。"""

    def __init__(
        self,
        sampler_name: str,
        status_code: int,
        elapsed_ms: float,
        success: bool,
        error_msg: str | None = None,
    ) -> None:
        self.sampler_name = sampler_name
        self.status_code = status_code
        self.elapsed_ms = elapsed_ms
        self.success = success
        self.error_msg = error_msg
        self.timestamp = time.time()


class AsyncPerfEngine:
    """基于 AsyncIO 的高性能并发施压引擎。"""

    def __init__(
        self,
        task_id: int,
        run_id: int,
        script_items: list[dict[str, Any]],  # [{"jmx_content": ..., "weight": 100}]
        concurrency: int = 10,
        ramp_up_seconds: int = 5,
        duration_seconds: int = 60,
        loop_count: int = 1,
        strategy_type: str = "duration",
        on_metrics_tick: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self.task_id = task_id
        self.run_id = run_id
        self.script_items = script_items
        self.concurrency = max(1, concurrency)
        self.ramp_up_seconds = max(0, ramp_up_seconds)
        self.duration_seconds = max(1, duration_seconds)
        self.loop_count = loop_count
        self.strategy_type = strategy_type
        self.on_metrics_tick = on_metrics_tick

        self._stop_event = asyncio.Event()
        self._samples: list[SampleResult] = []
        self._lock = asyncio.Lock()
        self._running = False

    def stop(self) -> None:
        """优雅停止施压。"""
        self._stop_event.set()

    async def run(self) -> dict[str, Any]:
        """执行性能压测主协程。"""
        self._running = True
        start_time = time.time()
        logger.info(
            f"启动内置并发压测引擎 task={self.task_id} run={self.run_id} 并发={self.concurrency}"
        )

        # 1. 解析参与压测的全部 JMX 步骤
        parsed_scenarios = []
        for item in self.script_items:
            jmx = item.get("jmx_content", "")
            if not jmx:
                continue
            parsed = JmxParser.parse(jmx)
            weight = max(1, int(item.get("weight", 100)))
            parsed_scenarios.append({"steps": parsed.get("steps", []), "weight": weight})

        if not parsed_scenarios:
            raise ValueError("没有可执行的有效脚本场景")

        # 启动后台实时指标推送任务
        metrics_collector_task = asyncio.create_task(self._metric_reporting_loop(start_time))

        # 2. 协程并发工作池
        workers = []
        delay_per_worker = (
            (self.ramp_up_seconds / self.concurrency) if self.ramp_up_seconds > 0 else 0
        )

        async with httpx.AsyncClient(
            verify=False,
            timeout=10.0,
            limits=httpx.Limits(max_connections=500, max_keepalive_connections=200),
        ) as client:
            for worker_id in range(self.concurrency):
                start_delay = worker_id * delay_per_worker
                w_task = asyncio.create_task(
                    self._worker_loop(worker_id, client, parsed_scenarios, start_delay)
                )
                workers.append(w_task)

            # 等待所有 worker 结束或触发停止
            await asyncio.gather(*workers, return_exceptions=True)

        self._running = False
        metrics_collector_task.cancel()
        try:
            await metrics_collector_task
        except asyncio.CancelledError:
            pass

        # 3. 计算最终全量聚合指标报告
        return self._calc_final_report(start_time)

    async def _worker_loop(
        self,
        worker_id: int,
        client: httpx.AsyncClient,
        scenarios: list[dict],
        start_delay: float,
    ) -> None:
        if start_delay > 0:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=start_delay)
                return  # 如果等待期间被中止
            except asyncio.TimeoutError:
                pass

        loop_idx = 0
        while not self._stop_event.is_set():
            if self.strategy_type == "loops" and loop_idx >= self.loop_count:
                break
            loop_idx += 1

            # 轮询或权重随机选择一个 scenario
            scenario = scenarios[worker_id % len(scenarios)]
            steps = scenario.get("steps", [])

            # 上下文变量字典（每次迭代独立，模拟独立用户会话）
            context_vars: dict[str, Any] = {}

            for step in steps:
                if self._stop_event.is_set():
                    break
                await self._execute_step(client, step, context_vars)

    async def _execute_step(
        self,
        client: httpx.AsyncClient,
        step: dict[str, Any],
        context_vars: dict[str, Any],
    ) -> None:
        name = step.get("name") or step.get("path") or "Sampler"
        method = step.get("method", "GET").upper()
        url = self._replace_vars(step.get("url") or step.get("path") or "", context_vars)
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"http://{url}"

        headers = {
            k: self._replace_vars(str(v), context_vars)
            for k, v in step.get("headers", {}).items()
        }

        body = step.get("body")
        content = None
        if body is not None and body != "":
            body_str = self._replace_vars(
                json.dumps(body) if isinstance(body, (dict, list)) else str(body),
                context_vars,
            )
            content = body_str.encode("utf-8")
            if not any(k.lower() == "content-type" for k in headers):
                headers["Content-Type"] = "application/json"

        t0 = time.perf_counter()
        status_code = 0
        success = True
        err_msg = None
        resp_text = ""

        try:
            resp = await client.request(method, url, headers=headers, content=content)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            status_code = resp.status_code
            resp_text = resp.text
            if status_code >= 400:
                success = False
                err_msg = f"HTTP {status_code}"
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            success = False
            err_msg = str(exc)

        # 提取变量
        if success and status_code and resp_text:
            for v_name, jp_expr in step.get("extract", {}).items():
                val = self._extract_jsonpath(resp_text, jp_expr)
                if val is not None:
                    context_vars[v_name] = val

        # 记录样本
        sample = SampleResult(name, status_code, elapsed_ms, success, err_msg)
        async with self._lock:
            self._samples.append(sample)

    async def _metric_reporting_loop(self, start_time: float) -> None:
        """每秒聚合一次指标并向外推送。"""
        last_calc_index = 0
        while self._running:
            await asyncio.sleep(1.0)
            now = time.time()
            if self.strategy_type == "duration" and (now - start_time) >= self.duration_seconds:
                self.stop()
                break

            async with self._lock:
                current_samples = self._samples[last_calc_index:]
                last_calc_index = len(self._samples)

            sec_total = len(current_samples)
            sec_failed = sum(1 for s in current_samples if not s.success)
            sec_rt = [s.elapsed_ms for s in current_samples]
            avg_rt = (sum(sec_rt) / sec_total) if sec_total else 0.0

            tick_metric = {
                "timestamp": int(now),
                "elapsed_sec": int(now - start_time),
                "threads": self.concurrency if not self._stop_event.is_set() else 0,
                "tps": round(sec_total / 1.0, 1),
                "avg_rt": round(avg_rt, 1),
                "failed": sec_failed,
            }

            if self.on_metrics_tick:
                try:
                    self.on_metrics_tick(tick_metric)
                except Exception:
                    pass

    def _calc_final_report(self, start_time: float) -> dict[str, Any]:
        """计算全量指标矩阵。"""
        total_duration = max(0.1, time.time() - start_time)
        samples = self._samples
        total = len(samples)
        failed = sum(1 for s in samples if not s.success)
        error_rate = round((failed / total * 100.0), 2) if total else 0.0
        avg_tps = round(total / total_duration, 1)

        rts = sorted(s.elapsed_ms for s in samples)
        avg_rt = round(sum(rts) / total, 1) if total else 0.0
        p90 = round(self._percentile(rts, 90), 1)
        p95 = round(self._percentile(rts, 95), 1)
        p99 = round(self._percentile(rts, 99), 1)

        # Sampler 维度统计汇总
        sampler_map: dict[str, list[SampleResult]] = {}
        for s in samples:
            sampler_map.setdefault(s.sampler_name, []).append(s)

        sampler_summary = []
        for s_name, s_list in sampler_map.items():
            s_tot = len(s_list)
            s_fail = sum(1 for s in s_list if not s.success)
            s_rts = sorted(s.elapsed_ms for s in s_list)
            sampler_summary.append(
                {
                    "sampler_name": s_name,
                    "samples": s_tot,
                    "failed": s_fail,
                    "error_rate": f"{round(s_fail / s_tot * 100, 1)}%",
                    "tps": round(s_tot / total_duration, 1),
                    "avg_rt_ms": round(sum(s_rts) / s_tot, 1) if s_tot else 0,
                    "min_rt_ms": round(s_rts[0], 1) if s_rts else 0,
                    "max_rt_ms": round(s_rts[-1], 1) if s_rts else 0,
                    "p95_rt_ms": round(self._percentile(s_rts, 95), 1),
                }
            )

        return {
            "total_samples": total,
            "failed_samples": failed,
            "error_rate": error_rate,
            "avg_tps": avg_tps,
            "avg_rt_ms": avg_rt,
            "p90_rt_ms": p90,
            "p95_rt_ms": p95,
            "p99_rt_ms": p99,
            "duration_actual": round(total_duration, 1),
            "sampler_summary": sampler_summary,
        }

    @staticmethod
    def _percentile(sorted_data: list[float], percent: int) -> float:
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * (percent / 100.0)
        f = int(k)
        c = f + 1
        if c < len(sorted_data):
            return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])
        return sorted_data[f]

    @staticmethod
    def _replace_vars(text: str, variables: dict[str, Any]) -> str:
        if not text:
            return text

        def repl(match):
            key = match.group(1) or match.group(2)
            return str(variables.get(key, match.group(0)))

        return re.sub(r"\$\{([^}]+)\}|\{\{([^}]+)\}\}", repl, text)

    @staticmethod
    def _extract_jsonpath(text: str, expr: str) -> Any:
        try:
            from jsonpath_ng import parse

            data = json.loads(text)
            matches = [m.value for m in parse(expr).find(data)]
            return matches[0] if matches else None
        except Exception:
            return None
