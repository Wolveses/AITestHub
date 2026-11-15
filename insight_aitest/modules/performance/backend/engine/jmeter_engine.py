# -*- coding: utf-8 -*-
"""JMeter 原生 CLI 调度执行引擎。

调用宿主机本地安装的 `jmeter -n -t plan.jmx -l report.jtl -e -o html_report`，
流式解析 JTL 输出并生成官方 HTML 报告。
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Optional
from logzero import logger

from insight_aitest.modules.performance.backend.services.jmx_parser import JmxParser


class JMeterCliEngine:
    """本地 JMeter 原生 CLI 执行器。"""

    def __init__(
        self,
        task_id: int,
        run_id: int,
        jmx_content: str,
        concurrency: Optional[int] = None,
        ramp_up_seconds: Optional[int] = None,
        duration_seconds: Optional[int] = None,
        custom_properties: Optional[dict[str, Any]] = None,
        exec_mode: str = "local",
        slave_hosts: str = "",
        on_metrics_tick: Optional[Callable[[dict[str, Any]], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.task_id = task_id
        self.run_id = run_id
        self.jmx_content = jmx_content
        self.concurrency = concurrency
        self.ramp_up_seconds = ramp_up_seconds
        self.duration_seconds = duration_seconds
        self.custom_properties = dict(custom_properties or {})
        self.exec_mode = exec_mode or "local"
        self.slave_hosts = (slave_hosts or "").strip()
        self.on_metrics_tick = on_metrics_tick
        self.on_log = on_log
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._stopped: bool = False

    def _emit_log(self, text: str) -> None:
        if self.on_log:
            try:
                self.on_log(text)
            except Exception:
                pass

    def stop(self) -> None:
        """终止 JMeter 进程。"""
        self._stopped = True
        if self._proc:
            try:
                pid = self._proc.pid
                if os.name == "nt":
                    # Windows 下彻底终止整个进程树 (包含 jmeter.bat 与下游 java.exe)
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True,
                        check=False,
                    )
                else:
                    self._proc.terminate()
                self._emit_log("[SYSTEM] 已向 JMeter 发送终止信号并清理进程树")
            except Exception as exc:
                self._emit_log(f"[WARN] 终止进程失败: {exc}")

    async def run(self) -> dict[str, Any]:
        """异步执行 JMeter CLI 任务并实时输出控制台日志。"""
        import time
        from datetime import datetime

        self._stopped = False
        self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] 正在准备 JMeter 执行环境...")
        jmeter_bin = shutil.which("jmeter") or shutil.which("jmeter.bat")
        if not jmeter_bin:
            jmeter_home = os.environ.get("JMETER_HOME") or r"D:\apache-jmeter-5.6.3"
            candidate = os.path.join(jmeter_home, "bin", "jmeter.bat")
            if os.path.isfile(candidate):
                jmeter_bin = candidate
        if not jmeter_bin:
            err = "未在系统 PATH 环境变量中检测到 JMeter 可执行程序，请检查 JMETER_HOME 配置"
            self._emit_log(f"[ERROR] {err}")
            raise FileNotFoundError(err)

        self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] 找到 JMeter 运行程序: {jmeter_bin}")
        temp_dir = tempfile.mkdtemp(prefix=f"perf_jmeter_{self.run_id}_")
        jmx_file = os.path.join(temp_dir, "plan.jmx")
        jtl_file = os.path.join(temp_dir, "result.jtl")

        jmx_to_execute = JmxParser.parameterize_thread_group(self.jmx_content)
        jmx_to_execute = JmxParser.adjust_thread_group_for_properties(jmx_to_execute, self.custom_properties)
        with open(jmx_file, "w", encoding="utf-8") as f:
            f.write(jmx_to_execute)

        self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] 生成临时 JMX 方案文件: {jmx_file}")

        cmd = [
            jmeter_bin,
            "-n",
            "-t",
            jmx_file,
            "-l",
            jtl_file,
        ]

        is_distributed = (self.exec_mode == "distributed" and bool(self.slave_hosts))
        prop_prefix = "-G" if is_distributed else "-J"

        if is_distributed:
            self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] 启用分布式集群压测模式，Master 调度远程从机: {self.slave_hosts}")
            cmd.extend(["-R", self.slave_hosts, "-X"])
            cmd.append("-Jserver.rmi.ssl.disable=true")
        else:
            self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] 启用本地单机压测模式 (Master 本机施压)")

        # 动态透传自定义参数 (支持用户脚本中任意 __P、__property、props.get 属性)
        # 统一由脚本动态参数全面控制并发、时长、预热及业务变量，不再写死硬编码兜底参数
        for prop_name, prop_val in (self.custom_properties or {}).items():
            if prop_name and prop_val is not None and str(prop_val).strip() != "":
                clean_name = str(prop_name).strip()
                clean_val = str(prop_val).strip()
                cmd.append(f"{prop_prefix}{clean_name}={clean_val}")

        cmd_display = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] 启动命令行调度: {cmd_display}")
        logger.info(f"启动 JMeter CLI 调度: {cmd_display}")

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_stream(stream: Optional[asyncio.StreamReader], is_err: bool = False):
            if not stream:
                return
            while True:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break
                line_str = line_bytes.decode(errors="replace").rstrip()
                if line_str:
                    prefix = "[STDERR] " if is_err else ""
                    self._emit_log(f"{prefix}{line_str}")

        await asyncio.gather(
            read_stream(self._proc.stdout, False),
            read_stream(self._proc.stderr, True),
        )
        await self._proc.wait()

        self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] JMeter 执行结束，退出码: {self._proc.returncode}")

        if self._stopped:
            self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ 测试已被用户手动停止")
            if os.path.exists(jtl_file):
                report = self._parse_jtl(jtl_file)
            else:
                report = {
                    "total_samples": 0,
                    "failed_samples": 0,
                    "error_rate": 0.0,
                    "avg_tps": 0.0,
                    "avg_rt_ms": 0.0,
                    "min_rt_ms": 0.0,
                    "max_rt_ms": 0.0,
                    "p90_rt_ms": 0.0,
                    "p95_rt_ms": 0.0,
                    "p99_rt_ms": 0.0,
                    "sampler_summary": [],
                    "jtl_rows": [],
                    "jtl_content": "",
                }
            report["stopped"] = True
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
            return report

        if self._proc.returncode != 0 and not os.path.exists(jtl_file):
            err_msg = f"JMeter 执行失败退出 ({self._proc.returncode})"
            self._emit_log(f"[ERROR] {err_msg}")
            raise RuntimeError(err_msg)

        # 解析 JTL 文件
        self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] 开始解析 JTL 采样结果数据: {jtl_file}")
        report = self._parse_jtl(jtl_file)
        self._emit_log(f"[{datetime.now().strftime('%H:%M:%S')}] 解析完成: 样本总数={report.get('total_samples', 0)}, 失败={report.get('failed_samples', 0)}, 错误率={report.get('error_rate', 0)}%, 平均耗时={report.get('avg_rt_ms', 0)}ms, TPS={report.get('avg_tps', 0)}")

        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        return report

    def _parse_jtl(self, jtl_file: str) -> dict[str, Any]:
        """解析 JTL (CSV 格式) 得到统计指标、分组聚合与明细样本。"""
        if not os.path.exists(jtl_file):
            return {
                "total_samples": 0,
                "failed_samples": 0,
                "error_rate": 0.0,
                "avg_tps": 0.0,
                "avg_rt_ms": 0.0,
                "min_rt_ms": 0.0,
                "max_rt_ms": 0.0,
                "p90_rt_ms": 0.0,
                "p95_rt_ms": 0.0,
                "p99_rt_ms": 0.0,
                "sampler_summary": [],
                "jtl_rows": [],
                "jtl_content": "",
            }

        jtl_content = ""
        try:
            with open(jtl_file, "r", encoding="utf-8", errors="replace") as f:
                jtl_content = f.read(500000)  # 读取前 500KB 供预览
        except Exception:
            pass

        samples = []
        sampler_groups: dict[str, list[dict]] = {}
        tx_pattern = re.compile(r"Number of samples in transaction\s*:\s*(\d+)", re.I)

        with open(jtl_file, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    elapsed = float(row.get("elapsed", 0))
                    success = str(row.get("success", "true")).lower() == "true"
                    label = row.get("label", "Sampler") or "Sampler"
                    rc = row.get("responseCode", "")
                    rm = row.get("responseMessage", "")
                    thread_name = row.get("threadName", "")
                    url = row.get("URL", "")
                    ts = row.get("timeStamp", "")
                    bytes_val = int(row.get("bytes", 0)) if str(row.get("bytes", "")).isdigit() else 0

                    url_clean = (url or "").strip().lower()
                    m_tx = tx_pattern.search(rm)
                    is_tx = (not url_clean or url_clean == "null") or (m_tx is not None)
                    tx_child_count = int(m_tx.group(1)) if m_tx else 0

                    sample_item = {
                        "timeStamp": ts,
                        "elapsed": elapsed,
                        "label": label,
                        "responseCode": rc,
                        "responseMessage": rm,
                        "threadName": thread_name,
                        "success": success,
                        "failureMessage": row.get("failureMessage", ""),
                        "bytes": bytes_val,
                        "URL": url,
                        "latency": float(row.get("Latency", 0)) if row.get("Latency") else 0,
                        "is_transaction": is_tx,
                        "tx_child_count": tx_child_count,
                        "children": [],
                    }
                    samples.append(sample_item)

                    if label not in sampler_groups:
                        sampler_groups[label] = {
                            "is_transaction": is_tx,
                            "items": [],
                        }
                    sampler_groups[label]["items"].append(sample_item)
                except Exception:
                    continue

        # 构建采样明细的主子树结构（按线程回溯归属）
        sample_tree = []
        thread_buffers: dict[str, list[dict]] = {}
        for s in samples:
            t_name = s.get("threadName", "")
            if not s.get("is_transaction"):
                if t_name not in thread_buffers:
                    thread_buffers[t_name] = []
                thread_buffers[t_name].append(s)
            else:
                cnt = s.get("tx_child_count", 0)
                buf = thread_buffers.get(t_name, [])
                if cnt > 0 and len(buf) >= cnt:
                    s["children"] = buf[-cnt:]
                    del buf[-cnt:]
                else:
                    s["children"] = buf[:]
                    buf.clear()
                sample_tree.append(s)

        # 处理没有被任何事务控制器包裹的平铺子请求
        for t_name, remaining in thread_buffers.items():
            for r in remaining:
                sample_tree.append(r)

        total = len(samples)
        failed = sum(1 for s in samples if not s["success"])
        error_rate = round((failed / total * 100.0), 2) if total else 0.0
        rts = sorted(s["elapsed"] for s in samples)
        avg_rt = round(sum(rts) / total, 1) if total else 0.0
        min_rt = round(rts[0], 1) if rts else 0.0
        max_rt = round(rts[-1], 1) if rts else 0.0

        def _calc_pct(sorted_vals: list[float], pct: float) -> float:
            if not sorted_vals:
                return 0.0
            idx = int(len(sorted_vals) * pct)
            idx = max(0, min(len(sorted_vals) - 1, idx))
            return round(sorted_vals[idx], 1)

        # 计算实际有效测试耗时（秒）以稳妥计算 TPS，避免 duration_seconds 为 None 崩溃
        if self.duration_seconds is not None and self.duration_seconds > 0:
            effective_duration = float(self.duration_seconds)
        else:
            ts_list = [int(s["timeStamp"]) for s in samples if str(s.get("timeStamp", "")).isdigit()]
            if ts_list and max(ts_list) > min(ts_list):
                effective_duration = max(0.1, (max(ts_list) - min(ts_list)) / 1000.0)
            elif rts:
                effective_duration = max(0.1, sum(rts) / 1000.0)
            else:
                effective_duration = 1.0

        # 按接口分组聚合报表
        sampler_summary = []
        for lbl, group_info in sampler_groups.items():
            group = group_info["items"]
            is_tx = group_info["is_transaction"]
            g_total = len(group)
            g_failed = sum(1 for s in group if not s["success"])
            g_rts = sorted(s["elapsed"] for s in group)
            g_avg = round(sum(g_rts) / g_total, 1) if g_total else 0.0
            sampler_summary.append({
                "label": lbl,
                "is_transaction": is_tx,
                "samples": g_total,
                "failed": g_failed,
                "error_rate": round(g_failed / g_total * 100.0, 2) if g_total else 0.0,
                "avg_rt": g_avg,
                "min_rt": round(g_rts[0], 1) if g_rts else 0.0,
                "max_rt": round(g_rts[-1], 1) if g_rts else 0.0,
                "p90_rt": _calc_pct(g_rts, 0.9),
                "p95_rt": _calc_pct(g_rts, 0.95),
                "p99_rt": _calc_pct(g_rts, 0.99),
                "tps": round(g_total / effective_duration, 2),
            })

        return {
            "total_samples": total,
            "failed_samples": failed,
            "error_rate": error_rate,
            "avg_tps": round(total / effective_duration, 2),
            "avg_rt_ms": avg_rt,
            "min_rt_ms": min_rt,
            "max_rt_ms": max_rt,
            "p90_rt_ms": _calc_pct(rts, 0.9),
            "p95_rt_ms": _calc_pct(rts, 0.95),
            "p99_rt_ms": _calc_pct(rts, 0.99),
            "sampler_summary": sampler_summary,
            "jtl_rows": samples[:2000],  # 原始扁平明细
            "jtl_tree": sample_tree[:2000],  # 主子分层树形结构
            "jtl_content": jtl_content,
        }
