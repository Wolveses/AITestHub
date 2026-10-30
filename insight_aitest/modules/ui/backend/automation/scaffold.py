# -*- coding: utf-8 -*-
"""自动化脚本运行脚手架（pytest 插件，随代码版本发布）。

由 ``runner.py`` 以 ``python -m pytest -p insight_aitest...automation.scaffold`` 加载，
不落地到用户目录；用例脚本目录只保留用例本体与历史版本。

提供：
- ``page`` fixture：注入登录态（storageState / 请求头），默认超时取自环境变量；
- 每次执行结束时写终态截图 ``final.png``；失败时额外写 ``failure.png``；
- 整段执行录制 ``trace.zip``；
- 记录 ``rep_call`` 供截图判断成败。

环境变量（均由后端注入）：``INSIGHT_UI_BASE_URL``、``INSIGHT_UI_ARTIFACTS``、
``INSIGHT_UI_STORAGE_STATE``、``INSIGHT_UI_HEADERS``、``INSIGHT_UI_TIMEOUT_MS``。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

_ARTIFACTS = Path(os.environ.get("INSIGHT_UI_ARTIFACTS", ".") or ".")


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
def page(_insight_browser, request):
    kwargs = {"ignore_https_errors": True}
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
            try:
                page.screenshot(path=str(_ARTIFACTS / "failure.png"), full_page=True)
            except Exception:
                pass
        # 终态截图：每次执行都留一张，便于回看页面最后状态
        try:
            page.screenshot(path=str(_ARTIFACTS / "final.png"), full_page=True)
        except Exception:
            pass
        try:
            ctx.tracing.stop(path=str(_ARTIFACTS / "trace.zip"))
        except Exception:
            pass
    finally:
        ctx.close()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    rep = yield
    if rep.when == "call":
        item.rep_call = rep
    return rep
