# -*- coding: utf-8 -*-
"""接口资产模型（UI 生成期抓包沉淀）。

独立于用例库（testcases），存于 api.db；由用户显式「转为 API 用例」后才进入用例库。
request/response 的 body 为任意 JSON（dict/list/str/None），统一用 JSON 列。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column

from insight_aitest.platform.persistence import Base
from insight_aitest.platform.persistence.types import CommaList


class ApiAsset(MappedAsDataclass, Base, kw_only=True):
    """一条接口资产（一个 method + 归一化路径）。"""

    __test__ = False
    __tablename__ = "api_assets"
    __table_args__ = (
        UniqueConstraint("project_id", "fingerprint", name="uq_api_asset_fp"),
        Index("idx_api_assets_project", "project_id"),
        Index("idx_api_assets_method", "method"),
    )

    id: Mapped[int | None] = mapped_column(
        Integer, primary_key=True, autoincrement=True, default=None
    )
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    title: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(Text, default="GET")
    path: Mapped[str] = mapped_column(Text, default="")
    path_template: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(Text, default="")
    headers: Mapped[dict] = mapped_column("headers_json", JSON, default_factory=dict)
    body: Mapped[object | None] = mapped_column("body_json", JSON, nullable=True, default=None)
    response_status: Mapped[int] = mapped_column(Integer, default=0)
    response_headers: Mapped[dict] = mapped_column(
        "response_headers_json", JSON, default_factory=dict
    )
    response_body: Mapped[object | None] = mapped_column(
        "response_body_json", JSON, nullable=True, default=None
    )
    response_content_type: Mapped[str] = mapped_column(Text, default="")
    body_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    fingerprint: Mapped[str] = mapped_column(Text, default="")
    times_seen: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(Text, default="ui-capture")
    source_case_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    tags: Mapped[list[str]] = mapped_column(CommaList, default_factory=list)
    is_noise: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_meta: Mapped[dict | None] = mapped_column("ai_meta_json", JSON, nullable=True, default=None)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default_factory=datetime.now)
