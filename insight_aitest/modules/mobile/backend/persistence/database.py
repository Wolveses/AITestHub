# -*- coding: utf-8 -*-
"""手机 App 自动化数据库（~/.insight_eye/mobile.db）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from insight_aitest.modules.mobile.backend.persistence.models import (
    CaseStatus,
    GenerationStatus,
    MobileApp,
    MobileCase,
    MobileGeneration,
    MobileLesson,
    MobileRun,
    RunStatus,
)
from insight_aitest.platform.persistence import Base, get_engine, session_scope


class MobileDatabase:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Base.metadata.create_all(
            get_engine(db_path),
            tables=[
                MobileApp.__table__,
                MobileCase.__table__,
                MobileGeneration.__table__,
                MobileRun.__table__,
                MobileLesson.__table__,
            ],
        )

    # ===== App 环境配置 =====

    def get_app(self, app_id: int) -> MobileApp | None:
        with session_scope(self.db_path) as s:
            return s.get(MobileApp, app_id)

    def get_default_app(self, project_id: int, platform: str | None = None) -> MobileApp | None:
        stmt = select(MobileApp).where(MobileApp.project_id == project_id)
        if platform:
            stmt = stmt.where(MobileApp.platform == platform)
        stmt = stmt.order_by(MobileApp.is_default.desc(), MobileApp.id.desc())
        with session_scope(self.db_path) as s:
            return s.scalar(stmt)

    def list_apps(self, project_id: int | None = None) -> list[MobileApp]:
        stmt = select(MobileApp)
        if project_id is not None:
            stmt = stmt.where(MobileApp.project_id == project_id)
        stmt = stmt.order_by(MobileApp.is_default.desc(), MobileApp.id.desc())
        with session_scope(self.db_path) as s:
            return list(s.scalars(stmt))

    def create_app(self, **fields) -> int:
        app = MobileApp(**fields)
        with session_scope(self.db_path) as s:
            if app.is_default:
                for other in s.scalars(
                    select(MobileApp).where(MobileApp.project_id == app.project_id)
                ):
                    other.is_default = 0
            s.add(app)
            s.flush()
            return int(app.id)

    def update_app(self, app_id: int, **fields) -> MobileApp | None:
        with session_scope(self.db_path) as s:
            app = s.get(MobileApp, app_id)
            if app is None:
                return None
            if fields.get("is_default"):
                for other in s.scalars(
                    select(MobileApp).where(
                        MobileApp.project_id == app.project_id,
                        MobileApp.id != app_id,
                    )
                ):
                    other.is_default = 0
            for k, v in fields.items():
                if hasattr(app, k):
                    setattr(app, k, v)
            app.updated_at = datetime.now()
            return app

    def delete_app(self, app_id: int) -> bool:
        with session_scope(self.db_path) as s:
            app = s.get(MobileApp, app_id)
            if app is None:
                return False
            s.delete(app)
            return True

    # ===== 用例资产 =====

    def get_case(self, case_id: int) -> MobileCase | None:
        with session_scope(self.db_path) as s:
            return s.get(MobileCase, case_id)

    def get_case_by_doc(self, project_id: int, doc_id: int) -> MobileCase | None:
        with session_scope(self.db_path) as s:
            return s.scalar(
                select(MobileCase).where(
                    MobileCase.project_id == project_id,
                    MobileCase.kb_document_id == doc_id,
                )
            )

    def list_cases(
        self,
        project_id: int | None = None,
        status: str | None = None,
        platform: str | None = None,
        category_path: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[MobileCase], int]:
        stmt = select(MobileCase)
        count_stmt = select(func.count(MobileCase.id))
        conds = []
        if project_id is not None:
            conds.append(MobileCase.project_id == project_id)
        if status:
            conds.append(MobileCase.status == status)
        if platform:
            conds.append(MobileCase.platform == platform)
        if category_path:
            conds.append(MobileCase.category_path.like(f"{category_path}%"))
        if keyword:
            conds.append(MobileCase.title.ilike(f"%{keyword}%"))
        for c in conds:
            stmt = stmt.where(c)
            count_stmt = count_stmt.where(c)
        p = max(1, page)
        ps = max(1, min(page_size, 200))
        stmt = stmt.order_by(MobileCase.id.desc()).offset((p - 1) * ps).limit(ps)
        with session_scope(self.db_path) as s:
            total = s.scalar(count_stmt) or 0
            items = list(s.scalars(stmt))
        return items, int(total)

    def imported_doc_ids(self, project_id: int) -> set[int]:
        with session_scope(self.db_path) as s:
            rows = s.execute(
                select(MobileCase.kb_document_id).where(MobileCase.project_id == project_id)
            ).scalars()
            return set(rows)

    def create_case(self, **fields) -> int:
        case = MobileCase(**fields)
        with session_scope(self.db_path) as s:
            s.add(case)
            s.flush()
            return int(case.id)

    def update_case(self, case_id: int, **fields) -> MobileCase | None:
        with session_scope(self.db_path) as s:
            case = s.get(MobileCase, case_id)
            if case is None:
                return None
            for k, v in fields.items():
                if hasattr(case, k):
                    setattr(case, k, v)
            case.updated_at = datetime.now()
            return case

    def delete_case(self, case_id: int) -> bool:
        with session_scope(self.db_path) as s:
            case = s.get(MobileCase, case_id)
            if case is None:
                return False
            s.delete(case)
            return True

    # ===== 生成会话 =====

    def create_generation(self, **fields) -> int:
        gen = MobileGeneration(**fields)
        with session_scope(self.db_path) as s:
            s.add(gen)
            s.flush()
            return int(gen.id)

    def get_generation(self, gen_id: int) -> MobileGeneration | None:
        with session_scope(self.db_path) as s:
            return s.get(MobileGeneration, gen_id)

    def get_generation_by_token_hash(self, token_hash: str) -> MobileGeneration | None:
        with session_scope(self.db_path) as s:
            return s.scalar(
                select(MobileGeneration).where(
                    MobileGeneration.session_token_hash == token_hash,
                    MobileGeneration.status == GenerationStatus.RUNNING,
                )
            )

    def list_cases_with_running_generation(self, project_id: int) -> list[MobileCase]:
        running_case_ids = select(MobileGeneration.mobile_case_id).where(
            MobileGeneration.status == GenerationStatus.RUNNING
        )
        stmt = (
            select(MobileCase)
            .where(
                MobileCase.project_id == project_id,
                (
                    MobileCase.status.in_((CaseStatus.GENERATING, CaseStatus.FIXING))
                    | MobileCase.id.in_(running_case_ids)
                ),
            )
            .order_by(MobileCase.id.desc())
        )
        with session_scope(self.db_path) as s:
            return list(s.scalars(stmt))

    def list_generations(self, case_id: int, limit: int = 20) -> list[MobileGeneration]:
        with session_scope(self.db_path) as s:
            return list(
                s.scalars(
                    select(MobileGeneration)
                    .where(MobileGeneration.mobile_case_id == case_id)
                    .order_by(MobileGeneration.id.desc())
                    .limit(limit)
                )
            )

    def update_generation(self, gen_id: int, **fields) -> MobileGeneration | None:
        with session_scope(self.db_path) as s:
            gen = s.get(MobileGeneration, gen_id)
            if gen is None:
                return None
            for k, v in fields.items():
                if hasattr(gen, k):
                    setattr(gen, k, v)
            return gen

    def count_generations(self, case_id: int) -> int:
        with session_scope(self.db_path) as s:
            return int(
                s.scalar(
                    select(func.count(MobileGeneration.id)).where(
                        MobileGeneration.mobile_case_id == case_id
                    )
                )
                or 0
            )

    # ===== 执行记录 =====

    def create_run(self, **fields) -> int:
        run = MobileRun(**fields)
        with session_scope(self.db_path) as s:
            s.add(run)
            s.flush()
            return int(run.id)

    def get_run(self, run_id: int) -> MobileRun | None:
        with session_scope(self.db_path) as s:
            return s.get(MobileRun, run_id)

    def update_run(self, run_id: int, **fields) -> MobileRun | None:
        with session_scope(self.db_path) as s:
            run = s.get(MobileRun, run_id)
            if run is None:
                return None
            for k, v in fields.items():
                if hasattr(run, k):
                    setattr(run, k, v)
            return run

    def list_runs(
        self, case_id: int | None = None, project_id: int | None = None, limit: int = 50
    ) -> list[dict]:
        stmt = select(MobileRun)
        if case_id is not None:
            stmt = stmt.where(MobileRun.case_id == case_id)
        if project_id is not None:
            stmt = stmt.where(MobileRun.project_id == project_id)
        stmt = stmt.order_by(MobileRun.id.desc()).limit(limit)
        with session_scope(self.db_path) as s:
            rows = list(s.scalars(stmt))
        return [
            {
                "id": r.id,
                "case_id": r.case_id,
                "project_id": r.project_id,
                "app_id": r.app_id,
                "case_title": r.case_title,
                "status": r.status.value if isinstance(r.status, RunStatus) else str(r.status),
                "runner": r.runner,
                "device_id": r.device_id,
                "device_model": r.device_model,
                "os_version": r.os_version,
                "script_version": r.script_version,
                "duration_ms": r.duration_ms,
                "error": r.error,
                "artifacts_rel_path": r.artifacts_rel_path,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ]

    # ===== 错题库 =====

    def list_lessons(self, project_id: int, limit: int = 100) -> list[MobileLesson]:
        with session_scope(self.db_path) as s:
            return list(
                s.scalars(
                    select(MobileLesson)
                    .where(MobileLesson.project_id == project_id)
                    .order_by(MobileLesson.hits.desc(), MobileLesson.updated_at.desc())
                    .limit(limit)
                )
            )

    def upsert_lesson(
        self, project_id: int, fingerprint: str, category: str, title: str, content: str
    ) -> None:
        with session_scope(self.db_path) as s:
            existing = s.scalar(
                select(MobileLesson).where(
                    MobileLesson.project_id == project_id,
                    MobileLesson.fingerprint == fingerprint,
                )
            )
            if existing is not None:
                existing.hits += 1
                existing.updated_at = datetime.now()
                return
            s.add(
                MobileLesson(
                    project_id=project_id,
                    fingerprint=fingerprint,
                    category=category,
                    title=title,
                    content=content,
                    hits=1,
                )
            )
