# -*- coding: utf-8 -*-
"""AI 自动化脚本数据库（复用 ui.db）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from insight_aitest.modules.ui.backend.automation.models import (
    UiCase,
    UiEnv,
    UiGeneration,
    UiLesson,
)
from insight_aitest.modules.ui.backend.persistence.models import RunRecord
from insight_aitest.platform.persistence import Base, ensure_schema, get_engine, session_scope


def _ensure_run_script_columns(db_path: str) -> None:
    """给旧 ui_runs 表补脚本链路列（幂等；新库由 create_all 直接建好）。"""
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(ui_runs)")}
        if not cols:
            return
        for name, ddl in (
            ("runner", "TEXT NOT NULL DEFAULT 'midscene'"),
            ("env_id", "INTEGER"),
            ("script_version", "INTEGER"),
            ("artifacts_rel_path", "TEXT NOT NULL DEFAULT ''"),
            ("trace_rel_path", "TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE ui_runs ADD COLUMN {name} {ddl}")
        conn.commit()


def _ensure_ui_cases_site(db_path: str) -> None:
    """给旧 ui_cases 表补 site 列（幂等；存量用例默认前台）。"""
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(ui_cases)")}
        if cols and "site" not in cols:
            conn.execute("ALTER TABLE ui_cases ADD COLUMN site TEXT NOT NULL DEFAULT 'frontend'")
            conn.commit()


def _ensure_ui_cases_params(db_path: str) -> None:
    """给旧 ui_cases 表补参数化列（幂等）。"""
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(ui_cases)")}
        if not cols:
            return
        for name, ddl in (
            ("params_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("params_schema_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("params_updated_at", "DATETIME"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE ui_cases ADD COLUMN {name} {ddl}")
        conn.commit()


def _ensure_generation_metrics(db_path: str) -> None:
    """给旧 ui_generations 表补可观测指标列（幂等）。"""
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(ui_generations)")}
        if not cols:
            return
        for name in ("corpus_chars", "prompt_chars", "completion_chars", "fix_rounds"):
            if name not in cols:
                conn.execute(f"ALTER TABLE ui_generations ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def _drop_flow_assets(db_path: str) -> None:
    """移除流程复用机制留下的表与列（幂等；旧版 SQLite 不支持 DROP COLUMN 时跳过）。"""
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS ui_flows")
        cols = {row[1] for row in conn.execute("PRAGMA table_info(ui_cases)")}
        for name in ("flow_id", "flow_version"):
            if name not in cols:
                continue
            try:
                conn.execute(f"ALTER TABLE ui_cases DROP COLUMN {name}")
            except sqlite3.OperationalError:
                # SQLite < 3.35 不支持 DROP COLUMN：保留空列不影响新模型读写
                pass
        conn.commit()


class UIAutomationDatabase:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Base.metadata.create_all(
            get_engine(db_path),
            tables=[
                UiCase.__table__,
                UiEnv.__table__,
                UiGeneration.__table__,
                UiLesson.__table__,
                RunRecord.__table__,
            ],
        )
        ensure_schema(
            db_path,
            [
                _ensure_run_script_columns,
                _ensure_ui_cases_site,
                _ensure_ui_cases_params,
                _ensure_generation_metrics,
                _drop_flow_assets,
            ],
        )

    # ===== 用例 =====

    def get_case(self, case_id: int) -> UiCase | None:
        with session_scope(self.db_path) as s:
            return s.get(UiCase, case_id)

    def get_case_by_doc(self, project_id: int, doc_id: int) -> UiCase | None:
        with session_scope(self.db_path) as s:
            return s.scalar(
                select(UiCase).where(
                    UiCase.project_id == project_id, UiCase.kb_document_id == doc_id
                )
            )

    def list_cases(
        self,
        project_id: int | None = None,
        status: str | None = None,
        category_path: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[UiCase], int]:
        stmt = select(UiCase)
        count_stmt = select(func.count(UiCase.id))
        conds = []
        if project_id is not None:
            conds.append(UiCase.project_id == project_id)
        if status:
            conds.append(UiCase.status == status)
        if category_path:
            # 目录树选中父级时包含其所有子路径
            conds.append(UiCase.category_path.like(f"{category_path}%"))
        if keyword:
            conds.append(UiCase.title.ilike(f"%{keyword}%"))
        for c in conds:
            stmt = stmt.where(c)
            count_stmt = count_stmt.where(c)
        p = max(1, page)
        ps = max(1, min(page_size, 200))
        stmt = stmt.order_by(UiCase.id.desc()).offset((p - 1) * ps).limit(ps)
        with session_scope(self.db_path) as s:
            total = s.scalar(count_stmt) or 0
            items = list(s.scalars(stmt))
        return items, total

    def imported_doc_ids(self, project_id: int) -> set[int]:
        with session_scope(self.db_path) as s:
            rows = s.execute(
                select(UiCase.kb_document_id).where(UiCase.project_id == project_id)
            ).scalars()
            return set(rows)

    def create_case(self, **fields) -> int:
        case = UiCase(**fields)
        with session_scope(self.db_path) as s:
            s.add(case)
            s.flush()
            return case.id

    def update_case(self, case_id: int, **fields) -> UiCase | None:
        with session_scope(self.db_path) as s:
            case = s.get(UiCase, case_id)
            if case is None:
                return None
            for k, v in fields.items():
                if hasattr(case, k):
                    setattr(case, k, v)
            case.updated_at = datetime.now()
            return case

    def delete_case(self, case_id: int) -> bool:
        with session_scope(self.db_path) as s:
            case = s.get(UiCase, case_id)
            if case is None:
                return False
            s.delete(case)
            return True

    def count_cases(self, project_id: int | None = None) -> int:
        stmt = select(func.count(UiCase.id))
        if project_id is not None:
            stmt = stmt.where(UiCase.project_id == project_id)
        with session_scope(self.db_path) as s:
            return s.scalar(stmt) or 0

    # ===== 环境 =====

    def get_env(self, env_id: int) -> UiEnv | None:
        with session_scope(self.db_path) as s:
            return s.get(UiEnv, env_id)

    def list_envs(self, project_id: int | None = None) -> list[UiEnv]:
        stmt = select(UiEnv)
        if project_id is not None:
            stmt = stmt.where(UiEnv.project_id == project_id)
        stmt = stmt.order_by(UiEnv.is_default.desc(), UiEnv.id.desc())
        with session_scope(self.db_path) as s:
            return list(s.scalars(stmt))

    def default_env(self, project_id: int) -> UiEnv | None:
        with session_scope(self.db_path) as s:
            env = s.scalar(
                select(UiEnv)
                .where(UiEnv.project_id == project_id, UiEnv.is_default == 1)
                .order_by(UiEnv.id.desc())
            )
            if env is not None:
                return env
            return s.scalar(
                select(UiEnv).where(UiEnv.project_id == project_id).order_by(UiEnv.id.desc())
            )

    def create_env(self, **fields) -> int:
        env = UiEnv(**fields)
        with session_scope(self.db_path) as s:
            s.add(env)
            s.flush()
            env_id = env.id
            if env.is_default:
                s.query(UiEnv).filter(
                    UiEnv.project_id == env.project_id, UiEnv.id != env_id
                ).update({UiEnv.is_default: 0})
            return env_id

    def update_env(self, env_id: int, **fields) -> UiEnv | None:
        with session_scope(self.db_path) as s:
            env = s.get(UiEnv, env_id)
            if env is None:
                return None
            for k, v in fields.items():
                if hasattr(env, k):
                    setattr(env, k, v)
            env.updated_at = datetime.now()
            if env.is_default:
                s.query(UiEnv).filter(
                    UiEnv.project_id == env.project_id, UiEnv.id != env_id
                ).update({UiEnv.is_default: 0})
            return env

    def delete_env(self, env_id: int) -> bool:
        with session_scope(self.db_path) as s:
            env = s.get(UiEnv, env_id)
            if env is None:
                return False
            s.delete(env)
            return True

    # ===== 生成记录 =====

    def create_generation(self, **fields) -> int:
        gen = UiGeneration(**fields)
        with session_scope(self.db_path) as s:
            s.add(gen)
            s.flush()
            return gen.id

    def update_generation(self, gen_id: int, **fields) -> None:
        """更新生成记录（生成期先落日志路径，结束时再补终态）。"""
        with session_scope(self.db_path) as s:
            gen = s.get(UiGeneration, gen_id)
            if gen is None:
                return
            for k, v in fields.items():
                if hasattr(gen, k):
                    setattr(gen, k, v)

    def finish_generation(self, gen_id: int, **fields) -> None:
        with session_scope(self.db_path) as s:
            gen = s.get(UiGeneration, gen_id)
            if gen is None:
                return
            for k, v in fields.items():
                if hasattr(gen, k):
                    setattr(gen, k, v)
            gen.finished_at = datetime.now()

    def list_generations(self, case_id: int, limit: int = 30) -> list[UiGeneration]:
        with session_scope(self.db_path) as s:
            return list(
                s.scalars(
                    select(UiGeneration)
                    .where(UiGeneration.ui_case_id == case_id)
                    .order_by(UiGeneration.id.desc())
                    .limit(limit)
                )
            )

    # ===== 反面样本（错题库）=====

    def upsert_lesson(
        self, project_id: int, fingerprint: str, category: str, title: str, content: str
    ) -> int:
        """按指纹去重写入反面样本；命中已有样本时更新正文与时间，不重复膨胀。"""
        with session_scope(self.db_path) as s:
            lesson = s.scalar(
                select(UiLesson).where(
                    UiLesson.project_id == project_id,
                    UiLesson.fingerprint == fingerprint,
                )
            )
            if lesson is not None:
                lesson.category = category
                lesson.title = title
                lesson.content = content
                lesson.updated_at = datetime.now()
                return int(lesson.id)
            lesson = UiLesson(
                project_id=project_id,
                fingerprint=fingerprint,
                category=category,
                title=title,
                content=content,
            )
            s.add(lesson)
            s.flush()
            return int(lesson.id)

    def list_lessons(self, project_id: int, limit: int = 300) -> list[UiLesson]:
        with session_scope(self.db_path) as s:
            return list(
                s.scalars(
                    select(UiLesson)
                    .where(UiLesson.project_id == project_id)
                    .order_by(UiLesson.hits.desc(), UiLesson.updated_at.desc())
                    .limit(limit)
                )
            )

    def bump_lesson_hits(self, lesson_ids: list[int]) -> None:
        """记录样本被注入提示词的次数（淘汰策略按命中次数优先保留）。"""
        if not lesson_ids:
            return
        with session_scope(self.db_path) as s:
            for lesson_id in lesson_ids:
                lesson = s.get(UiLesson, lesson_id)
                if lesson is not None:
                    lesson.hits = int(lesson.hits or 0) + 1

    def trim_lessons(self, project_id: int, keep: int) -> int:
        """超出上限时淘汰「命中次数最少 + 最久未更新」的样本，返回删除条数。"""
        with session_scope(self.db_path) as s:
            stale = list(
                s.scalars(
                    select(UiLesson)
                    .where(UiLesson.project_id == project_id)
                    .order_by(UiLesson.hits.asc(), UiLesson.updated_at.asc())
                )
            )
            extra = len(stale) - keep
            if extra <= 0:
                return 0
            for lesson in stale[:extra]:
                s.delete(lesson)
            return extra

    # ===== 脚本执行记录（ui_runs 中 runner='script' 的行）=====

    def list_script_runs(self, case_id: int, limit: int = 50) -> list[dict]:
        with session_scope(self.db_path) as s:
            rows = s.execute(
                select(RunRecord)
                .where(RunRecord.case_id == case_id, RunRecord.runner == "script")
                .order_by(RunRecord.id.desc())
                .limit(limit)
            ).scalars()
            return [self._run_dict(r) for r in rows]

    def get_script_run(self, run_id: int) -> dict | None:
        with session_scope(self.db_path) as s:
            r = s.get(RunRecord, run_id)
            if r is None or r.runner != "script":
                return None
            return self._run_dict(r)

    def create_script_run(self, run: RunRecord) -> int:
        with session_scope(self.db_path) as s:
            run.steps = []
            s.add(run)
            s.flush()
            return run.id

    def update_script_run(self, run_id: int, **fields) -> None:
        """更新执行记录（执行结束时补终态、耗时、错误与产物路径）。"""
        with session_scope(self.db_path) as s:
            run = s.get(RunRecord, run_id)
            if run is None:
                return
            for key, value in fields.items():
                setattr(run, key, value)

    def delete_script_runs(self, run_ids: list[int]) -> int:
        """删除执行记录（历史裁剪用；调用方需先清理对应产物目录）。"""
        if not run_ids:
            return 0
        with session_scope(self.db_path) as s:
            rows = s.execute(
                select(RunRecord).where(
                    RunRecord.id.in_(run_ids), RunRecord.runner == "script"
                )
            ).scalars()
            deleted = 0
            for row in rows:
                s.delete(row)
                deleted += 1
            return deleted

    @staticmethod
    def _run_dict(r: RunRecord) -> dict:
        return {
            "id": r.id,
            "case_id": r.case_id,
            "case_title": r.case_title,
            "status": r.status.value if hasattr(r.status, "value") else r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "duration_ms": r.duration_ms,
            "base_url_used": r.base_url_used,
            "error": r.error,
            "env_id": r.env_id,
            "script_version": r.script_version,
            "artifacts_rel_path": r.artifacts_rel_path,
            "trace_rel_path": r.trace_rel_path,
        }
