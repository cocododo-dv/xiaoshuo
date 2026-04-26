from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AuthorDraft,
    AuthorPreferenceProfile,
    ChapterGoal,
    ChapterMemory,
    ChapterState,
    FinalScene,
    LongformDiagnosticCard,
    PassagePatchCandidate,
    RevisionCandidate,
    SceneCard,
    SceneRunState,
    WriterEvaluation,
)
from novel_system.services.author_drafts import AuthorDraftService
from novel_system.services.errors import DomainError
from novel_system.services.writer_deep_review import WriterDeepReviewService


SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2, "info": 3}
AUTHOR_DESK_PRESSURE_TYPES = {
    "character_arc_gap",
    "foreshadow_debt",
    "foreshadowing_debt",
    "promise_without_payoff",
    "chapter_promise_unpaid",
}


class AuthorDeskService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def snapshot(self, object_type: str, object_id: str) -> dict[str, Any]:
        target = self._target(object_type, object_id)
        return {
            "target": target,
            "author_draft": self._current_author_draft(object_type, object_id),
            "runtime_text": self._runtime_text(target),
            "aggregate_text": self._aggregate_text(target["chapter_id"]),
            "deep_review_summary": self._deep_review_summary(object_type, object_id),
            "open_candidates": self._open_candidates(object_type, object_id),
            "longform_pressure": self._longform_pressure(target),
            "author_preference_summary": self._author_preference_summary(),
        }

    def _target(self, object_type: str, object_id: str) -> dict[str, str | None]:
        if object_type == "scene":
            scene = self.session.get(SceneCard, object_id)
            if scene is None or scene.trashed_flag == 1:
                raise DomainError("SCENE_NOT_FOUND", "scene not found", status_code=404)
            return {
                "object_type": "scene",
                "object_id": scene.scene_id,
                "chapter_id": scene.chapter_id,
                "scene_id": scene.scene_id,
            }
        if object_type == "chapter":
            chapter = self.session.get(ChapterGoal, object_id)
            if chapter is None or chapter.trashed_flag == 1:
                raise DomainError("CHAPTER_NOT_FOUND", "chapter not found", status_code=404)
            return {
                "object_type": "chapter",
                "object_id": chapter.chapter_id,
                "chapter_id": chapter.chapter_id,
                "scene_id": None,
            }
        raise DomainError("AUTHOR_DESK_TARGET_INVALID", "object_type must be scene or chapter", status_code=400)

    def _current_author_draft(self, object_type: str, object_id: str) -> dict[str, Any] | None:
        row = self.session.execute(
            select(AuthorDraft)
            .where(
                AuthorDraft.object_type == object_type,
                AuthorDraft.object_id == object_id,
                AuthorDraft.status == "current",
            )
            .order_by(AuthorDraft.updated_at.desc(), AuthorDraft.draft_id.desc())
        ).scalars().first()
        return AuthorDraftService.serialize_draft(row)

    def _runtime_text(self, target: dict[str, str | None]) -> dict[str, Any] | None:
        if target["object_type"] == "scene":
            final_scene = self._final_scene(str(target["scene_id"]))
            if final_scene is None:
                return None
            return {
                "source_ref": f"final_scene:{final_scene.row_id}",
                "content": final_scene.content or "",
                "row_id": final_scene.row_id,
                "text_layer": "runtime_final_scene",
            }
        assembled = self._assembled_chapter_text(str(target["chapter_id"]))
        if not assembled:
            return None
        return {
            "source_ref": f"chapter_assembled:{target['chapter_id']}",
            "content": assembled,
            "row_id": None,
            "text_layer": "chapter_assembled",
        }

    def _aggregate_text(self, chapter_id: str | None) -> dict[str, Any] | None:
        if not chapter_id:
            return None
        memory = self._final_chapter_memory(chapter_id)
        if memory is None:
            return None
        return {
            "source_ref": f"chapter_memory:{memory.row_id}",
            "content": memory.content or "",
            "row_id": memory.row_id,
            "text_layer": "chapter_memory_final",
        }

    def _deep_review_summary(self, object_type: str, object_id: str) -> dict[str, Any] | None:
        row = self.session.execute(
            select(WriterEvaluation)
            .where(
                WriterEvaluation.object_type == object_type,
                WriterEvaluation.object_id == object_id,
                WriterEvaluation.rubric_id == "literary_revision_v1",
                WriterEvaluation.parent_evaluation_id.is_(None),
            )
            .order_by(WriterEvaluation.created_at.desc(), WriterEvaluation.evaluation_id.desc())
        ).scalars().first()
        if row is None:
            return None
        findings = row.findings_json or []
        return {
            "evaluation_id": row.evaluation_id,
            "overall_score": row.overall_score,
            "scores": row.scores_json or {},
            "top_findings": findings[:3],
            "revision_brief": row.revision_brief_json or [],
            "requires_human_review": bool(row.requires_human_review),
            "status": row.status,
            "created_at": row.created_at,
        }

    def _open_candidates(self, object_type: str, object_id: str) -> list[dict[str, Any]]:
        patch_rows = self.session.execute(
            select(PassagePatchCandidate)
            .where(
                PassagePatchCandidate.object_type == object_type,
                PassagePatchCandidate.object_id == object_id,
                PassagePatchCandidate.status == "candidate",
            )
            .order_by(PassagePatchCandidate.created_at.desc(), PassagePatchCandidate.patch_id.desc())
        ).scalars().all()
        revision_rows = self.session.execute(
            select(RevisionCandidate)
            .where(
                RevisionCandidate.object_type == object_type,
                RevisionCandidate.object_id == object_id,
                RevisionCandidate.status == "candidate",
            )
            .order_by(RevisionCandidate.created_at.desc(), RevisionCandidate.revision_id.desc())
        ).scalars().all()
        items = [
            {"candidate_type": "passage_patch", **WriterDeepReviewService.serialize_patch_candidate(row)}
            for row in patch_rows
        ]
        items.extend(
            {
                "candidate_type": "revision",
                "revision_id": row.revision_id,
                "object_type": row.object_type,
                "object_id": row.object_id,
                "chapter_id": row.chapter_id,
                "scene_id": row.scene_id,
                "revision_type": row.revision_type,
                "source_text_ref": row.source_text_ref,
                "proposed_text": row.proposed_text,
                "instruction": row.instruction_json or [],
                "diff_summary": row.diff_summary_json or {},
                "patches": row.patches_json or [],
                "apply_mode": row.apply_mode,
                "target_text_ref": row.target_text_ref,
                "status": row.status,
                "created_at": row.created_at,
            }
            for row in revision_rows
        )
        return items

    def _longform_pressure(self, target: dict[str, str | None]) -> list[dict[str, Any]]:
        query = select(LongformDiagnosticCard).where(
            LongformDiagnosticCard.status == "open",
            LongformDiagnosticCard.chapter_id == target["chapter_id"],
            LongformDiagnosticCard.card_type.in_(AUTHOR_DESK_PRESSURE_TYPES),
        )
        if target["object_type"] == "scene":
            query = query.where(
                (LongformDiagnosticCard.scene_id == target["scene_id"])
                | (LongformDiagnosticCard.object_type == "chapter")
            )
        rows = self.session.execute(query).scalars().all()
        rows = sorted(rows, key=lambda row: (SEVERITY_RANK.get(row.severity, 9), row.updated_at, row.card_id))
        return [self._serialize_longform_card(row) for row in rows[:3]]

    def _author_preference_summary(self) -> dict[str, Any]:
        row = self.session.execute(
            select(AuthorPreferenceProfile)
            .where(AuthorPreferenceProfile.scope_type == "global", AuthorPreferenceProfile.scope_ref_id == "global")
            .order_by(AuthorPreferenceProfile.updated_at.desc(), AuthorPreferenceProfile.profile_id.desc())
        ).scalars().first()
        return row.summary_json if row is not None else {}

    def _final_scene(self, scene_id: str) -> FinalScene | None:
        state = self.session.get(SceneRunState, scene_id)
        if state is not None and state.current_final_scene_row_id:
            pointed = self.session.get(FinalScene, state.current_final_scene_row_id)
            if pointed is not None and pointed.scene_id == scene_id:
                return pointed
        return self.session.execute(
            select(FinalScene)
            .where(FinalScene.scene_id == scene_id)
            .order_by(FinalScene.created_at.desc(), FinalScene.row_id.desc())
        ).scalars().first()

    def _final_chapter_memory(self, chapter_id: str) -> ChapterMemory | None:
        state = self.session.get(ChapterState, chapter_id)
        if state is not None and state.last_final_memory_row_id:
            pointed = self.session.get(ChapterMemory, state.last_final_memory_row_id)
            if pointed is not None and pointed.chapter_id == chapter_id and pointed.aggregate_stage == "final":
                return pointed
        return self.session.execute(
            select(ChapterMemory)
            .where(
                ChapterMemory.chapter_id == chapter_id,
                ChapterMemory.aggregate_stage == "final",
                ChapterMemory.active_flag == 1,
            )
            .order_by(ChapterMemory.created_at.desc(), ChapterMemory.row_id.desc())
        ).scalars().first()

    def _assembled_chapter_text(self, chapter_id: str) -> str:
        scenes = self.session.execute(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
            .order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all()
        parts = []
        for scene in scenes:
            final_scene = self._final_scene(scene.scene_id)
            if final_scene is not None and final_scene.content:
                parts.append(final_scene.content)
        return "\n\n".join(parts)

    @staticmethod
    def _serialize_longform_card(row: LongformDiagnosticCard) -> dict[str, Any]:
        return {
            "card_id": row.card_id,
            "card_type": row.card_type,
            "severity": row.severity,
            "object_type": row.object_type,
            "object_id": row.object_id,
            "chapter_id": row.chapter_id,
            "scene_id": row.scene_id,
            "evidence": row.evidence_json or {},
            "recommendation": row.recommendation_json or {},
            "source_refs": row.source_refs_json or [],
            "updated_at": row.updated_at,
        }
