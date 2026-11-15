# -*- coding: utf-8 -*-
"""固化脚本本地执行器（pytest + Appium，零大模型调用）。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable

from insight_aitest.modules.mobile.backend.automation import paths
from insight_aitest.modules.mobile.backend.automation.app_service import build_runtime_env_payload
from insight_aitest.modules.mobile.backend.device_pool import doctor
from insight_aitest.modules.mobile.backend.persistence.models import ErrorCategory, RunStatus

logger = logging.getLogger(__name__)

RUN_RETAIN = 15
DEFAULT_TIMEOUT_SEC = 600
SCAFFOLD_PLUGIN = "insight_aitest.modules.mobile.backend.automation.scaffold"
REPO_ROOT = Path(__file__).resolve().parents[5]


class MobileEnvError(RuntimeError):
    """App 环境或设备未就绪。"""


def classify_failure(text: str) -> str:
    t = (text or "").lower()
    env_marks = (
        "connection refused",
        "max retries exceeded",
        "econnrefused",
        "could not find a connected android device",
        "device offline",
        "unauthorized",
        "adb",
        "appium",
        "sessionnotcreatedexception",
        "instrumentation process cannot be initialized",
    )
    if any(m in t for m in env_marks):
        return ErrorCategory.ENV
    case_marks = ("用例信息不完善", "前置条件缺失", "缺少步骤")
    if any(m in t for m in case_marks):
        return ErrorCategory.CASE
    return ErrorCategory.SCRIPT


def _parse_junit(junit: Path) -> tuple[int, int, str]:
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


def _coerce_param(value, kind: str):
    if kind == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if kind == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return "" if value is None else value


def _unique_value(value: str, suffix: str) -> str:
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local}{suffix}@{domain}"
    return f"{value}{suffix}"


def build_params(case) -> dict:
    schema = list(getattr(case, "params_schema_json", None) or [])
    raw = dict(getattr(case, "params_json", None) or {})
    if not schema and not raw:
        return {}
    suffix = datetime.now().strftime("%H%M%S")
    values: dict = {}
    for item in schema:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        val = raw.get(name, item.get("default", ""))
        coerced = _coerce_param(val, str(item.get("type") or "str"))
        if item.get("unique") and isinstance(coerced, str) and coerced:
            coerced = _unique_value(coerced, suffix)
        values[name] = coerced
    for key, val in raw.items():
        if key not in values:
            values[key] = val
    return {"values": values, "schema": schema}


def _prune_old_runs(project_id: int, case_id: int) -> None:
    parent = paths.workspace_root() / "artifacts" / str(project_id) / str(case_id)
    if not parent.exists():
        return
    dirs = sorted(
        (d for d in parent.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for stale in dirs[RUN_RETAIN:]:
        shutil.rmtree(stale, ignore_errors=True)


def _tail(text: str, limit: int = 3000) -> str:
    text = (text or "").strip()
    return text[-limit:] if len(text) > limit else text


def run_script(
    case,
    app,
    device_id: str,
    *,
    script_path: Path | None = None,
    out_dir: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT_SEC,
    cancel_check: Callable[[], bool] | None = None,
    skip_doctor: bool = False,
) -> dict:
    """在平台主机执行 Appium pytest 脚本并返回标准化结果 dict。"""
    if app is None:
        raise MobileEnvError("项目尚未配置可用 App 环境，请先在「设备与 App」中配置")
    if not device_id:
        raise MobileEnvError("未指定执行设备 device_id")

    project_id = int(case.project_id)
    case_id = int(case.id)

    if not skip_doctor:
        err = doctor(app.appium_url, device_id=device_id)
        if err:
            raise MobileEnvError(err)

    script = script_path or paths.resolve_rel(case.script_rel_path)
    if not script.exists():
        raise FileNotFoundError(f"脚本文件不存在: {script}")

    if out_dir is None:
        out_dir = paths.artifacts_dir(project_id, case_id)
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
    _prune_old_runs(project_id, case_id)

    junit = out_dir / "junit.xml"
    stdout_log = out_dir / "stdout.log"
    params_file = out_dir / "params.json"
    env_file = out_dir / "app_env.json"

    params_payload = build_params(case)
    if params_payload:
        params_file.write_text(
            json.dumps(params_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    env_file.write_text(
        json.dumps(build_runtime_env_payload(app), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    child_env = os.environ.copy()
    existing_pp = child_env.get("PYTHONPATH", "")
    pp_parts = [str(REPO_ROOT), str(paths.project_scripts_dir(project_id))]
    # dry_run 时优先引用 staging 目录的 pages/
    if script.parent != paths.case_dir(project_id, case_id):
        pp_parts.insert(1, str(script.parent))
    if existing_pp:
        pp_parts.append(existing_pp)
    child_env["PYTHONPATH"] = os.pathsep.join(pp_parts)

    child_env.update(
        {
            "INSIGHT_MOBILE_APPIUM_URL": app.appium_url or "http://127.0.0.1:4723",
            "INSIGHT_MOBILE_DEVICE_ID": device_id,
            "INSIGHT_MOBILE_PLATFORM": app.platform or "android",
            "INSIGHT_MOBILE_PACKAGE": app.app_package or "",
            "INSIGHT_MOBILE_ACTIVITY": app.app_activity or "",
            "INSIGHT_MOBILE_APP_PATH": (
                str(paths.resolve_rel(app.app_file_rel)) if app.app_file_rel else ""
            ),
            "INSIGHT_MOBILE_RESET_MODE": app.reset_mode or "no_reset",
            "INSIGHT_MOBILE_ARTIFACTS": str(out_dir),
            "INSIGHT_MOBILE_ENV": str(env_file),
            "INSIGHT_MOBILE_EXTRA_CAPS": json.dumps(app.extra_caps_json or {}, ensure_ascii=False),
            "INSIGHT_MOBILE_PARAMS": str(params_file) if params_payload else "",
            "INSIGHT_MOBILE_TIMEOUT_MS": "10000",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )

    started = time.time()
    status, error_message = RunStatus.PASSED, ""
    aborted = False
    stdout_log.write_text("", encoding="utf-8")

    try:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pytest",
                str(script),
                "-v",
                # -s 关闭 pytest 的输出捕获：脚本里的 print 实时写进 stdout.log，
                # 执行记录「标准日志输出」才能在运行中与通过后看到每步操作与断言日志
                "-s",
                "-p",
                "no:cacheprovider",
                "-p",
                SCAFFOLD_PLUGIN,
                "--rootdir",
                str(script.parent),
                f"--junit-xml={junit}",
            ],
            cwd=str(script.parent),
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        def _pump() -> None:
            try:
                with stdout_log.open("a", encoding="utf-8") as fh:
                    for line in proc.stdout:  # type: ignore[union-attr]
                        fh.write(line)
                        fh.flush()
            except Exception:
                pass

        pump = threading.Thread(target=_pump, daemon=True, name=f"mobile-run-log-{case_id}")
        pump.start()
        try:
            deadline = time.time() + timeout
            while True:
                if cancel_check and cancel_check():
                    proc.kill()
                    aborted = True
                    break
                remain = deadline - time.time()
                if remain <= 0:
                    proc.kill()
                    raise subprocess.TimeoutExpired(cmd="pytest", timeout=timeout)
                try:
                    proc.wait(timeout=min(remain, 0.5))
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            pump.join(timeout=3)

        if aborted:
            status = RunStatus.ERROR
            error_message = "用户已终止执行"
        else:
            output = stdout_log.read_text(encoding="utf-8", errors="replace")
            _, failures, first = _parse_junit(junit)
            if proc.returncode != 0 or failures > 0:
                status = RunStatus.FAILED if proc.returncode == 1 else RunStatus.ERROR
                error_message = first or _tail(output)
    except subprocess.TimeoutExpired:
        status = RunStatus.ERROR
        error_message = f"脚本执行超过 {timeout} 秒被终止（疑似页面卡死或设备无响应）"
        try:
            with stdout_log.open("a", encoding="utf-8") as fh:
                fh.write("\n" + error_message + "\n")
        except OSError:
            pass
    except Exception as e:
        status = RunStatus.ERROR
        error_message = f"执行器异常：{type(e).__name__}: {e}"

    duration_ms = int((time.time() - started) * 1000)
    screenshots = sorted(p.name for p in out_dir.glob("*.png"))
    device_log = out_dir / "device.log"
    script_hash = hashlib.sha256(script.read_bytes()).hexdigest()

    result = {
        "status": "passed" if status is RunStatus.PASSED else "failed",
        "run_status": status.value,
        "error_category": None if status is RunStatus.PASSED else classify_failure(error_message),
        "error_message": error_message,
        "duration_ms": duration_ms,
        "started_at": datetime.fromtimestamp(started).isoformat(),
        "finished_at": datetime.now().isoformat(),
        "device_id": device_id,
        "app_package": app.app_package,
        "script_hash": script_hash,
        "params": params_payload.get("values") or {},
        "screenshots": screenshots,
        "has_device_log": device_log.exists(),
        "cancelled": aborted,
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result["artifacts_rel_path"] = paths.to_rel(out_dir)
    result["run_dir"] = str(out_dir)
    result["stdout_tail"] = _tail(stdout_log.read_text(encoding="utf-8", errors="replace"))
    result["logcat_tail"] = (
        _tail(device_log.read_text(encoding="utf-8", errors="replace"))
        if device_log.exists()
        else ""
    )
    return result
