# -*- coding: utf-8 -*-
"""流程资产 API：列表 / 详情 / 归档。

流程脚本与用例的关系是「同目录同操作流程复用一套脚本 + 参数注入」，
目录归属按用例库目录 id（kb_folder_id），目录改名不影响流程。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from insight_aitest.modules.ui.backend.automation import flows as flowlib
from insight_aitest.modules.ui.backend.automation.database import UIAutomationDatabase
from insight_aitest.modules.ui.backend.automation.deps import get_automation_db
from insight_aitest.modules.ui.backend.automation.models import UiFlowStatus

router = APIRouter(prefix="/automation/flows", tags=["ui-automation"])


@router.get("")
def list_flows(
    project_id: int = Query(...),
    folder_id: int | None = Query(None),
    status: str | None = Query(None),
    db: UIAutomationDatabase = Depends(get_automation_db),
) -> dict:
    flows = db.list_flows(project_id, folder_id=folder_id, status=status)
    counts = db.flow_case_counts(project_id)
    return {
        "items": [flowlib.flow_out(f, counts.get(f.id, 0)) for f in flows],
        "total": len(flows),
    }


@router.get("/{flow_id}")
def get_flow(flow_id: int, db: UIAutomationDatabase = Depends(get_automation_db)) -> dict:
    flow = db.get_flow(flow_id)
    if flow is None:
        raise HTTPException(404, "流程不存在")
    cases, _total = db.list_cases(
        project_id=int(flow.project_id), flow_id=int(flow.id), page_size=200
    )
    data = flowlib.flow_out(flow, len(cases), True)
    data["cases"] = [
        {
            "id": c.id,
            "title": c.title,
            "status": c.status,
            "script_version": c.script_version,
            "flow_version": c.flow_version,
            "flow_outdated": bool(
                c.flow_version and int(c.flow_version) < int(flow.version or 1)
            ),
        }
        for c in cases
    ]
    return data


@router.post("/{flow_id}/archive")
def archive_flow(
    flow_id: int, db: UIAutomationDatabase = Depends(get_automation_db)
) -> dict:
    """归档流程：不再参与自动复用匹配，已生成脚本的用例保持可执行。"""
    flow = db.get_flow(flow_id)
    if flow is None:
        raise HTTPException(404, "流程不存在")
    db.update_flow(flow_id, status=UiFlowStatus.ARCHIVED)
    updated = db.get_flow(flow_id)
    counts = db.flow_case_counts(int(flow.project_id))
    return flowlib.flow_out(updated, counts.get(flow_id, 0))
