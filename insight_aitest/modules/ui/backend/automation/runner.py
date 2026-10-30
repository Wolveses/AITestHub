# -*- coding: utf-8 -*-
"""固化脚本本地执行器（pytest + playwright，不调用任何大模型）。

每次执行：
1. 用环境配置请求登录接口，拿 token 并转换成 storageState / 请求头（本地网络请求）；
2. subprocess 跑 ``python -m pytest case.py``，注入 INSIGHT_UI_* 环境变量；
3. conftest 负责失败截图 + trace，runner 解析 junit 生成 result.json；
4. 写入 ui_runs（runner='script'）并记录产物目录（相对路径，可迁移）。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from insight_aitest.modules.ui.backend.automation import paths
from insight_aitest.modules.ui.backend.automation.env_service import prepare_auth, site_url
from insight_aitest.modules.ui.backend.automation.models import ErrorCategory
from insight_aitest.modules.ui.backend.persistence.models import RunRecord, RunStatus

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 600

# 每个项目目录一份 conftest：提供 page fixture、登录态注入、失败截图与 trace。
# 由脚本生成器写入项目目录，历史脚本复用；用户无需感知。
CONFTEST_CONTENT = '''# -*- coding: utf-8 -*-
"""Insight-AITest 自动化脚本运行脚手架（自动生成，请勿手改）。"""

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
'''


class EnvMissingError(RuntimeError):
    """项目未配置可用环境。"""


def ensure_conftest(project_id: int) -> Path:
    """按项目写 conftest（幂等覆盖，保证脚手架升级立即生效）。"""
    d = paths.project_scripts_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "conftest.py"
    p.write_text(CONFTEST_CONTENT, encoding="utf-8")
    return p


def classify_failure(text: str) -> str:
    """失败原因规则分类（不调用模型）。"""
    t = (text or "").lower()
    env_marks = (
        "executable doesn't exist",
        "playwright install",
        "err_connection",
        "err_name_not_resolved",
        "econnrefused",
        "net::err",
        "browser closed",
        "target page, context or browser has been closed",
        "failed to launch",
        "timeout 30000ms exceeded while navigating",
    )
    if any(m in t for m in env_marks):
        return ErrorCategory.ENV
    case_marks = ("用例信息不完善", "前置条件缺失", "缺少步骤", "expected text not found")
    if any(m in t for m in case_marks):
        return ErrorCategory.CASE
    return ErrorCategory.SCRIPT


def _parse_junit(junit: Path) -> tuple[int, int, str]:
    """返回 (tests, failures, 首条失败信息)。"""
    if not junit.exists():
        return 0, 0, ""
    try:
        root = ET.parse(junit).getroot()
    except ET.ParseError:
        return 0, 0, ""
    suites = [root] if root.tag == "testsuite" else list(root)
    tests = failures = 0
    first = ""
    for suite in suites:
        tests += int(suite.get("tests") or 0)
        failures += int(suite.get("failures") or 0) + int(suite.get("errors") or 0)
        for case in suite.iter("testcase"):
            for bad in list(case.findall("failure")) + list(case.findall("error")):
                if not first:
                    msg = bad.get("message") or ""
                    body = (bad.text or "").strip()
                    first = (msg + "\n" + body).strip()
    return tests, failures, first[:6000]


def run_script(
    case,
    env,
    *,
    script_path: Path | None = None,
    run_dir: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT_SEC,
    auth=None,
) -> dict:
    """执行一个固化脚本，返回结果摘要（不写 ui_runs，由调用方决定是否落库）。"""
    if env is None:
        raise EnvMissingError("项目未配置环境，请先在环境管理中新增并测试通过")

    project_id = int(case.project_id)
    case_id = int(case.id)
    script = script_path or paths.case_script(project_id, case_id)
    if not script.exists():
        return {
            "status": "error",
            "error_category": ErrorCategory.ENV,
            "error_message": "脚本文件不存在，请先生成脚本",
            "duration_ms": 0,
            "artifacts_rel_path": "",
            "trace_rel_path": "",
            "screenshots": [],
        }

    ensure_conftest(project_id)
    if auth is None:
        auth = prepare_auth(env)
    if not auth.ok:
        return {
            "status": "error",
            "error_category": ErrorCategory.ENV,
            "error_message": f"登录态准备失败：{auth.message}",
            "duration_ms": 0,
            "artifacts_rel_path": "",
            "trace_rel_path": "",
            "screenshots": [],
        }

    out_dir = run_dir or paths.new_run_dir(project_id, case_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    junit = out_dir / "junit.xml"
    stdout_log = out_dir / "stdout.log"

    target_url = site_url(env, getattr(case, "site", "") or "")
    child_env = dict(os.environ)
    child_env.update(
        {
            "INSIGHT_UI_BASE_URL": target_url,
            "INSIGHT_UI_ARTIFACTS": str(out_dir),
            "INSIGHT_UI_STORAGE_STATE": auth.storage_state_path or "",
            "INSIGHT_UI_HEADERS": json.dumps(auth.headers, ensure_ascii=False),
            "INSIGHT_UI_TIMEOUT_MS": "15000",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )

    started = time.time()
    status = RunStatus.PASSED
    error_message = ""
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(script),
                "-q",
                "-p",
                "no:cacheprovider",
                # 固定 rootdir 到项目脚本目录，确保祖先 conftest.py 被加载
                "--rootdir",
                str(paths.project_scripts_dir(project_id)),
                f"--junit-xml={junit}",
            ],
            cwd=str(script.parent),
            env=child_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        stdout_log.write_text(output, encoding="utf-8")
        tests, failures, first = _parse_junit(junit)
        if proc.returncode != 0 or failures > 0:
            status = RunStatus.FAILED if proc.returncode in (1,) else RunStatus.ERROR
            error_message = first or _tail(output)
    except subprocess.TimeoutExpired:
        status = RunStatus.ERROR
        error_message = f"脚本执行超过 {timeout} 秒被终止（疑似页面卡死或等待超时）"
        try:
            stdout_log.write_text(error_message, encoding="utf-8")
        except OSError:
            pass
    except Exception as e:
        status = RunStatus.ERROR
        error_message = f"执行器异常：{type(e).__name__}: {e}"

    duration_ms = int((time.time() - started) * 1000)
    screenshots = sorted(p.name for p in out_dir.glob("*.png"))
    trace = out_dir / "trace.zip"
    result = {
        "status": "passed" if status is RunStatus.PASSED else "failed",
        "run_status": status.value,
        "error_category": None if status is RunStatus.PASSED else classify_failure(error_message),
        "error_message": error_message,
        "duration_ms": duration_ms,
        "started_at": datetime.fromtimestamp(started).isoformat(),
        "finished_at": datetime.now().isoformat(),
        "base_url": target_url,
        "site": getattr(case, "site", "") or "",
        "screenshots": screenshots,
        "has_trace": trace.exists(),
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result["artifacts_rel_path"] = paths.to_rel(out_dir)
    result["trace_rel_path"] = paths.to_rel(trace) if trace.exists() else ""
    result["run_dir"] = str(out_dir)
    return result


def _tail(text: str, limit: int = 3000) -> str:
    text = (text or "").strip()
    return text[-limit:] if len(text) > limit else text


def record_run(case, env, result: dict) -> int:
    """把执行结果写入 ui_runs（runner='script'）。"""
    from insight_aitest.modules.ui.backend.automation.deps import get_automation_db

    started = datetime.fromisoformat(result["started_at"])
    finished = datetime.fromisoformat(result["finished_at"])
    status = RunStatus(result.get("run_status") or "failed")
    run = RunRecord(
        case_id=int(case.id),
        case_title=case.title or "",
        case_snapshot={
            "title": case.title,
            "precondition": case.precondition,
            "steps": list(case.steps or []),
            "expected": case.expected,
        },
        status=status,
        total_steps=0,
        passed_steps=1 if status is RunStatus.PASSED else 0,
        started_at=started,
        finished_at=finished,
        duration_ms=int(result.get("duration_ms") or 0),
        steps=[],
        base_url_used=result.get("base_url") or "",
        project_id=int(case.project_id),
        error=result.get("error_message") or None,
        runner="script",
        env_id=int(env.id) if env is not None else None,
        script_version=int(case.script_version or 0),
        artifacts_rel_path=result.get("artifacts_rel_path") or "",
        trace_rel_path=result.get("trace_rel_path") or "",
    )
    run_id = get_automation_db().create_script_run(run)
    fields = {"last_run_id": run_id}
    if status is not RunStatus.PASSED:
        fields["last_error_category"] = result.get("error_category")
        fields["last_error_message"] = (result.get("error_message") or "")[:4000]
    get_automation_db().update_case(int(case.id), **fields)
    return run_id
