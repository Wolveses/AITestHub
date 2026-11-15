# -*- coding: utf-8 -*-
"""平台主机设备池、无线投屏辅助（QtScrcpy）与 Appium 状态路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from insight_aitest.modules.mobile.backend.automation.session_manager import cancel_generation_session
from insight_aitest.modules.mobile.backend.device_pool import (
    check_appium_status,
    enable_wireless_adb,
    get_lease_manager,
    list_mobile_devices,
)

router = APIRouter(prefix="/devices", tags=["mobile-devices"])


@router.get("")
def get_devices(platform: str | None = Query("android")) -> dict:
    return {
        "devices": list_mobile_devices(platform=platform or None),
        "appium": check_appium_status(),
    }


@router.get("/appium-status")
def get_appium_status(url: str = Query("http://127.0.0.1:4723")) -> dict:
    return check_appium_status(url)


@router.post("/{device_id}/wireless")
def open_wireless_adb(device_id: str, port: int = Query(5555)) -> dict:
    try:
        return enable_wireless_adb(device_id, port=port)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e


@router.post("/{device_id}/release")
def force_release_device(device_id: str) -> dict:
    """管理员强制释放设备租约锁，并重置关联的运行中生成会话。"""
    mgr = get_lease_manager()
    lease = mgr.get(device_id)
    if lease is None:
        return {"released": False, "device_id": device_id}
    if lease.holder_type == "generation" and lease.case_id:
        cancel_generation_session(lease.case_id, reason="设备锁已被管理员强制释放")
    else:
        mgr.release(device_id, force=True)
    return {"released": True, "device_id": device_id}
