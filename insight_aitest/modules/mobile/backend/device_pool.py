# -*- coding: utf-8 -*-
"""手机设备池、独占租约锁（TTL 自动回收）、无线 ADB 辅助与 Appium 状态探活。"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx

from insight_aitest.platform.services.device_manager import DeviceManager
from insight_aitest.platform.services.models.device import Device, DeviceType

logger = logging.getLogger(__name__)

DEFAULT_LEASE_TTL_SECONDS = 300
_WIRELESS_CACHE: dict[str, str] = {}
_CACHE_LOCK = threading.Lock()


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


@dataclass
class DeviceLease:
    device_id: str
    holder_type: str  # "generation" | "run"
    case_id: int
    generation_id: int | None
    token_hash: str
    ttl_seconds: int
    acquired_at: datetime
    expires_at: datetime

    def is_expired(self) -> bool:
        return datetime.now() >= self.expires_at

    def to_public_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "holder_type": self.holder_type,
            "case_id": self.case_id,
            "generation_id": self.generation_id,
            "acquired_at": self.acquired_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


class DeviceBusyError(RuntimeError):
    """设备已被其它生成或运行会话独占锁定。"""


class DeviceLeaseManager:
    """进程内设备独占租约锁，支持心跳续期与超时自动释放。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: dict[str, DeviceLease] = {}

    def _purge_expired_locked(self) -> None:
        expired = [did for did, lease in self._leases.items() if lease.is_expired()]
        for did in expired:
            logger.info("设备租约超时自动释放: device_id=%s", did)
            self._leases.pop(did, None)

    def acquire(
        self,
        device_id: str,
        *,
        holder_type: str,
        case_id: int,
        generation_id: int | None = None,
        ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    ) -> tuple[DeviceLease, str]:
        if not device_id:
            raise ValueError("device_id 不能为空")
        raw_token = secrets.token_urlsafe(32)
        t_hash = hash_token(raw_token)
        now = datetime.now()
        with self._lock:
            self._purge_expired_locked()
            existing = self._leases.get(device_id)
            if existing is not None:
                raise DeviceBusyError(
                    f"设备 {device_id} 当前被用例 #{existing.case_id} ({existing.holder_type}) 占用，"
                    f"预计释放时间 {existing.expires_at.strftime('%H:%M:%S')}"
                )
            lease = DeviceLease(
                device_id=device_id,
                holder_type=holder_type,
                case_id=case_id,
                generation_id=generation_id,
                token_hash=t_hash,
                ttl_seconds=ttl_seconds,
                acquired_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
            self._leases[device_id] = lease
            return lease, raw_token

    def get(self, device_id: str) -> DeviceLease | None:
        with self._lock:
            self._purge_expired_locked()
            return self._leases.get(device_id)

    def verify_and_touch(self, token: str) -> DeviceLease | None:
        if not token:
            return None
        t_hash = hash_token(token)
        now = datetime.now()
        with self._lock:
            self._purge_expired_locked()
            for lease in self._leases.values():
                if lease.token_hash == t_hash:
                    lease.expires_at = now + timedelta(seconds=lease.ttl_seconds)
                    return lease
        return None

    def release(self, device_id: str, *, token: str | None = None, force: bool = False) -> bool:
        with self._lock:
            self._purge_expired_locked()
            lease = self._leases.get(device_id)
            if lease is None:
                return False
            if not force and token is not None and lease.token_hash != hash_token(token):
                return False
            self._leases.pop(device_id, None)
            return True

    def list_leases(self) -> dict[str, DeviceLease]:
        with self._lock:
            self._purge_expired_locked()
            return dict(self._leases)


_lease_manager = DeviceLeaseManager()


def get_lease_manager() -> DeviceLeaseManager:
    return _lease_manager


def _run_adb(args: list[str], timeout: int = 10) -> tuple[int, str]:
    adb_bin = shutil.which("adb") or "adb"
    try:
        proc = subprocess.run(
            [adb_bin, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return proc.returncode, out
    except FileNotFoundError:
        return 127, "未检测到 adb 命令，请安装 Android Platform-Tools 并加入 PATH"
    except subprocess.TimeoutExpired:
        return 124, f"adb 命令超时 ({timeout}s)"


def _parse_wlan_ip(text: str) -> str:
    # 兼容 `ip -f inet addr show wlan0` 与 `ip route`
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/", text or "")
    if m:
        return m.group(1)
    m = re.search(r"src\s+(\d+\.\d+\.\d+\.\d+)", text or "")
    return m.group(1) if m else ""


def enable_wireless_adb(device_id: str, port: int = 5555) -> dict:
    """为平台主机直连的 Android 设备开启无线 ADB（供 QtScrcpy 等本机工具投屏观察）。"""
    if not device_id:
        raise ValueError("device_id 不能为空")
    rc, out = _run_adb(["-s", device_id, "tcpip", str(port)], timeout=10)
    if rc != 0:
        raise RuntimeError(f"开启 tcpip {port} 失败: {out}")

    # 若本身已是 ip:port 形式，直接提取 IP
    ip_match = re.match(r"^(\d+\.\d+\.\d+\.\d+):\d+$", device_id)
    ip = ip_match.group(1) if ip_match else ""
    if not ip:
        # `adb tcpip` 会触发手机 adbd 重启并短暂断连，重试等待设备重新上线并获取 IP
        for attempt in range(6):
            _, addr_out = _run_adb(
                ["-s", device_id, "shell", "ip", "-f", "inet", "addr", "show", "wlan0"]
            )
            ip = _parse_wlan_ip(addr_out)
            if not ip:
                _, route_out = _run_adb(["-s", device_id, "shell", "ip", "route"])
                ip = _parse_wlan_ip(route_out)
            if ip:
                break
            if attempt < 5:
                time.sleep(0.6)
                _run_adb(["-s", device_id, "wait-for-device"], timeout=5)
    if not ip:
        raise RuntimeError("已开启 tcpip 5555，但未能获取到设备 Wi-Fi IP（请确认手机已连接 Wi-Fi）")

    endpoint = f"{ip}:{port}"
    with _CACHE_LOCK:
        _WIRELESS_CACHE[device_id] = endpoint
    return {"device_id": device_id, "endpoint": endpoint, "port": port}


def list_mobile_devices(platform: str | None = "android") -> list[dict]:
    """扫描平台主机当前连接的手机设备并附加租约锁定状态。"""
    raw_devices: list[Device] = DeviceManager.scan_devices()
    leases = _lease_manager.list_leases()
    out: list[dict] = []
    for d in raw_devices:
        d_type = d.type.value
        if platform and d_type != platform:
            continue
        lease = leases.get(d.device_id)
        with _CACHE_LOCK:
            wireless = _WIRELESS_CACHE.get(d.device_id, "")
        out.append(
            {
                "device_id": d.device_id,
                "name": d.name,
                "type": d_type,
                "status": d.status.value,
                "model": d.model,
                "sdk_version": d.sdk_version,
                "busy": lease is not None,
                "lease": lease.to_public_dict() if lease else None,
                "wireless_endpoint": wireless,
            }
        )
    return out


def check_appium_status(appium_url: str = "http://127.0.0.1:4723", timeout: float = 2.0) -> dict:
    base = (appium_url or "http://127.0.0.1:4723").rstrip("/")
    host = (urlparse(base).hostname or "").lower()
    is_local = host in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
    try:
        with httpx.Client(timeout=timeout, trust_env=not is_local) as client:
            resp = client.get(f"{base}/status")
        if resp.status_code == 200:
            data = resp.json()
            ready = bool((data.get("value") or {}).get("ready", True))
            return {"ready": ready, "url": base, "detail": "ok"}
        return {"ready": False, "url": base, "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ready": False, "url": base, "detail": str(e)}


def doctor(appium_url: str = "http://127.0.0.1:4723", device_id: str = "") -> str:
    """运行前环境自检；返回空串表示通过，否则返回用户可读错误。"""
    try:
        import appium  # noqa: F401
    except ImportError:
        return "未安装 Appium-Python-Client，请先执行 pip install Appium-Python-Client"

    if shutil.which("adb") is None:
        return "未检测到 adb 命令，请确认平台主机已安装 Android Platform-Tools"

    status = check_appium_status(appium_url)
    if not status["ready"]:
        parsed = urlparse(appium_url)
        return (
            f"Appium 服务未就绪 ({appium_url}): {status['detail']}。"
            f"请在平台主机启动 Appium（如 appium -p {parsed.port or 4723}）"
        )

    if device_id:
        rc, out = _run_adb(["devices"], timeout=5)
        if rc != 0:
            return f"adb devices 查询失败: {out}"
        online = False
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == device_id and parts[1] == "device":
                online = True
                break
        if not online:
            return f"设备 {device_id} 未处于在线调试状态（offline/unauthorized/未连接）"
    return ""


def _wait_appium_ready(appium_url: str, wait_sec: float = 8.0) -> bool:
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if check_appium_status(appium_url, timeout=1.0)["ready"]:
            return True
        time.sleep(0.4)
    return False
