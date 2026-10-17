# -*- coding: utf-8 -*-
"""知识库文件夹（目录）路由。

提供目录层级树获取、新建文件夹、重命名/移动文件夹、删除文件夹。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from insight_aitest.modules.ai.backend.deps import get_kb_db
from insight_aitest.platform.services.kb.database import KBDatabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/folders", tags=["kb-folders"])


class FolderNode(BaseModel):
    id: int
    name: str
    parent_id: int | None = None
    project_id: int | None = None
    children: list[FolderNode] = []
    doc_count: int = 0


class FolderCreateIn(BaseModel):
    name: str
    parent_id: int | None = None
    project_id: int | None = None


class FolderUpdateIn(BaseModel):
    name: str | None = None
    parent_id: int | None = -1  # -1 表示保持不变


@router.get("", response_model=list[FolderNode])
async def list_folders_tree(
    project_id: int | None = None,
    db: KBDatabase = Depends(get_kb_db),
) -> list[FolderNode]:
    """获取指定项目（或全局）的文件夹目录树。"""
    folders = db.list_folders(project_id=project_id)
    documents = db.list_documents(project_id=project_id)

    # 统计每个文件夹直接持有的文档数
    counts: dict[int, int] = {}
    for d in documents:
        if d.folder_id:
            counts[d.folder_id] = counts.get(d.folder_id, 0) + 1

    # 构造节点字典
    node_map: dict[int, FolderNode] = {}
    for f in folders:
        node_map[f.id] = FolderNode(
            id=f.id,
            name=f.name,
            parent_id=f.parent_id,
            project_id=f.project_id,
            children=[],
            doc_count=counts.get(f.id, 0),
        )

    # 组装树结构
    roots: list[FolderNode] = []
    for f in folders:
        node = node_map[f.id]
        if f.parent_id and f.parent_id in node_map:
            node_map[f.parent_id].children.append(node)
        else:
            roots.append(node)

    return roots


@router.post("", response_model=FolderNode)
async def create_folder(
    body: FolderCreateIn,
    db: KBDatabase = Depends(get_kb_db),
) -> FolderNode:
    """创建新文件夹。"""
    if not body.name.strip():
        raise HTTPException(400, "文件夹名称不能为空")
    f = db.create_folder(
        name=body.name,
        parent_id=body.parent_id,
        project_id=body.project_id,
    )
    return FolderNode(
        id=f.id,
        name=f.name,
        parent_id=f.parent_id,
        project_id=f.project_id,
        children=[],
        doc_count=0,
    )


@router.put("/{folder_id}", response_model=dict[str, Any])
async def update_folder(
    folder_id: int,
    body: FolderUpdateIn,
    db: KBDatabase = Depends(get_kb_db),
) -> dict[str, Any]:
    """重命名或移动文件夹。"""
    ok = db.update_folder(folder_id, name=body.name, parent_id=body.parent_id)
    if not ok:
        raise HTTPException(404, "文件夹不存在")
    return {"ok": True}


@router.delete("/{folder_id}", response_model=dict[str, Any])
async def delete_folder(
    folder_id: int,
    db: KBDatabase = Depends(get_kb_db),
) -> dict[str, Any]:
    """删除文件夹（内部文档自动回归根目录/未分类）。"""
    ok = db.delete_folder(folder_id)
    if not ok:
        raise HTTPException(404, "文件夹不存在")
    return {"ok": True}

