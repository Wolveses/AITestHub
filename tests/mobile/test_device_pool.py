# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from insight_aitest.modules.mobile.backend import device_pool
from insight_aitest.modules.mobile.backend.device_pool import (
    DeviceBusyError,
    DeviceLeaseManager,
    enable_wireless_adb,
    list_mobile_devices,
)
from insight_aitest.platform.services.models.device import Device, DeviceStatus, DeviceType


def test_lease_manager_lifecycle_conflict_touch_ttl_and_release():
    mgr = DeviceLeaseManager()

    lease, token = mgr.acquire(
        "dev-1", holder_type="generation", case_id=42, generation_id=7, ttl_seconds=60
    )
    assert lease.device_id == "dev-1"
    assert mgr.get("dev-1") is not None

    with pytest.raises(DeviceBusyError):
        mgr.acquire("dev-1", holder_type="run", case_id=99, ttl_seconds=60)

    # Touch extends expiry
    lease.expires_at = datetime.now() + timedelta(seconds=1)
    touched = mgr.verify_and_touch(token)
    assert touched is not None
    assert (touched.expires_at - datetime.now()).total_seconds() > 30

    # Wrong token cannot release unless force=True
    assert mgr.release("dev-1", token="wrong-token", force=False) is False
    assert mgr.get("dev-1") is not None
    assert mgr.release("dev-1", token=token, force=False) is True
    assert mgr.get("dev-1") is None

    # Expired lease is automatically purged
    expired_lease, _ = mgr.acquire("dev-2", holder_type="run", case_id=11, ttl_seconds=10)
    expired_lease.expires_at = datetime.now() - timedelta(seconds=1)
    assert mgr.get("dev-2") is None
    new_lease, _ = mgr.acquire("dev-2", holder_type="run", case_id=12, ttl_seconds=10)
    assert new_lease.case_id == 12


def test_enable_wireless_adb_with_mocked_adb(monkeypatch):
    calls: list[list[str]] = []

    def fake_run_adb(args, timeout=10):
        calls.append(args)
        if args[-2:] == ["tcpip", "5555"]:
            return 0, "restarting in TCP mode port: 5555"
        if args[-1] == "wlan0":
            return 0, "inet 192.168.10.88/24 brd 192.168.10.255 scope global wlan0"
        return 1, ""

    monkeypatch.setattr(device_pool, "_run_adb", fake_run_adb)
    res = enable_wireless_adb("USB123456", port=5555)
    assert res == {"device_id": "USB123456", "endpoint": "192.168.10.88:5555", "port": 5555}
    assert ["-s", "USB123456", "tcpip", "5555"] in calls


def test_list_mobile_devices_merges_lease_and_wireless_cache(monkeypatch):
    fake_devices = [
        Device(
            device_id="emulator-5554",
            name="Pixel_7",
            type=DeviceType.ANDROID,
            status=DeviceStatus.ONLINE,
            model="Pixel 7",
            sdk_version="14",
        ),
        Device(
            device_id="ios-udid-1",
            name="iPhone 15",
            type=DeviceType.IOS,
            status=DeviceStatus.ONLINE,
            model="iPhone 15",
            sdk_version="17.2",
        ),
    ]
    monkeypatch.setattr(device_pool.DeviceManager, "scan_devices", staticmethod(lambda: fake_devices))

    mgr = DeviceLeaseManager()
    mgr.acquire("emulator-5554", holder_type="generation", case_id=5, generation_id=1)
    monkeypatch.setattr(device_pool, "_lease_manager", mgr)

    android_only = list_mobile_devices(platform="android")
    assert len(android_only) == 1
    assert android_only[0]["device_id"] == "emulator-5554"
    assert android_only[0]["busy"] is True
    assert android_only[0]["lease"]["case_id"] == 5

    all_devs = list_mobile_devices(platform=None)
    assert len(all_devs) == 2
