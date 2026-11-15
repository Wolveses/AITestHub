# -*- coding: utf-8 -*-
"""手机 App 自动化 pytest 运行脚手架插件。

由 runner.py 通过 ``python -m pytest -p insight_aitest.modules.mobile.backend.automation.scaffold`` 加载：
1. 提供 ``driver`` fixture（基于 Appium UiAutomator2Options 连接平台主机直连设备）；
2. 提供 ``params``、``app_env`` fixture；
3. 结束时捕获 ``failure.png``（失败时）与 ``final.png``，并烧入毫秒级时间戳水印；
4. 抓取设备 ``logcat`` 日志写入产物目录 ``device.log``。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

_ARTIFACTS = Path(os.environ.get("INSIGHT_MOBILE_ARTIFACTS", ".") or ".")

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _load_font(size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _watermark(path: Path, text: str) -> None:
    try:
        from PIL import Image, ImageDraw

        with Image.open(path) as raw:
            base = raw.convert("RGBA")
        font = _load_font(max(14, base.width // 60))
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        box = draw.textbbox((0, 0), text, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        pad = max(6, base.width // 300)
        x = base.width - tw - pad * 3 - box[0]
        y = base.height - th - pad * 3 - box[1]
        draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 70))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 102))
        Image.alpha_composite(base, overlay).convert("RGB").save(path, "PNG")
    except Exception:
        pass


def _shot(driver, name: str) -> None:
    target = _ARTIFACTS / name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(str(target))
    except Exception:
        return
    _watermark(target, _timestamp())


def _dump_logcat(driver, filename: str = "device.log", max_lines: int = 400) -> None:
    try:
        entries = driver.get_log("logcat") or []
    except Exception:
        return
    if not entries:
        return
    lines = []
    for item in entries[-max_lines:]:
        msg = item.get("message") if isinstance(item, dict) else str(item)
        if msg:
            lines.append(msg)
    try:
        (_ARTIFACTS / filename).write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


@pytest.fixture
def params() -> dict:
    path = os.environ.get("INSIGHT_MOBILE_PARAMS") or ""
    if not path or not os.path.exists(path):
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    values = data.get("values") if isinstance(data, dict) else None
    return dict(values) if isinstance(values, dict) else {}


@pytest.fixture
def app_env() -> dict:
    path = os.environ.get("INSIGHT_MOBILE_ENV") or ""
    if not path or not os.path.exists(path):
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@pytest.fixture
def driver(request):
    from appium import webdriver
    from appium.options.android import UiAutomator2Options

    appium_url = os.environ.get("INSIGHT_MOBILE_APPIUM_URL") or "http://127.0.0.1:4723"
    device_id = os.environ.get("INSIGHT_MOBILE_DEVICE_ID") or ""
    app_package = os.environ.get("INSIGHT_MOBILE_PACKAGE") or ""
    app_activity = os.environ.get("INSIGHT_MOBILE_ACTIVITY") or ""
    app_path = os.environ.get("INSIGHT_MOBILE_APP_PATH") or ""
    reset_mode = os.environ.get("INSIGHT_MOBILE_RESET_MODE") or "no_reset"
    timeout_ms = int(os.environ.get("INSIGHT_MOBILE_TIMEOUT_MS") or 10000)

    opts = UiAutomator2Options()
    opts.platform_name = "Android"
    opts.automation_name = "UiAutomator2"
    if device_id:
        opts.udid = device_id
    if app_package:
        opts.app_package = app_package
    if app_activity:
        opts.app_activity = app_activity
    if app_path and os.path.exists(app_path):
        opts.app = app_path
    opts.no_reset = reset_mode == "no_reset"
    opts.auto_grant_permissions = True
    opts.new_command_timeout = 120
    if app_package:
        opts.set_capability("appium:forceAppLaunch", True)
    extra_caps_raw = os.environ.get("INSIGHT_MOBILE_EXTRA_CAPS") or ""
    if extra_caps_raw:
        try:
            extra_caps = json.loads(extra_caps_raw)
            if isinstance(extra_caps, dict):
                for cap_k, cap_v in extra_caps.items():
                    opts.set_capability(str(cap_k), cap_v)
        except ValueError:
            pass

    drv = webdriver.Remote(appium_url, options=opts)
    drv.implicitly_wait(max(1, timeout_ms // 1000))
    try:
        yield drv
    finally:
        try:
            rep = getattr(request.node, "rep_call", None)
            if rep is not None and rep.failed:
                _shot(drv, "failure.png")
            _shot(drv, "final.png")
            _dump_logcat(drv)
        finally:
            try:
                drv.quit()
            except Exception:
                pass
