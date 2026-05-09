from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import ChapterGoal, ChapterState, ProjectBacktrackItem, SceneCard, StoryProject
from novel_system.services.errors import DomainError

PROJECT_BACKTRACK_BLOCK_REASON = "project_backtrack_pending"


class ProjectBacktrackService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, project_id: str) -> dict[str, Any]:
        self._require_project(project_id)
        rows = self.session.execute(
            select(ProjectBacktrackItem)
            .where(ProjectBacktrackItem.project_id == project_id)
            .order_by(ProjectBacktrackItem.created_at.desc(), ProjectBacktrackItem.item_id.desc())
        ).scalars().all()
        return {"items": [self.serialize(row) for row in rows]}

    def pending_for_project(self, project_id: str) -> list[ProjectBacktrackItem]:
        return self.session.execute(
            select(ProjectBacktrackItem)
            .where(
                ProjectBacktrackItem.project_id == project_id,
                ProjectBacktrackItem.status == "pending",
            )
            .order_by(ProjectBacktrackItem.created_at.asc(), ProjectBacktrackItem.item_id.asc())
        ).scalars().all()

    def pending_for_chapter(self, chapter_id: str) -> list[ProjectBacktrackItem]:
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is None or not chapter.project_id:
            return []
        return self.session.execute(
            select(ProjectBacktrackItem)
            .where(
                ProjectBacktrackItem.project_id == chapter.project_id,
                ProjectBacktrackItem.status == "pending",
                (ProjectBacktrackItem.chapter_id.is_(None)) | (ProjectBacktrackItem.chapter_id == chapter_id),
            )
            .order_by(ProjectBacktrackItem.created_at.asc(), ProjectBacktrackItem.item_id.asc())
        ).scalars().all()

    def ensure_item(
        self,
        *,
        project_id: str,
        chapter_id: str | None,
        scene_id: str | None,
        scope: str,
        target_ref: str,
        problem_summary: str,
        recommended_fix: str,
        reason_codes: list[str] | None = None,
        source_qc_report_id: str | None = None,
        source_contract_id: str | None = None,
        created_by: str = "scene_triage",
    ) -> ProjectBacktrackItem:
        self._require_project(project_id)
        existing = self.session.execute(
            select(ProjectBacktrackItem).where(
                ProjectBacktrackItem.project_id == project_id,
                ProjectBacktrackItem.target_ref == target_ref,
                ProjectBacktrackItem.scope == scope,
                ProjectBacktrackItem.status == "pending",
            )
        ).scalars().first()
        if existing is not None:
            existing.problem_summary = problem_summary
            existing.recommended_fix = recommended_fix
            existing.reason_codes_json = list(reason_codes or [])
            existing.source_qc_report_id = source_qc_report_id
            existing.source_contract_id = source_contract_id
            self._apply_block(chapter_id, project_id)
            self.session.flush()
            return existing

        item = ProjectBacktrackItem(
            item_id=f"project_backtrack_{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            scope=scope,
            target_ref=target_ref,
            status="pending",
            problem_summary=problem_summary,
            recommended_fix=recommended_fix,
            reason_codes_json=list(reason_codes or []),
            source_qc_report_id=source_qc_report_id,
            source_contract_id=source_contract_id,
            created_by=created_by,
        )
        self.session.add(item)
        self._apply_block(chapter_id, project_id)
        self.session.flush()
        return item

    def resolve(self, project_id: str, item_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        row = self._require_item(project_id, item_id)
        body = payload or {}
        row.status = "resolved"
        row.resolution_note = str(body.get("resolution_note") or "").strip() or None
        self._release_block(row.chapter_id, row.project_id)
        self.session.flush()
        return {"item": self.serialize(row)}

    @staticmethod
    def serialize(row: ProjectBacktrackItem) -> dict[str, Any]:
        return {
            "item_id": row.item_id,
            "project_id": row.project_id,
            "chapter_id": row.chapter_id,
            "scene_id": row.scene_id,
            "scope": row.scope,
            "target_ref": row.target_ref,
            "status": row.status,
            "problem_summary": row.problem_summary,
            "recommended_fix": row.recommended_fix,
            "reason_codes": list(row.reason_codes_json or []),
            "source_qc_report_id": row.source_qc_report_id,
            "source_contract_id": row.source_contract_id,
            "resolution_note": row.resolution_note,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def _apply_block(self, chapter_id: str | None, project_id: str) -> None:
        chapter_ids = [chapter_id] if chapter_id else [
            row[0]
            for row in self.session.execute(
                select(ChapterGoal.chapter_id).where(ChapterGoal.project_id == project_id, ChapterGoal.trashed_flag == 0)
            ).all()
        ]
        for current_chapter_id in chapter_ids:
            if not current_chapter_id:
                continue
            state = self.session.get(ChapterState, current_chapter_id)
            if state is None:
                state = ChapterState(
                    chapter_id=current_chapter_id,
                    current_phase="planning",
                    mid_aggregate_enabled_effective=0,
                    aggregate_block_reason=PROJECT_BACKTRACK_BLOCK_REASON,
                )
                self.session.add(state)
            state.aggregate_block_reason = PROJECT_BACKTRACK_BLOCK_REASON

    def _release_block(self, chapter_id: str | None, project_id: str) -> None:
        pending = self.pending_for_project(project_id)
        if chapter_id:
            pending = [
                item
                for item in pending
                if item.chapter_id in {None, chapter_id}
            ]
            if pending:
                return
            state = self.session.get(ChapterState, chapter_id)
            if state is not None and state.aggregate_block_reason == PROJECT_BACKTRACK_BLOCK_REASON:
                state.aggregate_block_reason = "none"
            return

        if pending:
            return
        chapter_ids = [
            row[0]
            for row in self.session.execute(
                select(ChapterGoal.chapter_id).where(ChapterGoal.project_id == project_id, ChapterGoal.trashed_flag == 0)
            ).all()
        ]
        for current_chapter_id in chapter_ids:
            state = self.session.get(ChapterState, current_chapter_id)
            if state is not None and state.aggregate_block_reason == PROJECT_BACKTRACK_BLOCK_REASON:
                state.aggregate_block_reason = "none"

    def _require_project(self, project_id: str) -> StoryProject:
        project = self.session.get(StoryProject, project_id)
        if project is None:
            raise DomainError("PROJECT_NOT_FOUND", "project not found", status_code=404)
        return project

    def _require_item(self, project_id: str, item_id: str) -> ProjectBacktrackItem:
        row = self.session.get(ProjectBacktrackItem, item_id)
        if row is None or row.project_id != project_id:
            raise DomainError("PROJECT_BACKTRACK_ITEM_NOT_FOUND", "project backtrack item not found", status_code=404)
        return row
