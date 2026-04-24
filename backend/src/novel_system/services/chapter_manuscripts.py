from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ChapterGoal,
    ChapterMemory,
    ChapterState,
    FinalScene,
    RevisionCandidate,
    SceneBundle,
    SceneCard,
    SceneRunState,
)
from novel_system.services.author_lifecycle import AuthorLifecycleService
from novel_system.services.source_safety import scan_source_safety, source_profile_ids_from_snapshot
from novel_system.services.writer_review import WriterReviewService


class ChapterManuscriptService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.lifecycle = AuthorLifecycleService(session)

    def list_manuscripts(self) -> list[dict[str, Any]]:
        chapters = self.session.execute(
            select(ChapterGoal).where(ChapterGoal.trashed_flag == 0).order_by(ChapterGoal.chapter_id.asc())
        ).scalars().all()
        return [self._chapter_list_item(chapter) for chapter in chapters]

    def manuscript_detail(self, chapter_id: str) -> dict[str, Any]:
        chapter = self.lifecycle.require_active_chapter(chapter_id)
        chapter_state = self.session.get(ChapterState, chapter_id)
        scenes = self._active_scenes(chapter_id)
        scene_states = self._scene_states(scenes)
        scene_entries = [self._scene_entry(scene, scene_states.get(scene.scene_id)) for scene in scenes]
        assembled = self._assembled_payload(scene_entries)
        aggregate = self._aggregate_payload(self._resolve_final_aggregate(chapter_id, chapter_state))
        source_safety_scan = scan_source_safety(
            [assembled["content"], aggregate["content"] if aggregate else ""],
            source_profile_ids=self._source_profile_ids_for_entries(scene_entries),
        )
        writer_review = WriterReviewService(self.session)
        writer_review_summary = writer_review.chapter_summary(chapter_id)
        editorial_workspace = self._editorial_workspace(
            chapter_id=chapter_id,
            scene_entries=scene_entries,
            chapter_review=writer_review_summary,
            writer_review=writer_review,
            aggregate=aggregate,
        )
        return {
            "chapter": self.lifecycle.serialize_chapter(chapter),
            "chapter_state": self.lifecycle.serialize_chapter_state(chapter_state, chapter_id),
            "completion_status": self._completion_status(
                assembled["scene_count"],
                assembled["generated_scene_count"],
            ),
            "comparison_status": self._comparison_status(assembled["content"], aggregate),
            "assembled": assembled,
            "aggregate": aggregate,
            "source_safety_scan": source_safety_scan,
            "writer_review_summary": writer_review_summary,
            "editorial_workspace": editorial_workspace,
            "scenes": scene_entries,
        }

    def _chapter_list_item(self, chapter: ChapterGoal) -> dict[str, Any]:
        chapter_state = self.session.get(ChapterState, chapter.chapter_id)
        scenes = self._active_scenes(chapter.chapter_id)
        scene_states = self._scene_states(scenes)
        scene_entries = [self._scene_entry(scene, scene_states.get(scene.scene_id)) for scene in scenes]
        assembled = self._assembled_payload(scene_entries)
        aggregate = self._aggregate_payload(self._resolve_final_aggregate(chapter.chapter_id, chapter_state))
        return {
            **self.lifecycle.serialize_chapter_summary(chapter),
            "scene_count": assembled["scene_count"],
            "generated_scene_count": assembled["generated_scene_count"],
            "missing_scene_ids": assembled["missing_scene_ids"],
            "completion_status": self._completion_status(
                assembled["scene_count"],
                assembled["generated_scene_count"],
            ),
            "comparison_status": self._comparison_status(assembled["content"], aggregate),
            "aggregate_row_id": aggregate["row_id"] if aggregate else None,
            "writer_review_summary": WriterReviewService(self.session).chapter_summary(chapter.chapter_id),
        }

    def _active_scenes(self, chapter_id: str) -> list[SceneCard]:
        return self.session.execute(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
            .order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all()

    def _scene_states(self, scenes: list[SceneCard]) -> dict[str, SceneRunState]:
        if not scenes:
            return {}
        states = self.session.execute(
            select(SceneRunState).where(SceneRunState.scene_id.in_([scene.scene_id for scene in scenes]))
        ).scalars().all()
        return {state.scene_id: state for state in states}

    def _scene_entry(self, scene: SceneCard, scene_state: SceneRunState | None) -> dict[str, Any]:
        final_scene = self._resolve_current_final_scene(scene, scene_state)
        return {
            **self.lifecycle.serialize_author_scene(scene, scene_state),
            "final_scene": self._final_scene_payload(final_scene),
        }

    def _resolve_current_final_scene(self, scene: SceneCard, scene_state: SceneRunState | None) -> FinalScene | None:
        if scene_state is None or not scene_state.current_final_scene_row_id:
            return None
        final_scene = self.session.get(FinalScene, scene_state.current_final_scene_row_id)
        if final_scene is None:
            return None
        if final_scene.scene_id != scene.scene_id or final_scene.chapter_id != scene.chapter_id:
            return None
        return final_scene

    @staticmethod
    def _final_scene_payload(final_scene: FinalScene | None) -> dict[str, Any] | None:
        if final_scene is None:
            return None
        return {
            "row_id": final_scene.row_id,
            "char_count": len(final_scene.content or ""),
            "created_at": final_scene.created_at,
        }

    def _assembled_payload(self, scene_entries: list[dict[str, Any]]) -> dict[str, Any]:
        generated_contents: list[str] = []
        missing_scene_ids: list[str] = []
        for scene in scene_entries:
            final_scene = scene.get("final_scene")
            if final_scene is None:
                missing_scene_ids.append(scene["scene_id"])
                continue
            row = self.session.get(FinalScene, final_scene["row_id"])
            if row is None:
                missing_scene_ids.append(scene["scene_id"])
                continue
            generated_contents.append(row.content or "")
        content = "\n".join(generated_contents)
        return {
            "content": content,
            "char_count": len(content),
            "scene_count": len(scene_entries),
            "generated_scene_count": len(generated_contents),
            "missing_scene_ids": missing_scene_ids,
        }

    def _source_profile_ids_for_entries(self, scene_entries: list[dict[str, Any]]) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for scene in scene_entries:
            final_scene = scene.get("final_scene")
            if not isinstance(final_scene, dict):
                continue
            row = self.session.get(FinalScene, final_scene.get("row_id"))
            if row is None or not row.source_bundle_id:
                continue
            bundle = self.session.get(SceneBundle, row.source_bundle_id)
            for value in source_profile_ids_from_snapshot(bundle.frozen_snapshot_json if bundle else None):
                if value in seen:
                    continue
                seen.add(value)
                values.append(value)
        return values

    def _editorial_workspace(
        self,
        *,
        chapter_id: str,
        scene_entries: list[dict[str, Any]],
        chapter_review: dict[str, Any],
        writer_review: WriterReviewService,
        aggregate: dict[str, Any] | None,
    ) -> dict[str, Any]:
        scene_reviews = [
            {
                "scene_id": scene["scene_id"],
                "scene_seq": scene.get("scene_seq"),
                "scene_goal": scene.get("scene_goal"),
                "review": writer_review.scene_summary(scene["scene_id"]),
            }
            for scene in scene_entries
        ]
        candidates = self._chapter_revision_candidates(chapter_id, [scene["scene_id"] for scene in scene_entries])
        review_summaries = [chapter_review, *[item["review"] for item in scene_reviews]]
        return {
            "reading_source": "aggregate" if aggregate else "assembled",
            "chapter_review": chapter_review,
            "scene_reviews": scene_reviews,
            "revision_candidates": candidates,
            "open_issue_counts": self._open_issue_counts(review_summaries),
        }

    def _chapter_revision_candidates(self, chapter_id: str, scene_ids: list[str]) -> list[dict[str, Any]]:
        object_pairs = {("chapter", chapter_id), *{("scene", scene_id) for scene_id in scene_ids}}
        rows = self.session.execute(
            select(RevisionCandidate)
            .where(RevisionCandidate.chapter_id == chapter_id)
            .order_by(
                RevisionCandidate.object_type.asc(),
                RevisionCandidate.created_at.desc(),
                RevisionCandidate.revision_id.asc(),
            )
        ).scalars().all()
        serialized: list[dict[str, Any]] = []
        for row in rows:
            if (row.object_type, row.object_id) not in object_pairs:
                continue
            payload = WriterReviewService.serialize_revision(row)
            payload["scope_label"] = "chapter" if row.object_type == "chapter" else row.scene_id or row.object_id
            serialized.append(payload)
        return serialized

    @staticmethod
    def _open_issue_counts(review_summaries: list[dict[str, Any]]) -> dict[str, int]:
        open_candidates = 0
        findings = 0
        requires_human_review = 0
        reviewed_objects = 0
        for summary in review_summaries:
            evaluation = summary.get("latest_evaluation")
            if evaluation:
                reviewed_objects += 1
                findings += len(evaluation.get("findings") or [])
                if evaluation.get("requires_human_review"):
                    requires_human_review += 1
            open_candidates += sum(1 for candidate in summary.get("candidates") or [] if candidate.get("status") == "candidate")
        return {
            "open_candidates": open_candidates,
            "findings": findings,
            "requires_human_review": requires_human_review,
            "reviewed_objects": reviewed_objects,
        }

    def _resolve_final_aggregate(self, chapter_id: str, chapter_state: ChapterState | None) -> ChapterMemory | None:
        if chapter_state is not None and chapter_state.last_final_memory_row_id:
            pointed = self.session.get(ChapterMemory, chapter_state.last_final_memory_row_id)
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

    @staticmethod
    def _aggregate_payload(memory: ChapterMemory | None) -> dict[str, Any] | None:
        if memory is None:
            return None
        return {
            "row_id": memory.row_id,
            "content": memory.content or "",
            "char_count": len(memory.content or ""),
            "created_at": memory.created_at,
        }

    @staticmethod
    def _completion_status(scene_count: int, generated_scene_count: int) -> str:
        if generated_scene_count == 0:
            return "empty"
        if scene_count > 0 and generated_scene_count >= scene_count:
            return "complete"
        return "partial"

    @staticmethod
    def _comparison_status(assembled_content: str, aggregate: dict[str, Any] | None) -> str:
        if aggregate is None:
            return "aggregate_missing"
        if aggregate["content"] == assembled_content:
            return "aggregate_matches_current"
        return "aggregate_differs_current"
