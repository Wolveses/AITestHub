# -*- coding: utf-8 -*-
"""固化脚本本地执行器（pytest + playwright，不调用任何大模型）。

每次执行：
1. 用环境配置请求登录接口，拿 token 并转换成 storageState / 请求头（本地网络请求）；
2. subprocess 跑 ``python -m pytest case.py``，注入 INSIGHT_UI_* 环境变量，
   并以 ``-p`` 加载仓库内脚手架插件（scaffold.py，提供 page fixture 与截图/trace）；
3. 解析 junit 生成 result.json；
4. 写入 ui_runs（runner='script'）并记录产物目录（相对路径，可迁移）。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
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

# 运行脚手架在仓库内实现（scaffold.py），通过 `-p` 以 pytest 插件加载，
# 用户目录只保留用例脚本与产物，不落地 conftest 副本。
SCAFFOLD_PLUGIN = "insight_aitest.modules.ui.backend.automation.scaffold"
# 仓库根目录：注入 PYTHONPATH，保证子进程能 import 脚手架插件
REPO_ROOT = Path(__file__).resolve().parents[5]


class EnvMissingError(RuntimeError):
    """项目未配置可用环境。"""


def drop_legacy_conftest(project_id: int) -> None:
    """清理旧版落在用户目录的 conftest 副本（脚手架已改为仓库内插件）。"""
    p = paths.project_scripts_dir(project_id) / "conftest.py"
    try:
        p.unlink()
    except OSError:
        pass


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


def _coerce_param(value, kind: str):
    """按参数类型做最小转换（非法值原样保留，交由脚本/断言暴露问题）。"""
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
    """给需要唯一的数据追加时间后缀。

    后缀只用数字且不加连接符：被测系统常限制用户名只能字母/数字/中文，
    带下划线会被格式校验拒绝，弹窗点「确定」后保持打开导致首跑误判失败。
    邮箱则把后缀插到 ``@`` 前，保证邮箱格式仍然合法。
    """
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local}{suffix}@{domain}"
    return f"{value}{suffix}"


def build_params(case) -> dict:
    """合并流程参数 schema 与本用例取值，返回 ``{"values": ..., "schema": ...}``。

    - 取值优先级：本用例 params_json → schema.default → 空串；
    - ``unique=true`` 的参数追加本次运行时间后缀，避免重复创建冲突；
    - 没有流程参数（schema 与取值都为空）时返回空字典，独立脚本不受影响。
    """
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
        value = raw.get(name)
        if value is None or value == "":
            value = item.get("default")
        value = _coerce_param(value, str(item.get("type") or "str"))
        if item.get("unique") and value not in ("", None):
            value = _unique_value(str(value), suffix)
        values[name] = value
    # schema 之外的取值原样保留（手工补充或历史数据）
    for key, value in raw.items():
        if key not in values:
            values[key] = value
    return {"values": values, "schema": schema}


def run_script(
    case,
    env,
    *,
    script_path: Path | None = None,
    run_dir: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT_SEC,
    auth=None,
    pages_root: Path | None = None,
    retries: int = 0,
) -> dict:
    """执行一个固化脚本，返回结果摘要（不写 ui_runs，由调用方决定是否落库）。

    retries: 失败后额外重试次数（仅用于吸收 UI 抖动，默认 0）。
    pages_root: 覆盖项目资产根目录（含 common/ 与 pages/ 包）。生成期首跑传暂存目录，
        避免未验证的资产污染正式目录；不传时默认 ``scripts/<project_id>``。
    """
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

    drop_legacy_conftest(project_id)
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

    # 参数化：schema 默认值 ← 本用例取值，unique 参数追加运行后缀，供 params fixture 读取
    params_payload = build_params(case)
    params_file = out_dir / "params.json"
    if params_payload:
        params_file.write_text(
            json.dumps(params_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    target_url = site_url(env, getattr(case, "site", "") or "")
    child_env = dict(os.environ)
    child_env.update(
        {
            "INSIGHT_UI_BASE_URL": target_url,
            "INSIGHT_UI_ARTIFACTS": str(out_dir),
            "INSIGHT_UI_DATA_DIR": str(paths.data_dir(project_id)),
            "INSIGHT_UI_PARAMS": str(params_file) if params_payload else "",
            "INSIGHT_UI_STORAGE_STATE": auth.storage_state_path or "",
            "INSIGHT_UI_HEADERS": json.dumps(auth.headers, ensure_ascii=False),
            "INSIGHT_UI_TIMEOUT_MS": "15000",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    # 子进程 cwd 在用例目录，需显式补仓库根目录（import 脚手架插件）与资产根目录（import common/pages）
    existing = child_env.get("PYTHONPATH") or ""
    child_env["PYTHONPATH"] = os.pathsep.join(
        p
        for p in (
            str(REPO_ROOT),
            str(pages_root or paths.project_scripts_dir(project_id)),
            existing,
        )
        if p
    )

    started = time.time()
    status = RunStatus.ERROR
    error_message = ""
    attempts = 0
    for attempt in range(retries + 1):
        attempts = attempt + 1
        status, error_message = RunStatus.PASSED, ""
        # 失败重试会清理上一轮产物（含 params.json），每轮重写保证 params fixture 可读
        if params_payload:
            params_file.write_text(
                json.dumps(params_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        try:
            # 输出实时落盘：前端在执行记录里轮询 stdout.log 就能看到运行过程，
            # 结束后文件保留完整日志（不能用 subprocess.run 的 capture_output，那要等结束才写）
            stdout_log.write_text("", encoding="utf-8")
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(script),
                    # -v 让每个用例的进度逐行输出，前端看到的执行过程更具体
                    "-v",
                    "-p",
                    "no:cacheprovider",
                    # 脚手架以插件形式加载（不在用例目录写 conftest）
                    "-p",
                    SCAFFOLD_PLUGIN,
                    # 固定 rootdir 到项目脚本目录，避免继承仓库的 pytest 配置
                    "--rootdir",
                    str(paths.project_scripts_dir(project_id)),
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
                except Exception:  # 进程被杀时管道中断是预期内的
                    pass

            pump = threading.Thread(target=_pump, daemon=True, name=f"ui-run-log-{case_id}")
            pump.start()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise
            finally:
                pump.join(timeout=3)
            output = stdout_log.read_text(encoding="utf-8", errors="replace")
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
        if status is RunStatus.PASSED or attempt >= retries:
            break
        # 失败重试：清掉上一轮产物，避免截图/trace 混淆
        for stale in out_dir.glob("*"):
            if stale.is_file():
                try:
                    stale.unlink()
                except OSError:
                    pass

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
        "params": params_payload.get("values") or {},
        "screenshots": screenshots,
        "has_trace": trace.exists(),
        "attempts": attempts,
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


def start_run(case, env) -> tuple[int, Path]:
    """执行前先落一条 RUNNING 记录，返回 (run_id, 产物目录)。

    先落库再执行，前端在执行记录里就能看到「执行中」并轮询日志；结束后回填终态。
    """
    from insight_aitest.modules.ui.backend.automation.deps import get_automation_db

    out_dir = paths.new_run_dir(int(case.project_id), int(case.id))
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    db = get_automation_db()
    run = RunRecord(
        case_id=int(case.id),
        case_title=case.title or "",
        case_snapshot={
            "title": case.title,
            "precondition": case.precondition,
            "steps": list(case.steps or []),
            "expected": case.expected,
        },
        status=RunStatus.RUNNING,
        total_steps=0,
        passed_steps=0,
        started_at=now,
        finished_at=now,
        duration_ms=0,
        steps=[],
        base_url_used=site_url(env, getattr(case, "site", "") or "") if env else "",
        project_id=int(case.project_id),
        error=None,
        runner="script",
        env_id=int(env.id) if env is not None else None,
        script_version=int(case.script_version or 0),
        artifacts_rel_path=paths.to_rel(out_dir),
        trace_rel_path="",
    )
    run_id = db.create_script_run(run)
    db.update_case(int(case.id), last_run_id=run_id)
    return run_id, out_dir


def finish_run(run_id: int, case, result: dict) -> None:
    """执行结束回填终态、耗时、错误与产物路径，并同步用例的最近错误。"""
    from insight_aitest.modules.ui.backend.automation.deps import get_automation_db

    db = get_automation_db()
    status = RunStatus(result.get("run_status") or "failed")
    finished = datetime.fromisoformat(result["finished_at"])
    db.update_script_run(
        run_id,
        status=status,
        finished_at=finished,
        duration_ms=int(result.get("duration_ms") or 0),
        error=result.get("error_message") or None,
        artifacts_rel_path=result.get("artifacts_rel_path") or "",
        trace_rel_path=result.get("trace_rel_path") or "",
        base_url_used=result.get("base_url") or "",
    )
    fields = {"last_run_id": run_id}
    if status is not RunStatus.PASSED:
        fields["last_error_category"] = result.get("error_category")
        fields["last_error_message"] = (result.get("error_message") or "")[:4000]
    else:
        # 最后一次执行通过后，不再展示历史脚本缺陷
        fields["last_error_category"] = None
        fields["last_error_message"] = ""
    db.update_case(int(case.id), **fields)
