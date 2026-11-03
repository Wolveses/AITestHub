# -*- coding: utf-8 -*-
"""自动化脚本运行脚手架（pytest 插件，随代码版本发布）。

由 ``runner.py`` 以 ``python -m pytest -p insight_aitest...automation.scaffold`` 加载，
不落地到用户目录；用例脚本目录只保留用例本体与历史版本。

提供：
- ``page`` fixture：注入登录态（storageState / 请求头），默认超时取自环境变量；
- 每次执行结束时写终态截图 ``final.png``；失败时额外写 ``failure.png``；
  截图右下角烧入毫秒级时间水印（40% 不透明，不铺底色）；
- 整段执行录制 ``trace.zip``；
- 记录 ``rep_call`` 供截图判断成败。

环境变量（均由后端注入）：``INSIGHT_UI_BASE_URL``、``INSIGHT_UI_ARTIFACTS``、
``INSIGHT_UI_STORAGE_STATE``、``INSIGHT_UI_HEADERS``、``INSIGHT_UI_TIMEOUT_MS``。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

_ARTIFACTS = Path(os.environ.get("INSIGHT_UI_ARTIFACTS", ".") or ".")
# 生成期首跑抓包：默认关闭，仅 runner 注入 INSIGHT_UI_CAPTURE_NETWORK=1 时开启
_CAPTURE = os.environ.get("INSIGHT_UI_CAPTURE_NETWORK") == "1"
_CAPTURE_FILE = _ARTIFACTS / "network.jsonl"
_CAPTURE_LOCK = threading.Lock()
_MAX_BODY_CHARS = 64 * 1024


def _truncate(text):
    """请求体/响应体统一截断，避免把大报文写进产物目录。"""
    if text is None:
        return None
    text = str(text)
    return text[:_MAX_BODY_CHARS]


def _record_response(resp, sink) -> None:
    """事件回调：只读取事件 payload 自带字段，不调用任何 Playwright 同步 API。"""
    try:
        req = resp.request
        rec = {
            "method": req.method,
            "url": req.url,
            "status": resp.status,
            "resource_type": getattr(req, "resource_type", "") or "",
            "request_headers": dict(req.headers or {}),
            "response_headers": dict(resp.headers or {}),
        }
        try:
            rec["request_body"] = _truncate(req.post_data)
        except Exception:
            rec["request_body"] = None
        with _CAPTURE_LOCK:
            sink.append((rec, resp))
    except Exception:
        # 抓包只做旁路记录，任何异常都不能影响用例执行
        return


def _resolve_bodies(sink) -> list[dict]:
    """用例结束后统一读取响应体（此时同步 API 调用是安全的）。"""
    records: list[dict] = []
    for rec, resp in sink:
        ctype = (rec.get("response_headers", {}).get("content-type") or "").lower()
        text_like = "json" in ctype or "text" in ctype or "xml" in ctype
        if (
            text_like
            and 200 <= int(rec.get("status") or 0) <= 499
            and rec.get("resource_type") in ("xhr", "fetch")
        ):
            try:
                text = resp.body().decode("utf-8", "replace")
                if len(text) > _MAX_BODY_CHARS:
                    text = text[:_MAX_BODY_CHARS]
                    rec["body_truncated"] = True
                try:
                    rec["response_body"] = json.loads(text)
                except ValueError:
                    rec["response_body"] = text
            except Exception:
                pass
        records.append(rec)
    return records


def _write_capture(sink) -> None:
    try:
        records = _resolve_bodies(sink)
        if not records:
            return
        _ARTIFACTS.mkdir(parents=True, exist_ok=True)
        with open(_CAPTURE_FILE, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        # 抓包产物写入失败不影响用例执行结果
        pass


# 水印字体优先级：Windows 微软雅黑 → macOS/Linux 常见中文字体 → PIL 默认位图字体
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _timestamp() -> str:
    """截图时间戳，精确到毫秒。"""
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
    """把时间戳烧进截图右下角（40% 不透明白字 + 淡阴影，不铺底色以免遮挡主体）。"""
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
        # 不铺底色，只保留 40% 不透明的文字 + 极淡描边阴影，避免遮挡页面主体
        draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 70))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 102))
        Image.alpha_composite(base, overlay).convert("RGB").save(path, "PNG")
    except Exception:
        # 水印只是辅助信息，缺字体或图片异常都不应影响用例判定
        pass


def _shot(page, name: str) -> None:
    """整页截图并烧入毫秒级时间水印。"""
    target = _ARTIFACTS / name
    try:
        page.screenshot(path=str(target), full_page=True)
    except Exception:
        return
    _watermark(target, _timestamp())


@pytest.fixture(scope="session")
def _insight_playwright():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def _insight_browser(_insight_playwright):
    browser = _insight_playwright.chromium.launch(headless=True)
    yield browser
    browser.close()


@pytest.fixture
def params():
    """用例参数（生成时从实测弹窗控件提取的 schema 默认值 + 本用例取值）。

    没有参数结构的独立脚本用例直接返回空字典；unique 参数已由后端追加运行时间后缀。
    """
    path = os.environ.get("INSIGHT_UI_PARAMS") or ""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    values = data.get("values") if isinstance(data, dict) else None
    return dict(values) if isinstance(values, dict) else {}


@pytest.fixture
def page(_insight_browser, request):
    # 固定 locale/时区/视口，避免日期控件、时区断言与人工界面不一致
    kwargs = {
        "ignore_https_errors": True,
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "viewport": {"width": 1440, "height": 900},
    }
    headers = os.environ.get("INSIGHT_UI_HEADERS") or ""
    if headers:
        try:
            kwargs["extra_http_headers"] = json.loads(headers)
        except ValueError:
            pass
    state = os.environ.get("INSIGHT_UI_STORAGE_STATE") or ""
    if state and os.path.exists(state):
        kwargs["storage_state"] = state
    ctx = _insight_browser.new_context(**kwargs)
    ctx.set_default_timeout(int(os.environ.get("INSIGHT_UI_TIMEOUT_MS") or 15000))
    sink: list = []
    if _CAPTURE:
        # 只记录旁路信息；响应体延迟到 teardown 读取，避免回调里调用同步 API
        ctx.on("response", lambda resp: _record_response(resp, sink))
    try:
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
    except Exception:
        pass
    page = ctx.new_page()
    yield page
    try:
        rep = getattr(request.node, "rep_call", None)
        failed = rep is not None and rep.failed
        if failed:
            _shot(page, "failure.png")
        # 终态截图：每次执行都留一张，便于回看页面最后状态
        _shot(page, "final.png")
        try:
            ctx.tracing.stop(path=str(_ARTIFACTS / "trace.zip"))
        except Exception:
            pass
    finally:
        if _CAPTURE:
            _write_capture(sink)
        ctx.close()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    rep = yield
    if rep.when == "call":
        item.rep_call = rep
    return rep
