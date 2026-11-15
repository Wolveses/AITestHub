# -*- coding: utf-8 -*-
"""Android 应用枚举器单元测试：覆盖 ColorOS 10 列 ps -A、Android 8+ ProcessRecord 与前台检测。"""

from unittest.mock import MagicMock

from insight_aitest.platform.services.device_adapters.app_enumerator import AndroidAppEnumerator
from insight_aitest.platform.services.device_adapters.models import AppStatus


def _make_enumerator(shell_map: dict[str, str]) -> AndroidAppEnumerator:
    enum = AndroidAppEnumerator.__new__(AndroidAppEnumerator)
    enum.device_id = "test-device"
    enum._cached_apps = []
    adb_mock = MagicMock()
    adb_mock.shell.side_effect = lambda cmd, device_id, timeout=10: shell_map.get(cmd, "")
    enum._adb = adb_mock
    return enum


def test_get_running_apps_handles_coloros_10_column_ps_and_modern_process_record():
    dumpsys_processes = """
  *APP* UID 10029 ProcessRecord{85a5ab2 2742:com.digibird.umplayer/u0a29}
    packageList={com.digibird.umplayer}
    oom: max=1001 curRaw=0 setRaw=0 cur=0 set=0
    hasClientActivities=false foregroundActivities=true (rep=true)
  *APP* UID 10100 ProcessRecord{abc1234 3100:com.example.bg/u0a100}
    oom: max=1001 curRaw=700 setRaw=700 cur=700 set=700
    hasClientActivities=false foregroundActivities=false (rep=false)
    PID #2742: ProcessRecord{85a5ab2 2742:com.digibird.umplayer/u0a29}
    """
    ps_output = (
        "USER           PID  PPID     VSZ    RSS WCHAN            ADDR\tFRZ  S NAME\n"
        "u0_a29        2742 26385 8672204 145012 0                   0\tefg  S com.digibird.umplayer\n"
        "u0_a100       3100 26385 1234567  65432 0                   0\t     S com.example.bg:push\n"
        "u0_a100       3099 26385 1234567  65432 0                   0\t     S com.example.bg\n"
    )
    enum = _make_enumerator({
        "dumpsys activity processes": dumpsys_processes,
        "ps -A": ps_output,
    })

    apps = {app.package_name: app for app in enum.get_running_apps()}

    assert "com.digibird.umplayer" in apps
    assert apps["com.digibird.umplayer"].is_running is True
    assert apps["com.digibird.umplayer"].pid == 2742
    assert apps["com.digibird.umplayer"].status == AppStatus.RUNNING

    assert "com.example.bg" in apps
    assert apps["com.example.bg"].pid == 3099
    assert apps["com.example.bg"].status == AppStatus.BACKGROUND


def test_get_running_apps_falls_back_to_resumed_activity_and_window_focus():
    ps_output = (
        "USER PID PPID VSZ RSS WCHAN ADDR S NAME\n"
        "u0_a50 4512 1000 1000 500 0 0 S com.example.fg\n"
    )
    activities_output = "  ResumedActivity: ActivityRecord{628974e u0 com.example.fg/.MainActivity t54072}\n"
    enum = _make_enumerator({
        "dumpsys activity processes": "",
        "dumpsys activity activities": activities_output,
        "dumpsys window windows": "",
        "ps -A": ps_output,
    })

    apps = enum.get_running_apps()
    assert len(apps) == 1
    assert apps[0].package_name == "com.example.fg"
    assert apps[0].status == AppStatus.RUNNING
