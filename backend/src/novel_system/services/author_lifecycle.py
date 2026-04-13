from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AttemptTracker,
    ChapterGoal,
    ChapterMemory,
    ChapterRollingNote,
    ChapterState,
    HumanReviewEvent,
    InteropArtifact,
    ReviewItem,
    SceneBundle,
    SceneCard,
    SceneDraft,
    SceneMemory,
    SceneRunState,
    FinalScene,
    StagedBackfill,
    utcnow,
)
from novel_system.services.errors import DomainError

TRASH_BLOCK_REASON_HAS_TRASHED_SCENES = "章节下已有单独移入回收站的场景"
SCENE_RUNTIME_ARTIFACTS_REASON = "场景已有下游运行产物"
CHAPTER_RUNTIME_ARTIFACTS_REASON = "章节下仍有场景存在下游运行产物"
SCENE_CHAPTER_TRASHED_RESTORE_REASON = "请先恢复所属章节，再恢复该场景"
SCENE_CHAPTER_TRASHED_PURGE_REASON = "该场景随章节一起回收，请在章节行中处理"


class AuthorLifecycleService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def require_active_chapter(self, chapter_id: str) -> ChapterGoal:
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is None:
            raise DomainError("CHAPTER_NOT_FOUND", "chapter not found", status_code=404)
        if chapter.trashed_flag == 1:
            raise DomainError("CHAPTER_TRASHED", "chapter is currently in author trash")
        return chapter

    def require_active_scene(self, scene_id: str) -> SceneCard:
        scene = self.session.get(SceneCard, scene_id)
        if scene is None:
            raise DomainError("SCENE_NOT_FOUND", "scene not found", status_code=404)
        if scene.trashed_flag == 1:
            raise DomainError("SCENE_TRASHED", "scene is currently in author trash")
        chapter = self.session.get(ChapterGoal, scene.chapter_id)
        if chapter is not None and chapter.trashed_flag == 1:
            raise DomainError("SCENE_TRASHED", "scene is currently in author trash")
        return scene

    def list_active_chapters(self) -> list[dict]:
        chapters = self.session.execute(
            select(ChapterGoal).where(ChapterGoal.trashed_flag == 0).order_by(ChapterGoal.chapter_id.asc())
        ).scalars().all()
        return [self.serialize_chapter_summary(chapter) for chapter in chapters]

    def serialize_chapter_summary(self, chapter: ChapterGoal) -> dict:
        chapter_state = self.session.get(ChapterState, chapter.chapter_id)
        active_scene_count = self._count_scenes(chapter.chapter_id, trashed_flag=0)
        trashed_scene_count = self._count_scenes(chapter.chapter_id, trashed_flag=1)
        trash_block_reason = TRASH_BLOCK_REASON_HAS_TRASHED_SCENES if trashed_scene_count > 0 else None
        return {
            "chapter_id": chapter.chapter_id,
            "planned_scene_count": chapter.planned_scene_count,
            "chapter_goal": chapter.chapter_goal,
            "main_plot_push": chapter.main_plot_push,
            "emotional_target": chapter.emotional_target,
            "ending_effect": chapter.ending_effect,
            "must_not": chapter.must_not,
            "notes": chapter.notes,
            "current_phase": chapter_state.current_phase if chapter_state else "planning",
            "chapter_passed_scene_count": chapter_state.chapter_passed_scene_count if chapter_state else 0,
            "chapter_backfill_pending_count": chapter_state.chapter_backfill_pending_count if chapter_state else 0,
            "active_scene_count": active_scene_count,
            "trashed_scene_count": trashed_scene_count,
            "trash_allowed": 0 if trash_block_reason else 1,
            "trash_block_reason": trash_block_reason,
        }

    def author_workspace_payload(self, chapter_id: str) -> dict:
        chapter = self.require_active_chapter(chapter_id)
        chapter_state = self.session.get(ChapterState, chapter_id)
        scenes = self._chapter_scenes(chapter_id, trashed_flag=0)
        scene_states = {
            state.scene_id: state
            for state in self.session.execute(
                select(SceneRunState).where(SceneRunState.scene_id.in_([scene.scene_id for scene in scenes]))
            ).scalars().all()
        }
        return {
            "chapter": self.serialize_chapter(chapter),
            "chapter_state": self.serialize_chapter_state(chapter_state, chapter_id),
            "scenes": [self.serialize_author_scene(scene, scene_states.get(scene.scene_id)) for scene in scenes],
        }

    def scene_draft_payload(self, chapter_id: str) -> dict:
        chapter = self.require_active_chapter(chapter_id)
        draft = self._empty_scene_draft_payload(chapter_id)
        previous_scene = self._last_active_scene(chapter_id)
        if previous_scene is not None:
            draft.update(
                {
                    "pov_character_id": previous_scene.pov_character_id or "",
                    "onstage_chars_json": list(previous_scene.onstage_chars_json or []),
                    "location": previous_scene.location or "",
                    "target_length_band": previous_scene.target_length_band or "medium",
                    "scene_type": previous_scene.scene_type or "reunion",
                }
            )
        draft["scene_goal"] = self._smart_scene_goal(chapter, previous_scene)
        draft["forbidden_text"] = chapter.must_not or ""
        draft["hook"] = self._smart_scene_hook(chapter)
        return draft

    def _empty_scene_draft_payload(self, chapter_id: str) -> dict:
        return {
            "scene_id": self._suggest_next_scene_id(chapter_id),
            "chapter_id": chapter_id,
            "scene_seq": self.next_scene_append_seq(chapter_id),
            "pov_character_id": "",
            "onstage_chars_json": [],
            "location": "",
            "scene_goal": "",
            "beats_json": [],
            "must_include_text": "",
            "forbidden_text": "",
            "exit_change": "",
            "hook": "",
            "target_length_band": "medium",
            "scene_type": "reunion",
            "is_chapter_last": 0,
        }

    def _smart_scene_goal(self, chapter: ChapterGoal, previous_scene: SceneCard | None) -> str:
        goal_text = (chapter.main_plot_push or chapter.chapter_goal or "").strip()
        previous_exit_change = (previous_scene.exit_change if previous_scene is not None else "") or ""
        previous_exit_change = previous_exit_change.strip()
        if previous_exit_change and goal_text:
            return f"承接上一场景变化：{previous_exit_change}；推进本章目标：{goal_text}"
        if previous_exit_change:
            return f"承接上一场景变化：{previous_exit_change}"
        if goal_text:
            return f"推进本章目标：{goal_text}"
        return ""

    def _smart_scene_hook(self, chapter: ChapterGoal) -> str:
        ending_effect = (chapter.ending_effect or "").strip()
        if ending_effect:
            return f"朝向本章结尾效果：{ending_effect}"
        emotional_target = (chapter.emotional_target or "").strip()
        if emotional_target:
            return f"维持情绪目标：{emotional_target}"
        return ""

    def author_trash_payload(self) -> dict:
        chapters = self.session.execute(
            select(ChapterGoal).where(ChapterGoal.trashed_flag == 1).order_by(ChapterGoal.chapter_id.asc())
        ).scalars().all()
        scenes = self.session.execute(
            select(SceneCard).where(SceneCard.trashed_flag == 1).order_by(SceneCard.chapter_id.asc(), SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all()
        return {
            "chapters": [self.serialize_trashed_chapter(chapter) for chapter in chapters],
            "scenes": [self.serialize_trashed_scene(scene) for scene in scenes],
        }

    def trash_scenes(self, scene_ids: list[str], actor_ref: str) -> dict:
        processed: list[dict] = []
        blocked: list[dict] = []
        for scene_id in self._unique_ids(scene_ids):
            scene = self.session.get(SceneCard, scene_id)
            if scene is None:
                blocked.append({"scene_id": scene_id, "code": "SCENE_NOT_FOUND", "message": "scene not found"})
                continue
            if scene.trashed_flag == 1:
                continue
            chapter = self.require_active_chapter(scene.chapter_id)
            scene.trashed_flag = 1
            scene.trashed_at = self._now()
            scene.trashed_by = actor_ref
            scene.is_chapter_last = 0
            self._normalize_active_last_scene(chapter.chapter_id)
            processed.append({"scene_id": scene.scene_id})
        self.session.flush()
        return {"processed": processed, "blocked": blocked}

    def restore_scenes(self, scene_ids: list[str]) -> dict:
        processed: list[dict] = []
        blocked: list[dict] = []
        for scene_id in self._unique_ids(scene_ids):
            scene = self.session.get(SceneCard, scene_id)
            if scene is None:
                blocked.append({"scene_id": scene_id, "code": "SCENE_NOT_FOUND", "message": "scene not found"})
                continue
            if scene.trashed_flag == 0:
                continue
            chapter = self.session.get(ChapterGoal, scene.chapter_id)
            if chapter is None:
                blocked.append({"scene_id": scene_id, "code": "CHAPTER_NOT_FOUND", "message": "chapter not found"})
                continue
            if chapter.trashed_flag == 1:
                blocked.append(
                    {
                        "scene_id": scene_id,
                        "code": "SCENE_RESTORE_BLOCKED_CHAPTER_TRASHED",
                        "message": SCENE_CHAPTER_TRASHED_RESTORE_REASON,
                    }
                )
                continue
            scene.trashed_flag = 0
            scene.trashed_at = None
            scene.trashed_by = None
            scene.scene_seq = self._next_active_scene_seq(scene.chapter_id)
            scene.is_chapter_last = 0
            self._normalize_active_last_scene(scene.chapter_id)
            processed.append({"scene_id": scene.scene_id})
        self.session.flush()
        return {"processed": processed, "blocked": blocked}

    def purge_scenes(self, scene_ids: list[str]) -> dict:
        processed: list[dict] = []
        blocked: list[dict] = []
        for scene_id in self._unique_ids(scene_ids):
            scene = self.session.get(SceneCard, scene_id)
            if scene is None:
                blocked.append({"scene_id": scene_id, "code": "SCENE_NOT_FOUND", "message": "scene not found"})
                continue
            if scene.trashed_flag == 0:
                blocked.append({"scene_id": scene_id, "code": "SCENE_NOT_TRASHED", "message": "scene is not in author trash"})
                continue
            chapter = self.session.get(ChapterGoal, scene.chapter_id)
            if chapter is not None and chapter.trashed_flag == 1:
                blocked.append(
                    {
                        "scene_id": scene_id,
                        "code": "SCENE_PURGE_BLOCKED_CHAPTER_TRASHED",
                        "message": SCENE_CHAPTER_TRASHED_PURGE_REASON,
                    }
                )
                continue
            reason = self.scene_purge_block_reason(scene)
            if reason is not None:
                blocked.append(
                    {
                        "scene_id": scene_id,
                        "code": "SCENE_PURGE_BLOCKED_RUNTIME_ARTIFACTS",
                        "message": reason,
                    }
                )
                continue
            run_state = self.session.get(SceneRunState, scene.scene_id)
            if run_state is not None:
                self.session.delete(run_state)
            self.session.delete(scene)
            self._normalize_active_last_scene(scene.chapter_id)
            processed.append({"scene_id": scene_id})
        self.session.flush()
        return {"processed": processed, "blocked": blocked}

    def trash_chapters(self, chapter_ids: list[str], actor_ref: str) -> dict:
        processed: list[dict] = []
        blocked: list[dict] = []
        for chapter_id in self._unique_ids(chapter_ids):
            chapter = self.session.get(ChapterGoal, chapter_id)
            if chapter is None:
                blocked.append({"chapter_id": chapter_id, "code": "CHAPTER_NOT_FOUND", "message": "chapter not found"})
                continue
            if chapter.trashed_flag == 1:
                continue
            if self._count_scenes(chapter_id, trashed_flag=1) > 0:
                blocked.append(
                    {
                        "chapter_id": chapter_id,
                        "code": "CHAPTER_TRASH_BLOCKED_HAS_TRASHED_SCENES",
                        "message": TRASH_BLOCK_REASON_HAS_TRASHED_SCENES,
                    }
                )
                continue
            chapter.trashed_flag = 1
            chapter.trashed_at = self._now()
            chapter.trashed_by = actor_ref
            scene_ids: list[str] = []
            for scene in self._chapter_scenes(chapter_id, trashed_flag=0):
                scene.trashed_flag = 1
                scene.trashed_at = chapter.trashed_at
                scene.trashed_by = actor_ref
                scene_ids.append(scene.scene_id)
            processed.append({"chapter_id": chapter_id, "scene_ids": scene_ids})
        self.session.flush()
        return {"processed": processed, "blocked": blocked}

    def restore_chapters(self, chapter_ids: list[str]) -> dict:
        processed: list[dict] = []
        blocked: list[dict] = []
        for chapter_id in self._unique_ids(chapter_ids):
            chapter = self.session.get(ChapterGoal, chapter_id)
            if chapter is None:
                blocked.append({"chapter_id": chapter_id, "code": "CHAPTER_NOT_FOUND", "message": "chapter not found"})
                continue
            if chapter.trashed_flag == 0:
                continue
            chapter.trashed_flag = 0
            chapter.trashed_at = None
            chapter.trashed_by = None
            scene_ids: list[str] = []
            for scene in self._chapter_scenes(chapter_id, trashed_flag=1):
                scene.trashed_flag = 0
                scene.trashed_at = None
                scene.trashed_by = None
                scene_ids.append(scene.scene_id)
            self._normalize_active_last_scene(chapter_id)
            processed.append({"chapter_id": chapter_id, "scene_ids": scene_ids})
        self.session.flush()
        return {"processed": processed, "blocked": blocked}

    def purge_chapters(self, chapter_ids: list[str]) -> dict:
        processed: list[dict] = []
        blocked: list[dict] = []
        for chapter_id in self._unique_ids(chapter_ids):
            chapter = self.session.get(ChapterGoal, chapter_id)
            if chapter is None:
                blocked.append({"chapter_id": chapter_id, "code": "CHAPTER_NOT_FOUND", "message": "chapter not found"})
                continue
            if chapter.trashed_flag == 0:
                blocked.append({"chapter_id": chapter_id, "code": "CHAPTER_NOT_TRASHED", "message": "chapter is not in author trash"})
                continue
            reason = self.chapter_purge_block_reason(chapter)
            if reason is not None:
                blocked.append(
                    {
                        "chapter_id": chapter_id,
                        "code": "CHAPTER_PURGE_BLOCKED_RUNTIME_ARTIFACTS",
                        "message": reason,
                    }
                )
                continue
            scene_ids = [scene.scene_id for scene in self._chapter_scenes(chapter_id, trashed_flag=1)]
            for scene_id in scene_ids:
                state = self.session.get(SceneRunState, scene_id)
                if state is not None:
                    self.session.delete(state)
                scene = self.session.get(SceneCard, scene_id)
                if scene is not None:
                    self.session.delete(scene)
            chapter_state = self.session.get(ChapterState, chapter_id)
            if chapter_state is not None:
                self.session.delete(chapter_state)
            self.session.delete(chapter)
            processed.append({"chapter_id": chapter_id, "scene_ids": scene_ids})
        self.session.flush()
        return {"processed": processed, "blocked": blocked}

    def serialize_chapter(self, chapter: ChapterGoal) -> dict:
        return {
            "chapter_id": chapter.chapter_id,
            "planned_scene_count": chapter.planned_scene_count,
            "mid_aggregate_enabled": chapter.mid_aggregate_enabled,
            "chapter_goal": chapter.chapter_goal,
            "main_plot_push": chapter.main_plot_push,
            "emotional_target": chapter.emotional_target,
            "ending_effect": chapter.ending_effect,
            "must_not": chapter.must_not,
            "notes": chapter.notes,
        }

    def serialize_chapter_state(self, chapter_state: ChapterState | None, chapter_id: str) -> dict:
        if chapter_state is None:
            return {
                "chapter_id": chapter_id,
                "current_phase": "planning",
                "chapter_passed_scene_count": 0,
                "chapter_backfill_pending_count": 0,
            }
        return {
            "chapter_id": chapter_state.chapter_id,
            "current_phase": chapter_state.current_phase,
            "chapter_passed_scene_count": chapter_state.chapter_passed_scene_count,
            "chapter_backfill_pending_count": chapter_state.chapter_backfill_pending_count,
        }

    def serialize_author_scene(self, scene: SceneCard, scene_state: SceneRunState | None) -> dict:
        return {
            "scene_id": scene.scene_id,
            "chapter_id": scene.chapter_id,
            "scene_seq": scene.scene_seq,
            "pov_character_id": scene.pov_character_id,
            "onstage_chars_json": scene.onstage_chars_json,
            "resolved_relation_id": scene.resolved_relation_id,
            "location": scene.location,
            "scene_goal": scene.scene_goal,
            "beats_json": scene.beats_json,
            "must_include_text": scene.must_include_text,
            "forbidden_text": scene.forbidden_text,
            "exit_change": scene.exit_change,
            "hook": scene.hook,
            "target_length_band": scene.target_length_band,
            "scene_type": scene.scene_type,
            "is_chapter_last": scene.is_chapter_last,
            "scene_status": scene_state.scene_status if scene_state else "ready",
            "current_bundle_id": scene_state.current_bundle_id if scene_state else None,
            "current_final_scene_row_id": scene_state.current_final_scene_row_id if scene_state else None,
        }

    def serialize_trashed_chapter(self, chapter: ChapterGoal) -> dict:
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_goal": chapter.chapter_goal,
            "trashed_at": chapter.trashed_at,
            "trashed_by": chapter.trashed_by,
            "scene_count": self._count_scenes(chapter.chapter_id, trashed_flag=1),
            "restore_allowed": 1,
            "restore_block_reason": None,
            "purge_allowed": 0 if self.chapter_purge_block_reason(chapter) else 1,
            "purge_block_reason": self.chapter_purge_block_reason(chapter),
        }

    def serialize_trashed_scene(self, scene: SceneCard) -> dict:
        chapter = self.session.get(ChapterGoal, scene.chapter_id)
        chapter_trashed = 1 if chapter is not None and chapter.trashed_flag == 1 else 0
        restore_block_reason = SCENE_CHAPTER_TRASHED_RESTORE_REASON if chapter_trashed else None
        if chapter_trashed:
            purge_block_reason = SCENE_CHAPTER_TRASHED_PURGE_REASON
        else:
            purge_block_reason = self.scene_purge_block_reason(scene)
        return {
            "scene_id": scene.scene_id,
            "chapter_id": scene.chapter_id,
            "scene_seq": scene.scene_seq,
            "scene_goal": scene.scene_goal,
            "trashed_at": scene.trashed_at,
            "trashed_by": scene.trashed_by,
            "chapter_trashed": chapter_trashed,
            "restore_allowed": 0 if restore_block_reason else 1,
            "restore_block_reason": restore_block_reason,
            "purge_allowed": 0 if purge_block_reason else 1,
            "purge_block_reason": purge_block_reason,
        }

    def scene_purge_block_reason(self, scene: SceneCard) -> str | None:
        state = self.session.get(SceneRunState, scene.scene_id)
        if state is not None:
            if any(
                [
                    state.current_bundle_id,
                    state.current_bundle_hash,
                    state.current_neutral_draft_row_id,
                    state.current_style_draft_row_id,
                    state.current_final_scene_row_id,
                    state.current_human_review_event_id,
                    state.current_qc_report_id,
                    state.bundle_build_count > 0,
                    state.hard_partial_rewrite_count > 0,
                    state.hard_full_rewrite_count > 0,
                    state.soft_patch_count > 0,
                    state.total_attempt_count > 0,
                    state.repeat_issue_key,
                    state.repeat_issue_count > 0,
                ]
            ):
                return SCENE_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(select(SceneBundle.bundle_id).where(SceneBundle.scene_id == scene.scene_id)):
            return SCENE_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(select(SceneDraft.row_id).where(SceneDraft.scene_id == scene.scene_id)):
            return SCENE_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(select(FinalScene.row_id).where(FinalScene.scene_id == scene.scene_id)):
            return SCENE_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(select(SceneMemory.row_id).where(SceneMemory.scene_id == scene.scene_id)):
            return SCENE_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(select(AttemptTracker.attempt_id).where(AttemptTracker.scene_id == scene.scene_id)):
            return SCENE_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(select(ReviewItem.review_id).where(ReviewItem.scene_id == scene.scene_id)):
            return SCENE_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(select(HumanReviewEvent.event_id).where(HumanReviewEvent.scene_id == scene.scene_id)):
            return SCENE_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(select(StagedBackfill.stage_id).where(StagedBackfill.scene_id == scene.scene_id)):
            return SCENE_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(select(InteropArtifact.artifact_id).where(InteropArtifact.scene_id == scene.scene_id)):
            return SCENE_RUNTIME_ARTIFACTS_REASON
        return None

    def chapter_purge_block_reason(self, chapter: ChapterGoal) -> str | None:
        if self._has_rows(select(ChapterMemory.row_id).where(ChapterMemory.chapter_id == chapter.chapter_id)):
            return CHAPTER_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(select(ChapterRollingNote.row_id).where(ChapterRollingNote.chapter_id == chapter.chapter_id)):
            return CHAPTER_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(select(StagedBackfill.stage_id).where(StagedBackfill.chapter_id == chapter.chapter_id)):
            return CHAPTER_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(
            select(ReviewItem.review_id).where(ReviewItem.chapter_id == chapter.chapter_id, ReviewItem.scene_id.is_(None))
        ):
            return CHAPTER_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(
            select(HumanReviewEvent.event_id).where(HumanReviewEvent.chapter_id == chapter.chapter_id, HumanReviewEvent.scene_id.is_(None))
        ):
            return CHAPTER_RUNTIME_ARTIFACTS_REASON
        if self._has_rows(
            select(InteropArtifact.artifact_id).where(InteropArtifact.chapter_id == chapter.chapter_id, InteropArtifact.scene_id.is_(None))
        ):
            return CHAPTER_RUNTIME_ARTIFACTS_REASON
        for scene in self._chapter_scenes(chapter.chapter_id, trashed_flag=1):
            if self.scene_purge_block_reason(scene) is not None:
                return CHAPTER_RUNTIME_ARTIFACTS_REASON
        return None

    def _normalize_active_last_scene(self, chapter_id: str) -> None:
        active_scenes = self._chapter_scenes(chapter_id, trashed_flag=0)
        for scene in active_scenes:
            scene.is_chapter_last = 0
        if active_scenes:
            active_scenes[-1].is_chapter_last = 1

    def _chapter_scenes(self, chapter_id: str, *, trashed_flag: int | None = None) -> list[SceneCard]:
        statement = select(SceneCard).where(SceneCard.chapter_id == chapter_id)
        if trashed_flag is not None:
            statement = statement.where(SceneCard.trashed_flag == trashed_flag)
        statement = statement.order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        return self.session.execute(statement).scalars().all()

    def _count_scenes(self, chapter_id: str, *, trashed_flag: int) -> int:
        return len(self._chapter_scenes(chapter_id, trashed_flag=trashed_flag))

    def _next_active_scene_seq(self, chapter_id: str) -> int:
        active_scenes = self._chapter_scenes(chapter_id, trashed_flag=0)
        if not active_scenes:
            return 1
        return max(scene.scene_seq for scene in active_scenes) + 1

    def next_scene_append_seq(self, chapter_id: str) -> int:
        chapter_scenes = self._chapter_scenes(chapter_id)
        if not chapter_scenes:
            return 1
        return max(scene.scene_seq for scene in chapter_scenes) + 1

    def _last_active_scene(self, chapter_id: str) -> SceneCard | None:
        active_scenes = self._chapter_scenes(chapter_id, trashed_flag=0)
        if not active_scenes:
            return None
        return active_scenes[-1]

    def _suggest_next_scene_id(self, chapter_id: str) -> str:
        pattern = re.compile(rf"^{re.escape(chapter_id)}_SC(\d+)$")
        used_suffixes: set[int] = set()
        suffix_width = 2
        for scene in self._chapter_scenes(chapter_id):
            match = pattern.match(scene.scene_id)
            if match is None:
                continue
            used_suffixes.add(int(match.group(1)))
            suffix_width = max(suffix_width, len(match.group(1)))

        next_suffix = 1
        while next_suffix in used_suffixes:
            next_suffix += 1

        width = max(suffix_width, len(str(next_suffix)), 2)
        return f"{chapter_id}_SC{next_suffix:0{width}d}"

    def _has_rows(self, statement) -> bool:
        return self.session.execute(statement.limit(1)).first() is not None

    def _unique_ids(self, values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if not isinstance(value, str) or not value or value in deduped:
                continue
            deduped.append(value)
        return deduped

    def _now(self) -> str:
        return utcnow()
