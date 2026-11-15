# -*- coding: utf-8 -*-
"""Prometheus 监控服务客户端。

负责与 Prometheus API (如 http://192.2.8.100:9091) 进行 HTTP 交互，
支持动态配置/持久化 Prometheus 主机地址、连接测试、目标主机探查、即时指标计算以及范围时序数据提取。
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
from logzero import logger

DEFAULT_PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://192.2.8.100:9091")
CONFIG_DIR = Path(os.path.expanduser("~/.insight_eye"))
CONFIG_FILE = CONFIG_DIR / "prometheus_config.json"


class PrometheusService:
    def __init__(self, base_url: str = DEFAULT_PROMETHEUS_URL):
        self.base_url = base_url.rstrip("/")
        self.token: str = ""
        self.endpoints: List[Dict[str, Any]] = []
        self._load_config()

    def _load_config(self) -> None:
        """从本地配置文件加载已保存的 Prometheus 主机配置。"""
        try:
            if CONFIG_FILE.exists():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                active_url = data.get("active_url", "").strip()
                if active_url:
                    self.base_url = active_url.rstrip("/")
                self.token = data.get("token", "")
                self.endpoints = data.get("endpoints", [])
        except Exception as e:
            logger.warning(f"[PrometheusService] 读取配置文件失败，使用默认配置: {e}")

        if not self.endpoints:
            self.endpoints = [
                {
                    "id": "default",
                    "name": "默认 Prometheus (192.2.8.100)",
                    "url": self.base_url,
                    "token": self.token,
                }
            ]

    def save_config(
        self,
        active_url: str,
        token: str = "",
        endpoints: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """保存并切换当前生效的 Prometheus 主机配置。"""
        clean_url = active_url.strip().rstrip("/")
        if not clean_url.startswith(("http://", "https://")):
            clean_url = f"http://{clean_url}"

        self.base_url = clean_url
        self.token = token.strip()

        if endpoints is not None:
            self.endpoints = endpoints
        else:
            # 如果当前地址不在列表中，自动加入列表
            exists = False
            for ep in self.endpoints:
                if ep.get("url", "").rstrip("/") == self.base_url:
                    ep["token"] = self.token
                    exists = True
                    break
            if not exists:
                self.endpoints.append(
                    {
                        "id": f"ep_{len(self.endpoints) + 1}",
                        "name": f"Prometheus ({self.base_url.replace('http://', '').replace('https://', '')})",
                        "url": self.base_url,
                        "token": self.token,
                    }
                )

        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "active_url": self.base_url,
                "token": self.token,
                "endpoints": self.endpoints,
            }
            CONFIG_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"[PrometheusService] 保存配置文件失败: {e}")

        return self.get_config()

    def get_config(self) -> Dict[str, Any]:
        """获取当前 Prometheus 配置信息。"""
        return {
            "active_url": self.base_url,
            "token": self.token,
            "endpoints": self.endpoints,
        }

    def test_connection(self, url: Optional[str] = None, token: Optional[str] = None) -> Dict[str, Any]:
        """测试指定或当前 Prometheus 主机地址的连通性与目标数量。"""
        target_url = (url or self.base_url).strip().rstrip("/")
        if not target_url.startswith(("http://", "https://")):
            target_url = f"http://{target_url}"
        auth_token = token.strip() if token is not None else self.token

        headers = {"Accept": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        try:
            req = urllib.request.Request(f"{target_url}/api/v1/query?query=up", headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") != "success":
                    return {"ok": False, "message": "服务响应状态非 success", "url": target_url}
                results = data.get("data", {}).get("result", [])
                jobs = set()
                for item in results:
                    j = item.get("metric", {}).get("job", "")
                    if j and j != "prometheus":
                        jobs.add(j)
                return {
                    "ok": True,
                    "url": target_url,
                    "host_count": len(jobs),
                    "endpoint_count": len(results),
                    "message": f"连接成功！共发现 {len(jobs)} 台受监控主机 ({len(results)} 个采集端点)",
                }
        except Exception as e:
            return {
                "ok": False,
                "url": target_url,
                "message": f"无法连接至 {target_url}: {e}",
            }

    def _request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15
    ) -> Dict[str, Any]:
        """向 Prometheus 发送 HTTP GET 请求。"""
        url = f"{self.base_url}{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: str(v) for k, v in params.items() if v is not None}
            )

        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except Exception as e:
            logger.error(f"[PrometheusService] 请求失败 {url}: {e}")
            raise RuntimeError(f"Prometheus 请求失败 ({self.base_url}): {e}")

    def query_instant(self, query: str, time: Optional[int] = None) -> List[Dict[str, Any]]:
        """即时查询 /api/v1/query"""
        params = {"query": query}
        if time:
            params["time"] = time
        res = self._request("/api/v1/query", params)
        if res.get("status") == "success":
            return res.get("data", {}).get("result", [])
        return []

    def query_range(
        self, query: str, start: int, end: int, step: int = 60
    ) -> List[Dict[str, Any]]:
        """范围时序查询 /api/v1/query_range"""
        params = {
            "query": query,
            "start": start,
            "end": end,
            "step": step,
        }
        res = self._request("/api/v1/query_range", params, timeout=30)
        if res.get("status") == "success":
            return res.get("data", {}).get("result", [])
        return []

    def get_target_hosts(self) -> List[Dict[str, Any]]:
        """获取受监控的主机列表（基于 node-exporter 与 cadvisor 的 jobs）。"""
        results = self.query_instant("up")
        hosts_map: Dict[str, Dict[str, Any]] = {}

        for item in results:
            metric = item.get("metric", {})
            job = metric.get("job", "")
            instance = metric.get("instance", "")
            status = item.get("value", [0, "0"])[1] == "1"

            if not job or job == "prometheus":
                continue

            host_key = job
            if host_key not in hosts_map:
                hosts_map[host_key] = {
                    "job": job,
                    "instance": instance.split(":")[0] if ":" in instance else instance,
                    "online": status,
                    "endpoints": [],
                }
            hosts_map[host_key]["endpoints"].append({"instance": instance, "online": status})
            if status:
                hosts_map[host_key]["online"] = True

        return list(hosts_map.values())

    def get_host_overview(self, job: str) -> Dict[str, Any]:
        """获取目标主机的概览指标（CPU使用率、内存使用率、负载、根分区磁盘使用）。"""
        overview = {
            "job": job,
            "cpu_percent": 0.0,
            "mem_total_gb": 0.0,
            "mem_used_gb": 0.0,
            "mem_percent": 0.0,
            "disk_total_gb": 0.0,
            "disk_used_gb": 0.0,
            "disk_percent": 0.0,
            "load1": 0.0,
            "cpu_cores": 1,
        }

        # 1. CPU cores
        cores_res = self.query_instant(f'count(node_cpu_seconds_total{{job="{job}",mode="idle"}})')
        if cores_res:
            try:
                overview["cpu_cores"] = int(float(cores_res[0]["value"][1]))
            except Exception:
                pass

        # 2. CPU 使用率 (1m rate)
        cpu_res = self.query_instant(
            f'(1 - avg(rate(node_cpu_seconds_total{{job="{job}",mode="idle"}}[1m]))) * 100'
        )
        if cpu_res:
            try:
                overview["cpu_percent"] = round(float(cpu_res[0]["value"][1]), 2)
            except Exception:
                pass

        # 3. 内存使用率
        mem_total_res = self.query_instant(f'node_memory_MemTotal_bytes{{job="{job}"}}')
        mem_avail_res = self.query_instant(f'node_memory_MemAvailable_bytes{{job="{job}"}}')
        if mem_total_res and mem_avail_res:
            try:
                total_b = float(mem_total_res[0]["value"][1])
                avail_b = float(mem_avail_res[0]["value"][1])
                used_b = max(0.0, total_b - avail_b)
                overview["mem_total_gb"] = round(total_b / (1024**3), 2)
                overview["mem_used_gb"] = round(used_b / (1024**3), 2)
                overview["mem_percent"] = (
                    round((used_b / total_b) * 100, 2) if total_b > 0 else 0.0
                )
            except Exception:
                pass

        # 4. 系统 1m 负载
        load_res = self.query_instant(f'node_load1{{job="{job}"}}')
        if load_res:
            try:
                overview["load1"] = round(float(load_res[0]["value"][1]), 2)
            except Exception:
                pass

        # 5. 根分区磁盘
        disk_total_res = self.query_instant(
            f'node_filesystem_size_bytes{{job="{job}",mountpoint="/"}}'
        )
        disk_free_res = self.query_instant(
            f'node_filesystem_free_bytes{{job="{job}",mountpoint="/"}}'
        )
        if disk_total_res and disk_free_res:
            try:
                total_d = float(disk_total_res[0]["value"][1])
                free_d = float(disk_free_res[0]["value"][1])
                used_d = max(0.0, total_d - free_d)
                overview["disk_total_gb"] = round(total_d / (1024**3), 2)
                overview["disk_used_gb"] = round(used_d / (1024**3), 2)
                overview["disk_percent"] = (
                    round((used_d / total_d) * 100, 2) if total_d > 0 else 0.0
                )
            except Exception:
                pass

        return overview

    def get_container_stats(
        self, job: str, start: int, end: int, step: int = 60
    ) -> List[Dict[str, Any]]:
        """获取目标主机上全部 Docker 容器在指定时间范围内的 CPU、内存 (RSS/Usage) 统计表。"""
        # 1. CPU
        cpu_query = f'sum(rate(container_cpu_usage_seconds_total{{job="{job}",image!=""}}[1m])) by (name) * 100'
        cpu_series = self.query_range(cpu_query, start, end, step)

        # 2. 内存 RSS
        rss_query = f'sum(container_memory_rss{{job="{job}",image!=""}}) by (name)'
        rss_series = self.query_range(rss_query, start, end, step)

        # 3. 内存 Usage
        usage_query = f'sum(container_memory_usage_bytes{{job="{job}",image!=""}}) by (name)'
        usage_series = self.query_range(usage_query, start, end, step)

        def aggregate_series(series_list: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
            res = {}
            for item in series_list:
                name = item.get("metric", {}).get("name")
                if not name:
                    continue
                vals = [float(v[1]) for v in item.get("values", []) if v[1] is not None]
                if vals:
                    res[name] = {
                        "max": max(vals),
                        "avg": sum(vals) / len(vals),
                        "latest": vals[-1],
                    }
            return res

        cpu_stats = aggregate_series(cpu_series)
        rss_stats = aggregate_series(rss_series)
        usage_stats = aggregate_series(usage_series)

        all_names = sorted(list(set(list(cpu_stats.keys()) + list(rss_stats.keys()))))
        rows = []
        for name in all_names:
            c = cpu_stats.get(name, {"max": 0.0, "avg": 0.0, "latest": 0.0})
            r = rss_stats.get(name, {"max": 0.0, "avg": 0.0, "latest": 0.0})
            u = usage_stats.get(name, {"max": 0.0, "avg": 0.0, "latest": 0.0})

            short_name = name
            m = re.match(r"^unicloud_([^\.]+)", name)
            if m:
                short_name = m.group(1)

            rows.append(
                {
                    "name": name,
                    "short_name": short_name,
                    "cpu_max": round(c["max"], 2),
                    "cpu_avg": round(c["avg"], 2),
                    "cpu_current": round(c["latest"], 2),
                    "rss_max_mb": round(r["max"] / (1024 * 1024), 2),
                    "rss_avg_mb": round(r["avg"] / (1024 * 1024), 2),
                    "rss_current_mb": round(r["latest"] / (1024 * 1024), 2),
                    "usage_max_mb": round(u["max"] / (1024 * 1024), 2),
                    "usage_avg_mb": round(u["avg"] / (1024 * 1024), 2),
                    "usage_current_mb": round(u["latest"] / (1024 * 1024), 2),
                }
            )

        rows.sort(key=lambda x: x["cpu_max"], reverse=True)
        return rows


# 单例实例
prometheus_service = PrometheusService()
