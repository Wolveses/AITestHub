"""Performance 监控路由集成测试（告警阈值动态修改 / 告警降序与解除状态 / 总内存字段）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from insight_aitest.platform.kernel import build_app
from insight_aitest.platform.persistence.database import DatabaseManager
from insight_aitest.platform.services.device_manager import DeviceManager


@pytest.fixture(autouse=True)
def _isolate_state():
    DatabaseManager._instance = None
    DeviceManager._session_alert_thresholds.clear()
    yield
    DatabaseManager._instance = None
    DeviceManager._session_alert_thresholds.clear()


def test_update_alert_thresholds_and_get_alerts_order(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    db_dir = tmp_path / ".insight_eye"
    db_dir.mkdir(parents=True, exist_ok=True)
    db = DatabaseManager(str(db_dir / "monitoring.db"))
    session = db.create_session("dev1", "com.example.app")
    db.update_session(session.id, memory_total_mb=8192.0)

    a1 = db.save_alert(
        session.id,
        {
            "alert_type": "low_fps",
            "metric_name": "FPS",
            "current_value": 24.0,
            "threshold_value": 30.0,
            "severity": "warning",
            "description": "FPS过低: 24.0 < 30.0",
        },
    )
    a2 = db.save_alert(
        session.id,
        {
            "alert_type": "high_cpu",
            "metric_name": "CPU",
            "current_value": 92.0,
            "threshold_value": 80.0,
            "severity": "critical",
            "description": "CPU过高: 92.0% > 80.0%",
        },
    )
    db.resolve_alerts(session.id, alert_type="low_fps")

    app = build_app()
    client = TestClient(app)

    # 1. 会话详情返回 memory_total_mb
    detail_resp = client.get(f"/api/modules/performance/monitoring/sessions/{session.id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["memory_total_mb"] == 8192.0

    # 2. 告警记录按时间/ID降序，且包含 resolved 状态
    alerts_resp = client.get(f"/api/modules/performance/monitoring/sessions/{session.id}/alerts")
    assert alerts_resp.status_code == 200
    alerts = alerts_resp.json()
    assert [item["id"] for item in alerts] == [a2, a1]
    assert alerts[0]["resolved"] is False
    assert alerts[1]["resolved"] is True

    # 3. 动态更新告警阈值
    put_resp = client.put(
        f"/api/modules/performance/monitoring/sessions/{session.id}/alert-thresholds",
        json={"fps": 45, "memory": 2048, "cpu": 75, "temperature": 42.5},
    )
    assert put_resp.status_code == 200
    assert DeviceManager._session_alert_thresholds[session.id] == {
        "fps_threshold": 45.0,
        "memory_threshold_mb": 2048.0,
        "cpu_threshold_percent": 75.0,
        "battery_threshold_temp": 42.5,
    }

    # 4. 不存在的会话返回 404
    missing_resp = client.put(
        "/api/modules/performance/monitoring/sessions/999999/alert-thresholds",
        json={"fps": 30, "memory": 500, "cpu": 80, "temperature": 45},
    )
    assert missing_resp.status_code == 404
