# -*- coding: utf-8 -*-
"""UI 自动化任务执行调度器。

支持手动立即执行与定时 Cron 触发：
1. 依序执行任务内已关联的已实现用例（复用底层 pytest + Playwright runner）；
2. 收集各用例的执行状态、耗时、产物与错误信息；
3. 聚合生成任务测试报告与历史记录（UiTaskRun / summary_json）。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

from insight_aitest.modules.ui.backend.automation.deps import get_automation_db
from insight_aitest.modules.ui.backend.automation.models import CaseStatus
from insight_aitest.modules.ui.backend.automation.runner import (
    EnvMissingError,
    finish_run,
    run_script,
    start_run,
)
from insight_aitest.modules.ui.backend.automation.task_models import (
    TaskStatus,
    TriggerType,
    UiTaskRun,
)

logger = logging.getLogger(__name__)

# 正在运行的任务集合（防止单任务并发重复执行）
_RUNNING_TASKS: set[int] = set()
_LOCK = threading.Lock()


def is_task_running(task_id: int) -> bool:
    with _LOCK:
        return task_id in _RUNNING_TASKS


def execute_task(task_id: int, trigger_type: str = TriggerType.MANUAL) -> UiTaskRun:
    """触发任务执行（异步启动后台 worker 跑完全部用例）。"""
    db = get_automation_db()
    task = db.get_task(task_id)
    if task is None:
        raise ValueError(f"任务不存在: {task_id}")

    with _LOCK:
        if task_id in _RUNNING_TASKS:
            raise RuntimeError(f"任务 {task_id} 当前已在执行中，请勿重复触发")
        _RUNNING_TASKS.add(task_id)

    try:
        case_pairs = db.get_task_cases(task_id)
        total_cases = len(case_pairs)

        run = db.create_task_run(
            task_id=task.id,
            project_id=task.project_id,
            env_id=task.env_id,
            trigger_type=trigger_type,
            total_cases=total_cases,
        )

        db.update_task(
            task_id,
            last_status=TaskStatus.RUNNING,
            last_run_at=datetime.now(),
            last_run_id=run.id,
        )

        worker = threading.Thread(
            target=_task_worker,
            args=(task_id, run.id),
            daemon=True,
            name=f"ui-task-run-{task_id}-{run.id}",
        )
        worker.start()
        return run
    except Exception:
        with _LOCK:
            _RUNNING_TASKS.discard(task_id)
        raise


def _task_worker(task_id: int, run_id: int) -> None:
    """任务执行后台工作线程。"""
    db = get_automation_db()
    task = db.get_task(task_id)
    run = db.get_task_run(run_id)
    if task is None or run is None:
        with _LOCK:
            _RUNNING_TASKS.discard(task_id)
        return

    started_time = time.time()
    results: list[dict] = []
    passed_count = 0
    failed_count = 0

    try:
        env = db.get_env(task.env_id) or db.default_env(task.project_id)
        case_pairs = db.get_task_cases(task_id)

        if not case_pairs:
            # 任务中无用例
            duration_ms = int((time.time() - started_time) * 1000)
            db.update_task_run(
                run_id,
                status=TaskStatus.PASSED,
                total_cases=0,
                passed_cases=0,
                failed_cases=0,
                duration_ms=duration_ms,
                summary_json=json.dumps([], ensure_ascii=False),
                ended_at=datetime.now(),
            )
            db.update_task(
                task_id,
                last_status=TaskStatus.PASSED,
                last_run_at=datetime.now(),
                last_run_id=run_id,
            )
            return

        for task_case, case in case_pairs:
            case_id = int(case.id)
            # 如果用例未实现自动化脚本，标记为失败并跳过
            if case.status != CaseStatus.IMPLEMENTED:
                failed_count += 1
                results.append(
                    {
                        "case_id": case_id,
                        "title": case.title,
                        "site": case.site,
                        "category": case.category_path or "未分类",
                        "status": "failed",
                        "duration_ms": 0,
                        "error": "用例尚未生成固化脚本（未实现）",
                        "run_id": None,
                        "artifacts_rel_path": "",
                    }
                )
                continue

            # 执行已实现的用例脚本
            sub_run_id = None
            case_started = time.time()
            prev_status = case.status
            try:
                db.update_case(case_id, status=CaseStatus.RUNNING)
                sub_run_id, run_dir = start_run(case, env)
                script_res = run_script(case, env, run_dir=run_dir, retries=1)
                finish_run(sub_run_id, case, script_res)

                run_status = script_res.get("run_status") or "failed"
                err_msg = script_res.get("error_message") or ""
                artifacts_path = script_res.get("artifacts_rel_path") or ""
                case_duration = int((time.time() - case_started) * 1000)

                if run_status == "passed":
                    passed_count += 1
                else:
                    failed_count += 1

                results.append(
                    {
                        "case_id": case_id,
                        "title": case.title,
                        "site": case.site,
                        "category": case.category_path or "未分类",
                        "status": run_status,
                        "duration_ms": case_duration,
                        "error": err_msg,
                        "run_id": sub_run_id,
                        "artifacts_rel_path": artifacts_path,
                    }
                )
            except EnvMissingError as e:
                failed_count += 1
                results.append(
                    {
                        "case_id": case_id,
                        "title": case.title,
                        "site": case.site,
                        "category": case.category_path or "未分类",
                        "status": "failed",
                        "duration_ms": int((time.time() - case_started) * 1000),
                        "error": str(e),
                        "run_id": sub_run_id,
                        "artifacts_rel_path": "",
                    }
                )
            except Exception as e:
                failed_count += 1
                results.append(
                    {
                        "case_id": case_id,
                        "title": case.title,
                        "site": case.site,
                        "category": case.category_path or "未分类",
                        "status": "failed",
                        "duration_ms": int((time.time() - case_started) * 1000),
                        "error": f"用例执行异常：{e}",
                        "run_id": sub_run_id,
                        "artifacts_rel_path": "",
                    }
                )
            finally:
                cur = db.get_case(case_id)
                if cur is not None and cur.status == CaseStatus.RUNNING:
                    db.update_case(case_id, status=CaseStatus.IMPLEMENTED)

        # 任务汇总
        total_duration_ms = int((time.time() - started_time) * 1000)
        overall_status = TaskStatus.PASSED if failed_count == 0 else TaskStatus.FAILED
        ended_at = datetime.now()

        db.update_task_run(
            run_id,
            status=overall_status,
            total_cases=len(results),
            passed_cases=passed_count,
            failed_cases=failed_count,
            duration_ms=total_duration_ms,
            summary_json=json.dumps(results, ensure_ascii=False),
            ended_at=ended_at,
        )

        db.update_task(
            task_id,
            last_status=overall_status,
            last_run_at=ended_at,
            last_run_id=run_id,
        )
    except Exception as e:
        logger.exception(f"任务 {task_id} 执行异常: {e}")
        ended_at = datetime.now()
        total_duration_ms = int((time.time() - started_time) * 1000)
        db.update_task_run(
            run_id,
            status=TaskStatus.ERROR,
            error_message=str(e),
            duration_ms=total_duration_ms,
            summary_json=json.dumps(results, ensure_ascii=False),
            ended_at=ended_at,
        )
        db.update_task(
            task_id,
            last_status=TaskStatus.ERROR,
            last_run_at=ended_at,
            last_run_id=run_id,
        )
    finally:
        with _LOCK:
            _RUNNING_TASKS.discard(task_id)
