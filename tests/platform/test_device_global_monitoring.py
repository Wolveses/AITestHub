# -*- coding: utf-8 -*-
"""设备全局性能监控单元测试：覆盖 Android/iOS 全局采集器、FPS 动态前台解析与会话持久化。"""

from unittest.mock import MagicMock, patch

from insight_aitest.platform.persistence.database import DatabaseManager
from insight_aitest.platform.services.collectors.android.android_apm import _validate_package_name
from insight_aitest.platform.services.collectors.android.cpu_collector import CPUCollector
from insight_aitest.platform.services.collectors.android.fps_collector import SurfaceStatsCollector
from insight_aitest.platform.services.collectors.android.memory_collector import MemoryCollector
from insight_aitest.platform.services.collectors.android.network_collector import NetworkCollector
from insight_aitest.platform.services.collectors.ios.cpu_collector import (
    CPUCollector as IOSCPUCollector,
)
from insight_aitest.platform.services.collectors.ios.ios_apm import _validate_bundle_id
from insight_aitest.platform.services.collectors.ios.memory_collector import (
    MemoryCollector as IOSMemoryCollector,
)
from insight_aitest.platform.services.collectors.ios.metrics_throttle import MetricsThrottle
from insight_aitest.platform.services.device_common import DEVICE_GLOBAL_TARGET


def test_package_and_bundle_validators_accept_device_global_target():
    assert _validate_package_name(DEVICE_GLOBAL_TARGET) is True
    assert _validate_package_name("com.example.app") is True
    assert _validate_package_name("invalid") is False

    assert _validate_bundle_id(DEVICE_GLOBAL_TARGET) is True
    assert _validate_bundle_id("com.example.app") is True
    assert _validate_bundle_id("invalid") is False


def test_android_cpu_collector_device_proc_stat_diff():
    collector = CPUCollector.__new__(CPUCollector)
    collector.device_id = "test-dev"
    collector.device_profile = None
    collector.strategy = None
    collector.cpu_cores = 8
    collector._last_cpu_data = {}

    snapshots = iter(
        [
            "cpu  100 0 100 800 0 0 0 0 0 0\n",
            "cpu  120 0 130 950 0 0 0 0 0 0\n",
        ]
    )
    with (
        patch(
            "insight_aitest.platform.services.collectors.android.cpu_collector.adb.shell",
            side_effect=lambda cmd, dev: next(snapshots),
        ),
        patch("insight_aitest.platform.services.collectors.android.cpu_collector.time.sleep"),
    ):
        res = collector.collect(DEVICE_GLOBAL_TARGET)

    # delta total = (120+130+950) - (100+100+800) = 200; idle delta = 150 -> 25.0%
    assert res == {"appCpuRate": 25.0, "sysCpuRate": 25.0}


def test_android_cpu_collector_device_fallbacks_top_and_dumpsys():
    collector = CPUCollector.__new__(CPUCollector)
    collector.device_id = "test-dev"
    collector.device_profile = None
    collector.strategy = None
    collector.cpu_cores = 8
    collector._last_cpu_data = {}

    def shell_top(cmd, dev):
        if cmd == "cat /proc/stat":
            return ""
        if cmd == "top -n 1":
            return "800%cpu   3%user   0%nice  39%sys 758%idle   0%iow"
        return ""

    with patch(
        "insight_aitest.platform.services.collectors.android.cpu_collector.adb.shell",
        side_effect=shell_top,
    ):
        res = collector.collect(DEVICE_GLOBAL_TARGET)
    assert res == {"appCpuRate": 5.25, "sysCpuRate": 5.25}

    def shell_dumpsys(cmd, dev):
        if cmd == "dumpsys cpuinfo":
            return " +0% 123/foo: 0% user\n4.6% TOTAL: 2.7% user + 1.4% kernel"
        return ""

    with patch(
        "insight_aitest.platform.services.collectors.android.cpu_collector.adb.shell",
        side_effect=shell_dumpsys,
    ):
        res2 = collector.collect(DEVICE_GLOBAL_TARGET)
    assert res2 == {"appCpuRate": 4.6, "sysCpuRate": 4.6}


def test_android_memory_collector_device_global_with_and_without_available():
    collector = MemoryCollector.__new__(MemoryCollector)
    collector.device_id = "test-dev"
    collector.device_profile = None
    collector.strategy = None
    collector._total_memory_mb = None

    meminfo_with_avail = (
        "MemTotal:        4096000 kB\n"
        "MemFree:          512000 kB\n"
        "MemAvailable:    2048000 kB\n"
    )
    with patch(
        "insight_aitest.platform.services.collectors.android.memory_collector.adb.shell",
        return_value=meminfo_with_avail,
    ):
        res = collector.collect(DEVICE_GLOBAL_TARGET)

    assert res["total_mb"] == 4000.0
    assert res["totalPass"] == 2000.0
    assert res["percentage"] == 50.0

    meminfo_legacy = (
        "MemTotal:        2048000 kB\n"
        "MemFree:          256000 kB\n"
        "Buffers:          128000 kB\n"
        "Cached:           640000 kB\n"
    )
    with patch(
        "insight_aitest.platform.services.collectors.android.memory_collector.adb.shell",
        return_value=meminfo_legacy,
    ):
        res2 = collector.collect(DEVICE_GLOBAL_TARGET)

    assert res2["total_mb"] == 2000.0
    assert res2["totalPass"] == 1000.0
    assert res2["percentage"] == 50.0


