# -*- coding: utf-8 -*-
"""接口资产库（复用 api.db，表 api_assets）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from insight_aitest.platform.persistence import Base, get_engine, session_scope
from insight_aitest.modules.api.backend.persistence.asset_models import ApiAsset


class AssetDatabase:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Base.metadata.create_all(get_engine(db_path), tables=[ApiAsset.__table__])

    def upsert_many(self, items: list[dict]) -> dict:
        """按 (project_id, fingerprint) 幂等写入：命中则累加次数并刷新样本。"""
        imported = 0
        updated = 0
        now = datetime.now()
        with session_scope(self.db_path) as s:
            for item in items:
                fingerprint = item.get("fingerprint") or ""
                project_id = item.get("project_id")
                stmt = select(ApiAsset).where(ApiAsset.fingerprint == fingerprint)
                stmt = stmt.where(
                    ApiAsset.project_id.is_(None)
                    if project_id is None
                    else ApiAsset.project_id == project_id
                )
                asset = s.scalars(stmt).first()
                if asset is None:
                    s.add(
                        ApiAsset(
                            project_id=project_id,
                            title=item.get("title") or "",
                            method=item.get("method") or "GET",
                            path=item.get("path") or "",
                            path_template=item.get("path_template") or "",
                            base_url=item.get("base_url") or "",
                            headers=item.get("headers") or {},
                            body=item.get("body"),
                            response_status=int(item.get("response_status") or 0),
                            response_headers=item.get("response_headers") or {},
                            response_body=item.get("response_body"),
                            response_content_type=item.get("response_content_type") or "",
                            body_truncated=bool(item.get("body_truncated")),
                            fingerprint=fingerprint,
                            times_seen=int(item.get("times_seen") or 1),
                            source=item.get("source") or "ui-capture",
                            source_case_id=item.get("source_case_id"),
                            tags=item.get("tags") or [],
                            first_seen_at=now,
                            last_seen_at=now,
                        )
                    )
                    imported += 1
                else:
                    asset.times_seen = int(asset.times_seen or 0) + int(
                        item.get("times_seen") or 1
                    )
                    asset.last_seen_at = now
                    asset.path = item.get("path") or asset.path
                    asset.path_template = item.get("path_template") or asset.path_template
                    asset.headers = item.get("headers") or asset.headers
                    asset.body = item.get("body")
                    asset.response_status = int(item.get("response_status") or 0)
                    asset.response_headers = item.get("response_headers") or {}
                    asset.response_body = item.get("response_body")
                    asset.response_content_type = item.get("response_content_type") or ""
                    asset.body_truncated = bool(item.get("body_truncated"))
                    updated += 1
        return {"imported": imported, "updated": updated}

    def list_assets(
        self,
        *,
        project_id: int | None = None,
        method: str = "",
        keyword: str = "",
        hide_noise: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ApiAsset], int]:
        stmt = select(ApiAsset)
        if project_id is not None:
            stmt = stmt.where(ApiAsset.project_id == project_id)
        if method:
            stmt = stmt.where(ApiAsset.method == method.upper())
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                (ApiAsset.title.like(like))
                | (ApiAsset.path_template.like(like))
                | (ApiAsset.path.like(like))
            )
        if hide_noise:
            stmt = stmt.where(ApiAsset.is_noise.is_(False))
        total = 0
        with session_scope(self.db_path) as s:
            total = int(s.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
            stmt = stmt.order_by(ApiAsset.last_seen_at.desc(), ApiAsset.id.desc())
            stmt = stmt.offset(max(0, (page - 1) * page_size)).limit(page_size)
            items = list(s.scalars(stmt))
        return items, total

    def list_by_fingerprints(
        self, project_id: int | None, fingerprints: list[str]
    ) -> list[ApiAsset]:
        if not fingerprints:
            return []
        stmt = select(ApiAsset).where(ApiAsset.fingerprint.in_(fingerprints))
        stmt = stmt.where(
            ApiAsset.project_id.is_(None)
            if project_id is None
            else ApiAsset.project_id == project_id
        )
        with session_scope(self.db_path) as s:
            return list(s.scalars(stmt))

    def get(self, asset_id: int) -> ApiAsset | None:
        with session_scope(self.db_path) as s:
            asset = s.get(ApiAsset, asset_id)
            if asset is None:
                return None
            # 会话关闭后仍要读取字段：触发加载
            s.refresh(asset)
            return asset

    def get_many(self, ids: list[int]) -> list[ApiAsset]:
        """按传入顺序返回资产（缺失的 id 自动忽略）。"""
        if not ids:
            return []
        unique = list(dict.fromkeys(ids))
        with session_scope(self.db_path) as s:
            rows = list(s.scalars(select(ApiAsset).where(ApiAsset.id.in_(unique)))
            )
            by_id = {row.id: row for row in rows}
            return [by_id[i] for i in unique if i in by_id]

    def update(self, asset_id: int, **fields) -> ApiAsset | None:
        allowed = ("title", "tags", "is_noise", "path_template", "ai_meta", "headers", "body")
        with session_scope(self.db_path) as s:
            asset = s.get(ApiAsset, asset_id)
            if asset is None:
                return None
            for key in allowed:
                if key in fields and fields[key] is not None:
                    setattr(asset, key, fields[key])
            return asset

    def delete_many(self, ids: list[int]) -> int:
        if not ids:
            return 0
        with session_scope(self.db_path) as s:
            rows = list(s.scalars(select(ApiAsset).where(ApiAsset.id.in_(ids))))
            for row in rows:
                s.delete(row)
            return len(rows)

    def delete(self, asset_id: int) -> bool:
        with session_scope(self.db_path) as s:
            asset = s.get(ApiAsset, asset_id)
            if asset is None:
                return False
            s.delete(asset)
            return True
