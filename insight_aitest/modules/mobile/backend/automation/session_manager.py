# -*- coding: utf-8 -*-
"""生成会话管理器：管理设备租约、暂存区工作空间、Appium 探索会话、试跑验真与固化提交。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from insight_aitest.modules.mobile.backend.automation import paths
from insight_aitest.modules.mobile.backend.automation.runner import run_script
from insight_aitest.modules.mobile.backend.automation.tree_pruner import ElementRef, prune_android_xml
from insight_aitest.modules.mobile.backend.automation.validator import validate_staging_dir
from insight_aitest.modules.mobile.backend.deps import get_mobile_db
from insight_aitest.modules.mobile.backend.device_pool import (
    DeviceBusyError,
    get_lease_manager,
    hash_token,
)
from insight_aitest.modules.mobile.backend.persistence.models import (
    CaseStatus,
    ErrorCategory,
    GenerationKind,
    GenerationStatus,
    RunStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class SessionRuntime:
    generation_id: int
    case_id: int
    project_id: int
    app_id: int
    device_id: str
    staging: Path
    driver: Any = None
    ref_map: dict[str, ElementRef] = field(default_factory=dict)
    step_seq: int = 0
    tool_calls: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


_RUNTIMES: dict[int, SessionRuntime] = {}
_RUNTIME_LOCK = threading.Lock()


def get_runtime(generation_id: int) -> SessionRuntime | None:
    with _RUNTIME_LOCK:
        return _RUNTIMES.get(generation_id)


def _close_driver(rt: SessionRuntime) -> None:
    drv = rt.driver
    rt.driver = None
    if drv is not None:
        try:
            drv.quit()
        except Exception:
            pass


def _prepare_staging(project_id: int, case_id: int) -> Path:
    """初始化暂存区：拷贝正式 pages/、common/ 与已有 case.py（若存在）。"""
    stg = paths.staging_dir(project_id, case_id)
    for sub in ("pages", "common"):
        dst = stg / sub
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        src = paths.project_scripts_dir(project_id) / sub
        if src.exists():
            shutil.copytree(src, dst)
        else:
            dst.mkdir(parents=True, exist_ok=True)
            (dst / "__init__.py").write_text("# -*- coding: utf-8 -*-\n", encoding="utf-8")

    existing_case = paths.case_script_path(project_id, case_id)
    stg_case = stg / "case.py"
    if existing_case.exists():
        shutil.copy2(existing_case, stg_case)
    elif stg_case.exists():
        stg_case.unlink()
    return stg


def append_event(case_id: int, gen_id: int, event_type: str, **payload: Any) -> None:
    """追加写入 JSONL 过程日志，供前端轮询展示。"""
    log_path = paths.generation_log_path(case_id, gen_id)
    entry = {
        "ts": datetime.now().isoformat(),
        "type": event_type,
        **payload,
    }
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("写入生成事件日志失败 case=%s gen=%s", case_id, gen_id)


def read_events(case_id: int, gen_id: int, limit: int = 200) -> list[dict]:
    log_path = paths.generation_log_path(case_id, gen_id)
    if not log_path.exists():
        return []
    out: list[dict] = []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def list_step_screenshots(case_id: int, gen_id: int) -> list[str]:
    d = paths.generation_steps_dir(case_id, gen_id)
    if not d.exists():
        return []
    return sorted(p.name for p in d.glob("*.png"))


def build_agent_prompt(case, app, device_id: str) -> str:
    steps_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(case.steps or []))
    return (
        f"请为手机 App 自动化用例 #{case.id}「{case.title}」生成并验证通过 Python pytest 脚本。\n\n"
        f"## 目标环境\n"
        f"- 平台: {app.platform} (包名: {app.app_package}, Activity: {app.app_activity or '默认'})\n"
        f"- 平台主机设备 ID: {device_id}\n\n"
        f"## 用例详情\n"
        f"- 前置条件: {case.precondition or '无'}\n"
        f"- 测试步骤:\n{steps_text or '(无)'}\n"
        f"- 预期结果: {case.expected or '无'}\n\n"
        f"## 执行要求（必须严格遵守）\n"
        f"1. 先调用 `get_case_context` 获取项目已有 `pages/` 页面对象和避坑经验；\n"
        f"2. 使用 `mobile_launch_app`、`mobile_snapshot`、`mobile_screenshot`、`mobile_tap`、`mobile_input`、`mobile_swipe` 在真机上真实探索每一步；\n"
        f"3. 优先按工具返回的推荐定位器（accessibility_id / resource-id / text）编写 `case.py`（禁止绝对像素坐标 `tap([(x, y)])`）；\n"
        f"4. 脚本必须包含 `def test_case(driver, params, app_env):`（使用脚手架注入的 `driver` fixture，不要自己创建 `webdriver.Remote`）；\n"
        f"5. 通过 `write_staging_file` 写入 `case.py` 后，必须调用 `run_server_dry_run` 在平台主机真实试跑验证；失败请根据返回报错修复再试；\n"
        f"6. 试跑通过后，调用 `commit_staging_script` 完成固化入库。"
    )


def start_generation_session(
    case_id: int,
    *,
    device_id: str,
    app_id: int,
    kind: str = GenerationKind.GENERATE,
    engine_detail: str = "remote_mcp",
    base_url: str = "",
) -> dict:
    """申请设备锁、初始化暂存区并创建生成会话，返回 MCP 接入配置与 Token。"""
    db = get_mobile_db()
    case = db.get_case(case_id)
    if case is None:
        raise ValueError("自动化用例不存在")
    if kind == GenerationKind.FIX and not case.script_rel_path:
        raise ValueError("该用例尚未生成脚本，请先执行生成")

    app = db.get_app(app_id)
    if app is None or int(app.project_id) != int(case.project_id):
        raise ValueError("选定的 App 环境不存在或不属于当前项目")

    lease_mgr = get_lease_manager()
    attempt = db.count_generations(case_id) + 1

    # 先创建 generation 占位拿 ID，再绑租约（失败则回滚状态）
    gen_id = db.create_generation(
        mobile_case_id=case_id,
        kind=kind,
        attempt=attempt,
        status=GenerationStatus.RUNNING,
        engine_type="local_agent",
        engine_detail=engine_detail,
        device_id=device_id,
        app_id=app_id,
        session_token_hash="",
        log_rel_path="",
    )

    try:
        lease, raw_token = lease_mgr.acquire(
            device_id,
            holder_type="generation",
            case_id=case_id,
            generation_id=gen_id,
        )
    except DeviceBusyError:
        db.update_generation(
            gen_id,
            status=GenerationStatus.FAILED,
            error_category=ErrorCategory.ENV,
            error_message=f"设备 {device_id} 当前被占用",
            finished_at=datetime.now(),
        )
        raise

    staging = _prepare_staging(int(case.project_id), case_id)
    log_path = paths.generation_log_path(case_id, gen_id)
    log_path.write_text("", encoding="utf-8")

    db.update_generation(
        gen_id,
        session_token_hash=hash_token(raw_token),
        log_rel_path=paths.to_rel(log_path),
    )
    db.update_case(
        case_id,
        status=CaseStatus.FIXING if kind == GenerationKind.FIX else CaseStatus.GENERATING,
    )

    with _RUNTIME_LOCK:
        _RUNTIMES[gen_id] = SessionRuntime(
            generation_id=gen_id,
            case_id=case_id,
            project_id=int(case.project_id),
            app_id=app_id,
            device_id=device_id,
            staging=staging,
        )

    append_event(
        case_id,
        gen_id,
        "session_started",
        device_id=device_id,
        app_id=app_id,
        kind=kind,
    )

    mcp_url = f"{base_url.rstrip('/')}/api/modules/mobile/mcp" if base_url else "/api/modules/mobile/mcp"
    mcp_config = {
        "mcpServers": {
            "insight-mobile": {
                "type": "http",
                "url": mcp_url,
                "headers": {"Authorization": f"Bearer {raw_token}"},
            }
        }
    }
    return {
        "generation_id": gen_id,
        "case_id": case_id,
        "device_id": device_id,
        "app_id": app_id,
        "session_token": raw_token,
        "expires_at": lease.expires_at.isoformat(),
        "mcp_url": mcp_url,
        "mcp_config": mcp_config,
        "agent_prompt": build_agent_prompt(case, app, device_id),
    }


def authenticate_session(token: str) -> tuple[SessionRuntime, Any]:
    """校验 MCP Bearer Token 并自动续期设备租约。"""
    lease = get_lease_manager().verify_and_touch(token)
    if lease is None or lease.generation_id is None:
        raise PermissionError("MCP 会话 Token 无效或已过期")

    db = get_mobile_db()
    gen = db.get_generation(lease.generation_id)
    if gen is None or gen.status != GenerationStatus.RUNNING:
        raise PermissionError("生成会话已结束或已取消")

    rt = get_runtime(lease.generation_id)
    if rt is None:
        case = db.get_case(gen.mobile_case_id)
        if case is None:
            raise PermissionError("关联用例不存在")
        rt = SessionRuntime(
            generation_id=int(gen.id),
            case_id=int(case.id),
            project_id=int(case.project_id),
            app_id=int(gen.app_id or 0),
            device_id=gen.device_id,
            staging=paths.staging_dir(int(case.project_id), int(case.id)),
        )
        with _RUNTIME_LOCK:
            _RUNTIMES[int(gen.id)] = rt
    return rt, gen


def cancel_generation_session(case_id: int, reason: str = "用户取消生成") -> bool:
    """取消用例当前进行中的生成会话并释放设备锁。"""
    db = get_mobile_db()
    case = db.get_case(case_id)
    if case is None:
        return False

    gens = db.list_generations(case_id, limit=5)
    cancelled_any = False
    for gen in gens:
        if gen.status != GenerationStatus.RUNNING:
            continue
        db.update_generation(
            int(gen.id),
            status=GenerationStatus.CANCELLED,
            error_message=reason,
            finished_at=datetime.now(),
        )
        if gen.device_id:
            get_lease_manager().release(gen.device_id, force=True)
        rt = get_runtime(int(gen.id))
        if rt is not None:
            _close_driver(rt)
            with _RUNTIME_LOCK:
                _RUNTIMES.pop(int(gen.id), None)
        append_event(case_id, int(gen.id), "session_cancelled", reason=reason)
        cancelled_any = True

    next_status = CaseStatus.IMPLEMENTED if case.script_rel_path else CaseStatus.NOT_IMPLEMENTED
    db.update_case(case_id, status=next_status)
    return cancelled_any


# ===== MCP 工具核心业务逻辑 =====


def _ensure_driver(rt: SessionRuntime, *, clear_data: bool = False):
    if rt.driver is not None and not clear_data:
        return rt.driver

    _close_driver(rt)
    db = get_mobile_db()
    app = db.get_app(rt.app_id)
    if app is None:
        raise RuntimeError("App 环境不存在")

    from appium import webdriver
    from appium.options.android import UiAutomator2Options

    opts = UiAutomator2Options()
    opts.platform_name = "Android"
    opts.automation_name = "UiAutomator2"
    opts.udid = rt.device_id
    if app.app_package:
        opts.app_package = app.app_package
    if app.app_activity:
        opts.app_activity = app.app_activity
    if app.app_file_rel:
        local_apk = paths.resolve_rel(app.app_file_rel)
        if local_apk.exists():
            opts.app = str(local_apk)
    opts.no_reset = (not clear_data) and (app.reset_mode == "no_reset")
    opts.auto_grant_permissions = True
    opts.new_command_timeout = 180
    if app.app_package:
        opts.set_capability("appium:forceAppLaunch", True)
    for cap_k, cap_v in (app.extra_caps_json or {}).items():
        opts.set_capability(str(cap_k), cap_v)

    rt.driver = webdriver.Remote(app.appium_url or "http://127.0.0.1:4723", options=opts)
    rt.driver.implicitly_wait(8)
    return rt.driver


def _pages_summary(project_id: int) -> list[dict]:
    pdir = paths.pages_dir(project_id)
    out = []
    for f in sorted(pdir.glob("*.py")):
        if f.name == "__init__.py":
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        out.append({"path": f"pages/{f.name}", "preview": txt[:1200]})
    return out


def tool_get_case_context(rt: SessionRuntime) -> dict:
    db = get_mobile_db()
    case = db.get_case(rt.case_id)
    app = db.get_app(rt.app_id)
    lessons = [
        {"title": l.title, "content": l.content}
        for l in db.list_lessons(rt.project_id, limit=5)
    ]
    return {
        "case": {
            "id": case.id,
            "title": case.title,
            "precondition": case.precondition,
            "steps": list(case.steps or []),
            "expected": case.expected,
            "params": dict(case.params_json or {}),
            "params_schema": list(case.params_schema_json or []),
        },
        "app": {
            "platform": app.platform if app else "android",
            "app_package": app.app_package if app else "",
            "app_activity": app.app_activity if app else "",
            "reset_mode": app.reset_mode if app else "no_reset",
            "test_username": app.test_username if app else "",
            "has_password": bool(app and app.password_ref),
        },
        "device_id": rt.device_id,
        "existing_pages": _pages_summary(rt.project_id),
        "lessons": lessons,
        "scaffold_rules": [
            "入口函数签名必须为 def test_case(driver, params, app_env): （或接收 driver）",
            "不要在脚本中调用 webdriver.Remote，直接使用脚手架传入的 driver fixture",
            "禁止使用 driver.tap([(x, y)]) 等绝对像素坐标，优先使用 AppiumBy.ACCESSIBILITY_ID / ID / ANDROID_UIAUTOMATOR",
            "测试账号与密码可从 app_env.get('test_username') / app_env.get('test_password') 读取",
            "可复用的页面操作封装可写入 pages/<name>.py 并由 case.py 导入",
        ],
    }


def tool_snapshot(rt: SessionRuntime, *, compact: bool = False) -> dict:
    drv = _ensure_driver(rt)
    xml_src = drv.page_source
    activity = ""
    try:
        activity = drv.current_activity or ""
    except Exception:
        pass
    size = None
    try:
        win = drv.get_window_size()
        size = (int(win["width"]), int(win["height"]))
    except Exception:
        pass
    snap = prune_android_xml(xml_src, activity=activity, screen_size=size, compact=compact)
    rt.ref_map = snap.refs
    return {
        "activity": activity,
        "raw_nodes": snap.total_raw_nodes,
        "kept_nodes": snap.kept_nodes,
        "snapshot": snap.text,
    }


def tool_screenshot(rt: SessionRuntime, label: str = "") -> tuple[bytes, str]:
    drv = _ensure_driver(rt)
    png_bytes: bytes = drv.get_screenshot_as_png()
    rt.step_seq += 1
    safe_label = "".join(c for c in (label or "shot") if c.isalnum() or c in ("-", "_"))[:24]
    filename = f"{rt.step_seq:03d}_{safe_label or 'shot'}.png"
    target = paths.generation_steps_dir(rt.case_id, rt.generation_id) / filename
    target.write_bytes(png_bytes)
    append_event(
        rt.case_id,
        rt.generation_id,
        "screenshot",
        filename=filename,
        label=label,
    )
    return png_bytes, filename


def _find_element_for_ref(drv, item: ElementRef):
    from appium.webdriver.common.appiumby import AppiumBy

    if item.content_desc:
        try:
            return drv.find_element(AppiumBy.ACCESSIBILITY_ID, item.content_desc)
        except Exception:
            pass
    if item.resource_id:
        try:
            return drv.find_element(AppiumBy.ID, item.resource_id)
        except Exception:
            pass
    if item.text:
        try:
            return drv.find_element(
                AppiumBy.ANDROID_UIAUTOMATOR, f"new UiSelector().text({item.text!r})"
            )
        except Exception:
            pass
    return drv.find_element(AppiumBy.XPATH, item.xpath)


def tool_tap(rt: SessionRuntime, ref: str) -> dict:
    item = rt.ref_map.get(ref)
    if item is None:
        raise ValueError(f"无效的 ref={ref}，请先调用 mobile_snapshot 获取当前界面控件")
    drv = _ensure_driver(rt)
    try:
        el = _find_element_for_ref(drv, item)
        el.click()
    except Exception:
        # 若瞬时控件不可点击，回退到 bounds 中心点（仅用于探索期交互）
        x1, y1, x2, y2 = item.bounds
        drv.tap([((x1 + x2) // 2, (y1 + y2) // 2)])
    strategy, value, snippet = item.recommended_locator()
    return {
        "ok": True,
        "ref": ref,
        "recommended_locator": {"strategy": strategy, "value": value, "snippet": snippet},
    }


def tool_input(
    rt: SessionRuntime, ref: str, text: str, *, clear_first: bool = True, hide_keyboard: bool = False
) -> dict:
    item = rt.ref_map.get(ref)
    if item is None:
        raise ValueError(f"无效的 ref={ref}，请先调用 mobile_snapshot 获取当前界面控件")
    drv = _ensure_driver(rt)
    el = _find_element_for_ref(drv, item)
    if clear_first:
        try:
            el.clear()
        except Exception:
            pass
    el.send_keys(text)
    if hide_keyboard:
        try:
            drv.hide_keyboard()
        except Exception:
            pass
    strategy, value, snippet = item.recommended_locator()
    return {
        "ok": True,
        "ref": ref,
        "recommended_locator": {"strategy": strategy, "value": value, "snippet": snippet},
    }


def tool_swipe(rt: SessionRuntime, direction: str = "up", distance_ratio: float = 0.5) -> dict:
    drv = _ensure_driver(rt)
    win = drv.get_window_size()
    w, h = int(win["width"]), int(win["height"])
    ratio = max(0.15, min(float(distance_ratio), 0.85))
    cx, cy = w // 2, h // 2
    dy = int(h * ratio / 2)
    dx = int(w * ratio / 2)
    d = (direction or "up").lower()
    if d == "up":
        drv.swipe(cx, cy + dy, cx, cy - dy, 400)
    elif d == "down":
        drv.swipe(cx, cy - dy, cx, cy + dy, 400)
    elif d == "left":
        drv.swipe(cx + dx, cy, cx - dx, cy, 400)
    elif d == "right":
        drv.swipe(cx - dx, cy, cx + dx, cy, 400)
    else:
        raise ValueError("direction 必须是 up / down / left / right")
    return {"ok": True, "direction": d}


def _resolve_staging_path(staging: Path, rel_path: str) -> Path:
    norm = (rel_path or "").replace("\\", "/").lstrip("/")
    if not norm or ".." in Path(norm).parts:
        raise ValueError("非法的暂存文件路径")
    if norm != "case.py" and not norm.startswith("pages/"):
        raise ValueError("仅允许读写 case.py 或 pages/*.py")
    target = (staging / norm).resolve()
    if not str(target).startswith(str(staging.resolve())):
        raise ValueError("路径越界")
    return target


def tool_read_staging_file(rt: SessionRuntime, rel_path: str) -> dict:
    target = _resolve_staging_path(rt.staging, rel_path)
    if not target.exists():
        return {"exists": False, "path": rel_path, "content": ""}
    return {"exists": True, "path": rel_path, "content": target.read_text(encoding="utf-8")}


def tool_write_staging_file(rt: SessionRuntime, rel_path: str, content: str) -> dict:
    target = _resolve_staging_path(rt.staging, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {"ok": True, "path": rel_path, "bytes": len(content.encode("utf-8")), "sha256": digest}


def tool_run_server_dry_run(rt: SessionRuntime) -> dict:
    """在平台主机真实执行暂存区脚本试跑（先释放探索 Session 防 UiAutomation 抢占）。"""
    _close_driver(rt)
    err = validate_staging_dir(rt.staging)
    if err:
        get_mobile_db().update_generation(rt.generation_id, last_dry_run_passed=0)
        append_event(rt.case_id, rt.generation_id, "dry_run_rejected", error=err)
        return {"passed": False, "stage": "static_validation", "error": err}

    db = get_mobile_db()
    case = db.get_case(rt.case_id)
    app = db.get_app(rt.app_id)
    stg_case = rt.staging / "case.py"
    script_hash = hashlib.sha256(stg_case.read_bytes()).hexdigest()

    run_id = db.create_run(
        case_id=rt.case_id,
        project_id=rt.project_id,
        app_id=rt.app_id,
        case_title=case.title if case else "",
        case_snapshot={"title": case.title, "steps": list(case.steps or [])} if case else {},
        status=RunStatus.RUNNING,
        runner="dry_run",
        device_id=rt.device_id,
        script_version=int(case.script_version or 0) + 1 if case else 1,
    )

    try:
        res = run_script(case, app, rt.device_id, script_path=stg_case)
    except Exception as e:
        db.update_run(
            run_id,
            status=RunStatus.ERROR,
            error=str(e),
            finished_at=datetime.now(),
        )
        db.update_generation(rt.generation_id, last_dry_run_passed=0)
        append_event(rt.case_id, rt.generation_id, "dry_run_error", error=str(e))
        return {"passed": False, "stage": "runner_error", "error": str(e)}

    passed = res["status"] == "passed"
    db.update_run(
        run_id,
        status=RunStatus.PASSED if passed else RunStatus(res["run_status"]),
        duration_ms=res["duration_ms"],
        error=res["error_message"] or None,
        artifacts_rel_path=res["artifacts_rel_path"],
        finished_at=datetime.now(),
    )
    db.update_generation(
        rt.generation_id,
        last_dry_run_passed=1 if passed else 0,
        last_dry_run_hash=script_hash if passed else "",
    )
    append_event(
        rt.case_id,
        rt.generation_id,
        "dry_run_finished",
        passed=passed,
        run_id=run_id,
        duration_ms=res["duration_ms"],
        error=res["error_message"][:500] if res["error_message"] else "",
    )
    return {
        "passed": passed,
        "run_id": run_id,
        "duration_ms": res["duration_ms"],
        "error": res["error_message"],
        "stdout_tail": res["stdout_tail"],
        "logcat_tail": res["logcat_tail"],
        "screenshots": res["screenshots"],
    }


def tool_commit_staging_script(rt: SessionRuntime) -> dict:
    """验收暂存区最新试跑结果并将脚本原子固化到正式目录。"""
    db = get_mobile_db()
    gen = db.get_generation(rt.generation_id)
    case = db.get_case(rt.case_id)
    if gen is None or case is None:
        raise RuntimeError("生成会话或用例不存在")

    stg_case = rt.staging / "case.py"
    if not stg_case.exists():
        raise ValueError("暂存区缺少 case.py，请先写入脚本并执行 run_server_dry_run")

    err = validate_staging_dir(rt.staging)
    if err:
        raise ValueError(f"静态校验失败，拒绝固化: {err}")

    digest = hashlib.sha256(stg_case.read_bytes()).hexdigest()
    if not gen.last_dry_run_passed or gen.last_dry_run_hash != digest:
        raise ValueError("当前 case.py 尚未在平台主机试跑通过（或试跑后被修改），请先调用 run_server_dry_run")

    # 合并 pages/
    stg_pages = rt.staging / "pages"
    dst_pages = paths.pages_dir(rt.project_id)
    if stg_pages.exists():
        for py in stg_pages.glob("*.py"):
            if py.name == "__init__.py":
                continue
            shutil.copy2(py, dst_pages / py.name)

    # 归档旧版本并写入新版本
    dst_case = paths.case_script_path(rt.project_id, rt.case_id)
    new_version = int(case.script_version or 0) + 1
    if dst_case.exists() and int(case.script_version or 0) > 0:
        hist = paths.case_history_dir(rt.project_id, rt.case_id) / f"case_v{case.script_version}.py"
        shutil.copy2(dst_case, hist)
    shutil.copy2(stg_case, dst_case)

    db.update_case(
        rt.case_id,
        status=CaseStatus.IMPLEMENTED,
        default_app_id=rt.app_id,
        script_rel_path=paths.to_rel(dst_case),
        script_version=new_version,
        script_hash=digest,
        last_error_category=None,
        last_error_message=None,
        last_generated_at=datetime.now(),
    )
    db.update_generation(
        rt.generation_id,
        status=GenerationStatus.SUCCESS,
        finished_at=datetime.now(),
    )
    append_event(rt.case_id, rt.generation_id, "committed", version=new_version)

    _close_driver(rt)
    get_lease_manager().release(rt.device_id, force=True)
    with _RUNTIME_LOCK:
        _RUNTIMES.pop(rt.generation_id, None)

    return {"committed": True, "case_id": rt.case_id, "script_version": new_version}