def test_android_network_collector_device_skips_loopback_and_uid_lookup():
    collector = NetworkCollector.__new__(NetworkCollector)
    collector.device_id = "test-dev"
    collector.device_profile = None
    collector.strategy = None
    collector.last_data = {}
    collector.last_time = {}

    samples = iter(
        [
            (
                "Inter-| Receive | Transmit\n"
                " face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
                "    lo: 9999999 10 0 0 0 0 0 0 9999999 10 0 0 0 0 0 0\n"
                " wlan0: 102400 100 0 0 0 0 0 0 51200 50 0 0 0 0 0 0\n"
            ),
            (
                "Inter-| Receive | Transmit\n"
                " face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
                "    lo: 19999999 20 0 0 0 0 0 0 19999999 20 0 0 0 0 0 0\n"
                " wlan0: 307200 200 0 0 0 0 0 0 153600 100 0 0 0 0 0 0\n"
            ),
        ]
    )
    times = iter([100.0, 102.0])

    with (
        patch(
            "insight_aitest.platform.services.collectors.android.network_collector.adb.shell",
            side_effect=lambda cmd, dev: next(samples),
        ) as shell_mock,
        patch(
            "insight_aitest.platform.services.collectors.android.network_collector.time.time",
            side_effect=lambda: next(times),
        ),
    ):
        first = collector.collect(DEVICE_GLOBAL_TARGET)
        second = collector.collect(DEVICE_GLOBAL_TARGET)

    assert first == {"upFlow": 0, "downFlow": 0}
    # 204800 / 2s / 1024 = 100 KB/s down; 102400 / 2s / 1024 = 50 KB/s up (lo ignored)
    assert second == {"upFlow": 50.0, "downFlow": 100.0}
    for call in shell_mock.call_args_list:
        assert "dumpsys package" not in call.args[0]


def test_android_fps_collector_device_mode_resolves_foreground_package():
    collector = SurfaceStatsCollector.__new__(SurfaceStatsCollector)
    collector.device = "test-dev"
    collector.package_name = DEVICE_GLOBAL_TARGET
    collector.focus_window = ""
    collector.use_legacy_method = False

    cmds = []

    def fake_shell(cmd, deviceId=None):
        cmds.append(cmd)
        if cmd == "dumpsys window windows":
            return "  mCurrentFocus=Window{123 u0 com.example.fg/com.example.fg.MainActivity}"
        if cmd == "dumpsys gfxinfo com.example.fg framestats":
            return ""
        if cmd == "dumpsys gfxinfo com.example.fg":
            return ""
        if cmd == "dumpsys SurfaceFlinger --list":
            return "com.example.fg/com.example.fg.MainActivity#0"
        return ""

    with (
        patch(
            "insight_aitest.platform.services.collectors.android.fps_collector.adb.shell",
            side_effect=fake_shell,
        ),
        patch.object(collector, "_try_legacy_method", return_value=(None, None)),
    ):
        collector._get_surfaceflinger_frame_data()

    assert not any("__device__" in cmd for cmd in cmds)
    assert "dumpsys gfxinfo com.example.fg framestats" in cmds


def test_ios_throttle_and_collectors_device_global_mode():
    throttle = MetricsThrottle(target_frequency=1.0, cpu_core_count=2)
    throttle.on_raw_batch(
        [
            {"pid": 10, "name": "AppA", "cpuUsage": 40.0, "physFootprint": 100 * 1024 * 1024},
            {"pid": 20, "name": "AppB", "cpuUsage": 20.0, "physFootprint": 200 * 1024 * 1024},
        ]
    )
    metrics = throttle.get_metrics(DEVICE_GLOBAL_TARGET)
    assert metrics["cpu_app"] == 30.0  # (40 + 20) / 2 cores
    assert metrics["used_mb"] == 300.0

    adapter = MagicMock()
    adapter.device_id = "ios-udid"

    ios_cpu = IOSCPUCollector(adapter, DEVICE_GLOBAL_TARGET, throttle=throttle)
    assert ios_cpu.collect() == {"cpu_app": 30.0, "cpu_system": 30.0}

    ios_mem = IOSMemoryCollector(adapter, DEVICE_GLOBAL_TARGET, throttle=throttle)
    ios_mem._total_memory_mb = 4096.0
    with patch(
        "insight_aitest.platform.services.collectors.ios.py_ios_device_helper.PyiOSDeviceHelper",
        side_effect=RuntimeError("no py-ios-device"),
    ):
        mem_res = ios_mem.collect()
    assert mem_res["used_mb"] == 300.0
    assert mem_res["total_mb"] == 4096.0


def test_database_create_session_labels_device_global_target(tmp_path):
    db_path = str(tmp_path / "monitoring.db")
    db = DatabaseManager(db_path)
    session = db.create_session("a301dc54", DEVICE_GLOBAL_TARGET, platform="android")
    assert session.app_package == DEVICE_GLOBAL_TARGET
    assert session.app_name == "设备全局监控"
