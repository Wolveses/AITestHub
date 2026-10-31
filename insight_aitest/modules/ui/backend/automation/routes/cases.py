# -*- coding: utf-8 -*-
"""AI 自动化用例资产 API：导入 / 列表 / 详情 / 编辑 / 生成 / 修复 / 执行 / 产物。"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from insight_aitest.modules.ui.backend.automation import concurrency, flows as flowlib, paths
from insight_aitest.modules.ui.backend.automation.database import UIAutomationDatabase
from insight_aitest.modules.ui.backend.automation.deps import get_automation_db
from insight_aitest.modules.ui.backend.automation.generator import ASSET_DIRS, start_job
from insight_aitest.modules.ui.backend.automation.importer import import_cases, list_importable
from insight_aitest.modules.ui.backend.automation.models import (
    CaseStatus,
    GenerationKind,
    Site,
    UiFlowStatus,
)
from insight_aitest.modules.ui.backend.automation.runner import EnvMissingError, finish_run, run_script, start_run
from insight_aitest.modules.ui.backend.persistence.models import RunStatus

router = APIRouter(prefix="/automation/cases", tags=["ui-automation"])


class ImportRequest(BaseModel):
    project_id: int
    document_ids: list[int]
    site_map: dict[int, str] | None = None


class CasePatch(BaseModel):
    title: str | None = None
    precondition: str | None = None
    steps: list[str] | None = None
    expected: str | None = None
    site: str | None = None


class ParamsUpdate(BaseModel):
    values: dict[str, str | int | float | bool | None] = {}


class GenerateRequest(BaseModel):
    """生成参数：可显式指定复用流程，或强制新建流程。"""

    reuse_flow_id: int | None = None
    force_new_flow: bool = False


def _case_out(case, db: UIAutomationDatabase, flow_cache: dict | None = None) -> dict:
    progress = concurrency.get_progress(case.id)
    flow = None
    if case.flow_id:
        flow = flow_cache.get(case.flow_id) if flow_cache is not None else db.get_flow(case.flow_id)
    return {
        "id": case.id,
        "project_id": case.project_id,
        "kb_document_id": case.kb_document_id,
        "source_case_id": case.source_case_id,
        "source_workspace_id": case.source_workspace_id,
        "title": case.title,
        "precondition": case.precondition,
        "steps": list(case.steps or []),
        "expected": case.expected,
        "category_path": case.category_path,
        "kb_folder_id": case.kb_folder_id,
        "site": case.site,
        "flow_id": case.flow_id,
        "flow_version": case.flow_version,
        "flow_title": flow.title if flow is not None else "",
        "flow_status": flow.status if flow is not None else None,
        "params": dict(case.params_json or {}),
        "params_schema": list(case.params_schema_json or []),
        "params_updated_at": case.params_updated_at.isoformat() if case.params_updated_at else None,
        "status": case.status,
        "script_version": case.script_version,
        "has_script": bool(case.script_rel_path),
        "last_error_category": case.last_error_category,
        "last_error_message": case.last_error_message,
        "last_run_id": case.last_run_id,
        "last_generated_at": case.last_generated_at.isoformat() if case.last_generated_at else None,
        "progress": progress,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }


def _get_or_404(case_id: int, db: UIAutomationDatabase):
    case = db.get_case(case_id)
    if case is None:
        raise HTTPException(404, "自动化用例不存在")
    return case


@router.get("")
def list_cases(
    project_id: int | None = None,
    status: str | None = Query(None),
    category_path: str | None = Query(None),
    keyword: str | None = Query(None),
    flow_id: int | None = Query(None),
    page: int = 1,
    page_size: int = 50,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    items, total = db.list_cases(
        project_id=project_id,
        status=status,
        category_path=category_path,
        keyword=keyword,
        flow_id=flow_id,
        page=page,
        page_size=page_size,
    )
    flow_cache = (
        {f.id: f for f in db.list_flows(project_id)} if project_id is not None else None
    )
    return {
        "items": [_case_out(c, db, flow_cache) for c in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/importable")
def get_importable(
    project_id: int = Query(...),
    search: str = "",
    category_path: str = "",
    page: int = 1,
    page_size: int = 200,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    return list_importable(
        project_id,
        db,
        search=search,
        category_path=category_path,
        page=page,
        page_size=page_size,
    )


@router.post("/import")
def do_import(
    body: ImportRequest,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    if not body.document_ids:
        raise HTTPException(400, "请选择要导入的用例")
    return import_cases(body.project_id, body.document_ids, db, body.site_map)


@router.get("/{case_id}")
def get_case(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    return _case_out(_get_or_404(case_id, db), db)


@router.patch("/{case_id}")
def patch_case(
    case_id: int,
    body: CasePatch,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    case = _get_or_404(case_id, db)
    if case.status in (CaseStatus.GENERATING, CaseStatus.FIXING, CaseStatus.RUNNING):
        raise HTTPException(409, "用例正在生成/执行中，请稍后再修改")
    fields = body.model_dump(exclude_none=True)
    if not fields:
        return _case_out(case, db)
    if "site" in fields and fields["site"] != case.site:
        if fields["site"] not in Site.ALL:
            raise HTTPException(400, "端只能是 frontend 或 backend")
        # 脚本按端入口地址生成，已产出脚本后固定端，避免脚本与入口错配
        if case.script_rel_path:
            raise HTTPException(409, "用例已生成脚本，端不可再切换；如需调整请删除用例后重新导入")
    # 用例信息变更后脚本与用例可能不再匹配：回到未实现，保留已有脚本供修复
    fields["status"] = CaseStatus.NOT_IMPLEMENTED
    db.update_case(case_id, **fields)
    return _case_out(db.get_case(case_id), db)


@router.delete("/{case_id}")
def delete_case(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    case = _get_or_404(case_id, db)
    if case.status in (CaseStatus.GENERATING, CaseStatus.FIXING, CaseStatus.RUNNING):
        raise HTTPException(409, "用例正在生成/执行中，无法删除")
    db.delete_case(case_id)
    return {"deleted": case_id}


@router.get("/{case_id}/params")
def get_case_params(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    case = _get_or_404(case_id, db)
    return {
        "flow_id": case.flow_id,
        "flow_version": case.flow_version,
        "values": dict(case.params_json or {}),
        "schema": list(case.params_schema_json or []),
        "updated_at": case.params_updated_at.isoformat() if case.params_updated_at else None,
    }


@router.put("/{case_id}/params")
def put_case_params(
    case_id: int,
    body: ParamsUpdate,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    """保存本用例参数值（不改脚本与流程，只影响下一次执行的注入值）。"""
    case = _get_or_404(case_id, db)
    if case.status in (CaseStatus.GENERATING, CaseStatus.FIXING, CaseStatus.RUNNING):
        raise HTTPException(409, "用例正在生成/执行中，请稍后再修改参数")
    schema = list(case.params_schema_json or [])
    if not schema:
        raise HTTPException(400, "该用例使用独立脚本，没有可编辑的流程参数")
    names = {str(item.get("name")) for item in schema if isinstance(item, dict) and item.get("name")}
    unknown = [key for key in body.values if key not in names]
    if unknown:
        raise HTTPException(400, f"参数不在流程参数结构内：{', '.join(unknown)}")
    db.update_case(
        case_id,
        params_json=dict(body.values),
        params_updated_at=datetime.now(),
    )
    return _case_out(db.get_case(case_id), db)


@router.get("/{case_id}/script")
def get_script(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    case = _get_or_404(case_id, db)
    if not case.script_rel_path:
        return {"content": "", "version": 0, "pages": []}
    p = paths.resolve_rel(case.script_rel_path)
    if not p.exists():
        raise HTTPException(404, "脚本文件不存在（可能未同步到本机）")
    source = p.read_text(encoding="utf-8")
    return {
        "content": source,
        "version": case.script_version,
        "pages": _referenced_pages(int(case.project_id), source),
    }


def _referenced_pages(project_id: int, source: str) -> list[dict]:
    """返回脚本实际 import 的项目资产源码（flows/、pages/、common/，含一层传递依赖）。

    按 import 语句反查，不返回无关文件；页面对象 import 的 common 也会一并带出，
    否则预览只看到页面对象、看不到它依赖的通用能力。
    """
    import ast

    def scan(src: str) -> set[tuple[str, str]]:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return set()
        refs: set[tuple[str, str]] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if parts[0] in ASSET_DIRS:
                    if len(parts) >= 2:
                        refs.add((parts[0], parts[1]))
                elif parts[0] == "flows" and len(parts) >= 3:
                    # flows.f_<folder>.<module>：按目录 + 模块名定位流程脚本
                    refs.add(("flows", f"{parts[1]}/{parts[2]}"))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[0] in ASSET_DIRS and len(parts) >= 2:
                        refs.add((parts[0], parts[1]))
                    elif parts[0] == "flows" and len(parts) >= 3:
                        refs.add(("flows", f"{parts[1]}/{parts[2]}"))
        return refs

    def locate(package: str, stem: str) -> Path | None:
        if package == "flows":
            folder, _, module = stem.partition("/")
            return paths.flows_root(project_id) / folder / f"{module}.py"
        root = paths.common_dir(project_id) if package == "common" else paths.pages_dir(project_id)
        return root / f"{stem}.py"

    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    queue = [source]
    while queue:
        src = queue.pop(0)
        for package, stem in sorted(scan(src)):
            if (package, stem) in seen or stem in ("", "__init__"):
                continue
            seen.add((package, stem))
            f = locate(package, stem)
            if f is None or not f.exists():
                continue
            content = f.read_text(encoding="utf-8")
            label = f"{stem}.py" if package == "flows" else f.name
            rel = f"flows/{stem}.py" if package == "flows" else f"{package}/{f.name}"
            out.append({"name": label, "path": rel, "content": content})
            queue.append(content)
    return sorted(out, key=lambda x: x["path"])


def _start_generate(
    case_id: int,
    kind: str,
    db: UIAutomationDatabase,
    reuse_flow_id: int | None = None,
    force_new_flow: bool = False,
) -> dict:
    case = _get_or_404(case_id, db)
    if kind == GenerationKind.FIX and not case.script_rel_path:
        raise HTTPException(400, "该用例还没有脚本，无法自动修复，请先生成脚本")
    project_id = int(case.project_id)
    if reuse_flow_id is not None:
        flow = db.get_flow(reuse_flow_id)
        if flow is None or int(flow.project_id) != project_id:
            raise HTTPException(400, "指定的复用流程不存在或不属于该项目")
        if flow.status != UiFlowStatus.ACTIVE:
            raise HTTPException(400, "指定的复用流程已归档")
    if not concurrency.acquire(project_id):
        raise HTTPException(409, "该项目已有任务在执行（生成/修复/运行），请稍后重试")
    concurrency.set_progress(case_id, "排队", "任务已提交")
    try:
        start_job(
            case_id,
            kind,
            reuse_flow_id=reuse_flow_id,
            force_new_flow=force_new_flow,
        )
    except Exception:
        concurrency.release(project_id)
        raise
    return {"accepted": True, "case_id": case_id, "kind": kind}


@router.post("/{case_id}/generate")
def generate(
    case_id: int,
    body: GenerateRequest | None = None,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    reuse_flow_id = body.reuse_flow_id if body else None
    force_new_flow = bool(body.force_new_flow) if body else False
    return _start_generate(
        case_id,
        GenerationKind.GENERATE,
        db,
        reuse_flow_id=reuse_flow_id,
        force_new_flow=force_new_flow,
    )


@router.post("/{case_id}/fix")
def fix(case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)) -> dict:
    return _start_generate(case_id, GenerationKind.FIX, db)


@router.post("/{case_id}/match-flow")
def match_flow(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    """纯规则打分：同目录（kb_folder_id）下可复用的流程候选（不调用模型）。"""
    case = _get_or_404(case_id, db)
    candidates = flowlib.match_candidates(db, case)
    counts = db.flow_case_counts(int(case.project_id))
    items = [
        {
            "flow": flowlib.flow_out(flow, counts.get(flow.id, 0)),
            "score": score,
            "detail": detail,
            "auto_reusable": score >= flowlib.AUTO_THRESHOLD,
        }
        for flow, score, detail in candidates[:5]
    ]
    recommended = next(
        (
            item["flow"]
            for item in items
            if item["score"] >= flowlib.GRAY_LOW
        ),
        None,
    )
    return {"recommended": recommended, "candidates": items}


def _run_worker(case_id: int) -> None:
    db = get_automation_db()
    case = db.get_case(case_id)
    if case is None:
        return
    project_id = int(case.project_id)
    prev_status = case.status
    run_id = None
    try:
        db.update_case(case_id, status=CaseStatus.RUNNING)
        concurrency.set_progress(case_id, "执行中", "运行固化脚本")
        env = db.default_env(project_id)
        # 先落 RUNNING 记录：执行记录里立刻能看到「执行中」，并可轮询 stdout.log 看实时过程
        run_id, run_dir = start_run(case, env)
        # 执行期允许一次自动重试，吸收 UI 抖动（生成期首跑不重试，避免掩盖脚本缺陷）
        result = run_script(case, env, run_dir=run_dir, retries=1)
        finish_run(run_id, case, result)
        concurrency.set_progress(
            case_id,
            "完成" if result.get("run_status") == "passed" else "失败",
            result.get("error_message") or "执行完成",
        )
    except EnvMissingError as e:
        if run_id:
            db.update_script_run(
                run_id, status=RunStatus.ERROR, error=str(e), finished_at=datetime.now()
            )
        db.update_case(case_id, status=prev_status)
        concurrency.set_progress(case_id, "失败", str(e))
    except Exception as e:  # 执行器异常不能把用例卡在 running
        if run_id:
            db.update_script_run(
                run_id,
                status=RunStatus.ERROR,
                error=f"执行器异常：{type(e).__name__}: {e}",
                finished_at=datetime.now(),
            )
        db.update_case(case_id, status=prev_status)
        concurrency.set_progress(case_id, "失败", f"执行器异常：{type(e).__name__}: {e}")
    finally:
        current = db.get_case(case_id)
        if current is not None and current.status == CaseStatus.RUNNING:
            db.update_case(
                case_id,
                status=CaseStatus.IMPLEMENTED if current.script_version >= 1 else CaseStatus.NOT_IMPLEMENTED,
            )
        concurrency.release(project_id)


@router.post("/{case_id}/run")
def run_case(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    case = _get_or_404(case_id, db)
    if not case.script_rel_path:
        raise HTTPException(400, "请先生成并固化脚本")
    project_id = int(case.project_id)
    if not concurrency.acquire(project_id):
        raise HTTPException(409, "该项目已有任务在执行（生成/修复/运行），请稍后重试")
    threading.Thread(
        target=_run_worker, args=(case_id,), daemon=True, name=f"ui-run-{case_id}"
    ).start()
    return {"accepted": True, "case_id": case_id}


@router.get("/{case_id}/runs")
def list_runs(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> list[dict]:
    _get_or_404(case_id, db)
    return db.list_script_runs(case_id)


@router.get("/{case_id}/runs/{run_id}/artifact/{filename}")
def get_artifact(
    case_id: int,
    run_id: int,
    filename: str,
    db: UIAutomationDatabase = Depends(get_automation_db),
):
    _get_or_404(case_id, db)
    run = db.get_script_run(run_id)
    if run is None or not run["artifacts_rel_path"]:
        raise HTTPException(404, "执行产物不存在")
    base = paths.resolve_rel(run["artifacts_rel_path"]).resolve()
    target = (base / filename).resolve()
    if not target.is_relative_to(base) or not target.exists() or not target.is_file():
        raise HTTPException(404, "产物文件不存在")
    return FileResponse(target)


@router.get("/{case_id}/runs/{run_id}/log")
def get_run_log(
    case_id: int,
    run_id: int,
    tail: int = Query(200_000, ge=1_000, le=2_000_000),
    db: UIAutomationDatabase = Depends(get_automation_db),
):
    """执行过程日志（pytest 实时 stdout）：运行中轮询即可看到过程，结束后保留完整内容。"""
    _get_or_404(case_id, db)
    run = db.get_script_run(run_id)
    if run is None or not run["artifacts_rel_path"]:
        raise HTTPException(404, "执行日志不存在")
    log = paths.resolve_rel(run["artifacts_rel_path"]) / "stdout.log"
    if not log.exists():
        return Response("（等待执行输出…）", media_type="text/plain; charset=utf-8")
    text = log.read_text(encoding="utf-8", errors="replace")
    if len(text) > tail:
        text = f"…（已截断，仅显示最后 {tail} 字符）…\n" + text[-tail:]
    return Response(text, media_type="text/plain; charset=utf-8")


def _format_generation_log(text: str, tail: int) -> str:
    """把生成过程的 jsonl 事件转成可读行，便于在界面上回看探索过程。"""
    lines: list[str] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            lines.append(raw[:600])
            continue
        kind = str(ev.get("type") or "")
        if kind == "assistant":
            step = f"[思考] {ev.get('thought') or ''}"
            if ev.get("tool"):
                step += f" → {ev.get('tool')}"
            lines.append(step)
        elif kind == "tool":
            mark = "（失败）" if ev.get("is_error") else ""
            obs = str(ev.get("observation") or "").replace("\n", " ")
            lines.append(f"[工具] {ev.get('tool') or ''}{mark}：{obs[:400]}")
        elif kind == "auto_open":
            lines.append(f"[进入用例页面] {ev.get('url') or ''}")
        elif kind == "controls":
            items = ev.get("items") or []
            names = "、".join(str(i.get("label") or "") for i in items)
            lines.append(f"[控件清单] 共 {len(items)} 项：{names}")
        elif kind in ("params_incomplete", "flow_invalid", "validate"):
            lines.append(f"[校验] {kind}：{str(ev.get('message') or ev)[:500]}")
        elif kind in ("bad_ref", "unknown_tool", "bad_json", "llm_error"):
            lines.append(f"[异常] {kind}：{str(ev)[:500]}")
        else:
            lines.append(f"[{kind}] {str(ev)[:400]}")
    body = "\n".join(lines)
    if len(body) > tail:
        body = f"…（已截断，仅显示最后 {tail} 字符）…\n" + body[-tail:]
    return body


@router.get("/{case_id}/generations/{generation_id}/log")
def get_generation_log(
    case_id: int,
    generation_id: int,
    tail: int = Query(200_000, ge=1_000, le=2_000_000),
    db: UIAutomationDatabase = Depends(get_automation_db),
):
    """生成过程日志（探索/工具调用/校验事件）：生成中轮询可看到实时进展。"""
    _get_or_404(case_id, db)
    gen = next((g for g in db.list_generations(case_id) if g.id == generation_id), None)
    if gen is None or not gen.log_rel_path:
        raise HTTPException(404, "生成日志不存在")
    log = paths.resolve_rel(gen.log_rel_path)
    if not log.exists():
        return Response("（等待生成输出…）", media_type="text/plain; charset=utf-8")
    return Response(
        _format_generation_log(log.read_text(encoding="utf-8", errors="replace"), tail),
        media_type="text/plain; charset=utf-8",
    )


@router.get("/{case_id}/generations")
def list_generations(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> list[dict]:
    _get_or_404(case_id, db)
    return [
        {
            "id": g.id,
            "kind": g.kind,
            "attempt": g.attempt,
            "status": g.status,
            "error_category": g.error_category,
            "error_message": g.error_message,
            "tool_calls": g.tool_calls,
            "model": g.model,
            "log_rel_path": g.log_rel_path,
            "started_at": g.started_at.isoformat() if g.started_at else None,
            "finished_at": g.finished_at.isoformat() if g.finished_at else None,
        }
        for g in db.list_generations(case_id)
    ]


@router.get("/{case_id}/progress")
def get_progress(
    case_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    case = _get_or_404(case_id, db)
    return {"status": case.status, "progress": concurrency.get_progress(case_id)}


# 兼容：前端可能直接拼产物绝对名
@router.get("/{case_id}/runs/{run_id}/result")
def get_result(
    case_id: int,
    run_id: int,
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    _get_or_404(case_id, db)
    run = db.get_script_run(run_id)
    if run is None or not run["artifacts_rel_path"]:
        raise HTTPException(404, "执行产物不存在")
    p = paths.resolve_rel(run["artifacts_rel_path"]) / "result.json"
    if not p.exists():
        return {}
    import json

    return json.loads(p.read_text(encoding="utf-8"))
