# -*- coding: utf-8 -*-
"""系统/服务器监控 API（通过 Prometheus 采集主机与 Docker 容器性能）。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from logzero import logger

from performance.backend.services.prometheus_service import prometheus_service

router = APIRouter(prefix="/system_monitor", tags=["system_monitor"])


class PrometheusEndpointItem(BaseModel):
    id: str
    name: str
    url: str
    token: str = ""


class SavePrometheusConfigRequest(BaseModel):
    active_url: str
    token: str = ""
    endpoints: Optional[List[Dict[str, Any]]] = None


class TestConnectionRequest(BaseModel):
    url: str
    token: str = ""


@router.get("/config")
async def get_prometheus_config() -> Dict[str, Any]:
    """获取当前 Prometheus 主机配置及历史保存列表。"""
    return prometheus_service.get_config()


@router.post("/config")
async def save_prometheus_config(req: SavePrometheusConfigRequest) -> Dict[str, Any]:
    """保存并切换当前生效的 Prometheus 主机地址。"""
    try:
        return prometheus_service.save_config(
            active_url=req.active_url,
            token=req.token,
            endpoints=req.endpoints,
        )
    except Exception as e:
        logger.error(f"保存 Prometheus 配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-connection")
async def test_prometheus_connection(req: TestConnectionRequest) -> Dict[str, Any]:
    """测试指定的 Prometheus 主机连接。"""
    return prometheus_service.test_connection(url=req.url, token=req.token)


@router.get("/hosts")
async def get_monitor_hosts() -> List[Dict[str, Any]]:
    """获取所有受监控的主机列表。"""
    try:
        return prometheus_service.get_target_hosts()
    except Exception as e:
        logger.error(f"获取监控主机失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overview")
async def get_host_overview(
    job: str = Query(..., description="目标主机 job 标识，如 cloud_8.130")
) -> Dict[str, Any]:
    """获取目标主机的即时概览指标（CPU、内存、系统负载、磁盘）。"""
    try:
        return prometheus_service.get_host_overview(job)
    except Exception as e:
        logger.error(f"获取主机概览失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/containers")
async def get_container_stats(
    job: str = Query(..., description="目标主机 job 标识，如 cloud_8.130"),
    start: Optional[int] = Query(None, description="起始时间戳（秒）"),
    end: Optional[int] = Query(None, description="结束时间戳（秒）"),
    step: int = Query(60, description="采样步长（秒）"),
) -> List[Dict[str, Any]]:
    """获取目标主机各 Docker 容器的 CPU 与 内存 统计信息（Max, Avg, Current）。"""
    try:
        now = int(time.time())
        if end is None:
            end = now
        if start is None:
            start = end - 3600

        return prometheus_service.get_container_stats(job=job, start=start, end=end, step=step)
    except Exception as e:
        logger.error(f"获取容器性能统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trend")
async def get_performance_trend(
    job: str = Query(..., description="目标主机 job 标识"),
    container: Optional[str] = Query(None, description="容器名过滤，为空时返回整体"),
    metric_type: str = Query("cpu", description="cpu | memory"),
    start: Optional[int] = Query(None),
    end: Optional[int] = Query(None),
    step: int = Query(60),
) -> List[List[Any]]:
    """获取时序波动趋势数据，供 ECharts 绘图。"""
    try:
        now = int(time.time())
        if end is None:
            end = now
        if start is None:
            start = end - 3600

        if metric_type == "cpu":
            if container:
                query = f'sum(rate(container_cpu_usage_seconds_total{{job="{job}",name="{container}"}}[1m])) * 100'
            else:
                query = f'(1 - avg(rate(node_cpu_seconds_total{{job="{job}",mode="idle"}}[1m]))) * 100'
        else:
            if container:
                query = (
                    f'sum(container_memory_rss{{job="{job}",name="{container}"}}) / 1024 / 1024'
                )
            else:
                query = f'(1 - (node_memory_MemAvailable_bytes{{job="{job}"}} / node_memory_MemTotal_bytes{{job="{job}"}})) * 100'

        series = prometheus_service.query_range(query, start, end, step)
        points = []
        if series:
            for v in series[0].get("values", []):
                try:
                    ts = int(v[0]) * 1000
                    val = round(float(v[1]), 2)
                    points.append([ts, val])
                except Exception:
                    continue
        return points
    except Exception as e:
        logger.error(f"获取趋势失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
