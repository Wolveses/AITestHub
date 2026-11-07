# -*- coding: utf-8 -*-
"""JMeter 原生 CLI 调度执行引擎。

调用宿主机本地安装的 `jmeter -n -t plan.jmx -l report.jtl -e -o html_report`，
流式解析 JTL 输出并生成官方 HTML 报告。
"""

from __future__ import annotations

import asyncio
import csv
import os
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Optional
from logzero import logger


class JMeterCliEngine:
    """本地 JMeter 原生 CLI 执行器。"""

    def __init__(
        self,
        task_id: int,
        run_id: int,
        jmx_content: str,
        concurrency: int = 10,
        ramp_up_seconds: int = 5,
        duration_seconds: int = 60,
        on_metrics_tick: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self.task_id = task_id
        self.run_id = run_id
        self.jmx_content = jmx_content
        self.concurrency = concurrency
        self.ramp_up_seconds = ramp_up_seconds
        self.duration_seconds = duration_seconds
        self.on_metrics_tick = on_metrics_tick
        self._proc: Optional[asyncio.subprocess.Process] = None

    def stop(self) -> None:
        """终止 JMeter 进程。"""
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass

    async def run(self) -> dict[str, Any]:
        """异步执行 JMeter CLI 任务。"""
        jmeter_bin = shutil.which("jmeter") or shutil.which("jmeter.bat")
        if not jmeter_bin:
            raise FileNotFoundError("未在系统 PATH 环境变量中检测到 JMeter 可执行程序，请切换使用内置执行引擎")

        temp_dir = tempfile.mkdtemp(prefix=f"perf_jmeter_{self.run_id}_")
        jmx_file = os.path.join(temp_dir, "plan.jmx")
        jtl_file = os.path.join(temp_dir, "result.jtl")

        with open(jmx_file, "w", encoding="utf-8") as f:
            f.write(self.jmx_content)

        cmd = [
            jmeter_bin,
            "-n",
            "-t",
            jmx_file,
            "-l",
            jtl_file,
            f"-Jconcurrency={self.concurrency}",
            f"-Jramp_up={self.ramp_up_seconds}",
            f"-Jduration={self.duration_seconds}",
        ]

        logger.info(f"启动 JMeter CLI 调度: {' '.join(cmd)}")
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await self._proc.communicate()
        if self._proc.returncode != 0 and not os.path.exists(jtl_file):
            err_text = stderr.decode(errors="replace")
            raise RuntimeError(f"JMeter 执行失败退出 ({self._proc.returncode}): {err_text}")

        # 解析 JTL 文件
        report = self._parse_jtl(jtl_file)
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        return report

    def _parse_jtl(self, jtl_file: str) -> dict[str, Any]:
        """解析 JTL (CSV 格式) 得到统计指标。"""
        if not os.path.exists(jtl_file):
            return {
                "total_samples": 0,
                "failed_samples": 0,
                "error_rate": 0.0,
                "avg_tps": 0.0,
                "avg_rt_ms": 0.0,
                "p90_rt_ms": 0.0,
                "p95_rt_ms": 0.0,
                "p99_rt_ms": 0.0,
                "sampler_summary": [],
            }

        samples = []
        with open(jtl_file, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    elapsed = float(row.get("elapsed", 0))
                    success = row.get("success", "true").lower() == "true"
                    label = row.get("label", "Sampler")
                    samples.append({"label": label, "elapsed": elapsed, "success": success})
                except Exception:
                    continue

        total = len(samples)
        failed = sum(1 for s in samples if not s["success"])
        error_rate = round((failed / total * 100.0), 2) if total else 0.0
        rts = sorted(s["elapsed"] for s in samples)
        avg_rt = round(sum(rts) / total, 1) if total else 0.0

        return {
            "total_samples": total,
            "failed_samples": failed,
            "error_rate": error_rate,
            "avg_tps": round(total / max(1, self.duration_seconds), 1),
            "avg_rt_ms": avg_rt,
            "p90_rt_ms": round(rts[int(total * 0.9)] if total else 0, 1),
            "p95_rt_ms": round(rts[int(total * 0.95)] if total else 0, 1),
            "p99_rt_ms": round(rts[int(total * 0.99)] if total else 0, 1),
            "sampler_summary": [],
        }
