from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AttemptTracker,
    ChapterRollingNote,
    FinalScene,
    SceneMemory,
    SceneRunState,
)
from novel_system.services.chapter_state import ensure_chapter_state
from novel_system.services.errors import DomainError
from novel_system.services.final_text_gate import FinalTextGateService


class Archiver:
    def __init__(self, session: Session) -> None:
        self.session = session

    def archive_final_scene(
        self,
        scene_id: str,
        final_scene_row_id: str,
        qc_report_id: str | None = None,
        *,
        carry_notes_json: list[dict[str, Any]] | None = None,
        execution_id: str | None = None,
        finalize_scene_status: bool = True,
    ) -> dict:
        final_scene = self.session.get(FinalScene, final_scene_row_id)
        state = self.session.get(SceneRunState, scene_id)
        if final_scene is None or state is None or final_scene.scene_id != scene_id:
            raise ValueError("archive target is missing or detached from scene state")
        # Every archive path converges here. Validate the exact FinalScene text,
        # not whichever upstream draft happened to be checked previously.
        final_text_gate = FinalTextGateService(self.session).evaluate(
            scene_id=scene_id,
            content=final_scene.content,
            source_bundle_id=final_scene.source_bundle_id,
        )
        FinalTextGateService.raise_if_not_archivable(final_text_gate, scene_id=scene_id)
        actual_content_hash = str(final_text_gate["content_hash"])
        persisted_content_hash = (final_scene.content_hash or "").strip()
        if persisted_content_hash and persisted_content_hash != actual_content_hash:
            raise DomainError(
                "FINAL_SCENE_CONTENT_HASH_MISMATCH",
                "stored final-scene content hash does not match the exact text being archived",
                status_code=409,
                details={
                    "scene_id": scene_id,
                    "final_scene_row_id": final_scene_row_id,
                    "stored_content_hash": persisted_content_hash,
                    "actual_content_hash": actual_content_hash,
                    "final_text_gate": final_text_gate,
                },
            )
        final_scene.content_hash = actual_content_hash
        # 目录冷启动章可能没有状态行（审计 P-1）：缺行补建而不是 None 解引用崩掉整跑
        chapter_state = ensure_chapter_state(self.session, final_scene.chapter_id)

        memory_row_id = _scene_memory_row_id(scene_id, final_scene_row_id)
        memory = self.session.get(SceneMemory, memory_row_id)
        if memory is None:
            for existing_memory in self.session.execute(
                select(SceneMemory).where(
                    SceneMemory.scene_id == scene_id,
                    SceneMemory.active_flag == 1,
                )
            ).scalars().all():
                existing_memory.active_flag = 0
                existing_memory.runtime_eligible = 0
            memory = SceneMemory(
                row_id=memory_row_id,
                scene_id=scene_id,
                chapter_id=final_scene.chapter_id,
                content=final_scene.content,
                carry_notes_json=carry_notes_json or [],
                source_bundle_id=final_scene.source_bundle_id,
                final_scene_row_id=final_scene_row_id,
                active_flag=1,
                runtime_eligible=1,
                runtime_eligibility_basis="direct_read",
            )
            self.session.add(memory)
        elif (
            memory.scene_id != scene_id
            or memory.chapter_id != final_scene.chapter_id
            or memory.content != final_scene.content
            or memory.carry_notes_json != (carry_notes_json or [])
            or memory.source_bundle_id != final_scene.source_bundle_id
            or memory.final_scene_row_id != final_scene_row_id
        ):
            raise ValueError("existing archive memory conflicts with the requested final scene")
        else:
            for existing_memory in self.session.execute(
                select(SceneMemory).where(
                    SceneMemory.scene_id == scene_id,
                    SceneMemory.active_flag == 1,
                    SceneMemory.row_id != memory_row_id,
                )
            ).scalars().all():
                existing_memory.active_flag = 0
                existing_memory.runtime_eligible = 0
            memory.active_flag = 1
            memory.runtime_eligible = 1
            memory.runtime_eligibility_basis = "direct_read"

        rolling = self.session.execute(
            select(ChapterRollingNote).where(ChapterRollingNote.scene_id == scene_id)
        ).scalars().first()
        if rolling is None:
            rolling = ChapterRollingNote(
                row_id=f"rolling_{scene_id}",
                scene_id=scene_id,
                chapter_id=final_scene.chapter_id,
                source_scene_memory_row_id=memory_row_id,
                note_text=final_scene.content,
                revision_no=1,
            )
            chapter_state.chapter_passed_scene_count += 1
            self.session.add(rolling)
        else:
            if (
                rolling.source_scene_memory_row_id != memory_row_id
                or rolling.note_text != final_scene.content
            ):
                rolling.source_scene_memory_row_id = memory_row_id
                rolling.note_text = final_scene.content
                rolling.revision_no += 1

        # 治理 §5.2 状态词表统一：归档态由本事务写入的权威状态表示，
        # 下游（章节聚合/回放）不再依赖 approved/near_final_ready 的字符串巧合
        final_scene.status = "archived"
        if finalize_scene_status:
            state.scene_status = "archived"
        archive_attempts = self.session.execute(
            select(AttemptTracker).where(
                AttemptTracker.scene_id == scene_id,
                AttemptTracker.step == "archive",
                AttemptTracker.status == "completed",
            )
        ).scalars().all()
        matching_attempts = [
            attempt
            for attempt in archive_attempts
            if (attempt.details_json or {}).get("final_scene_row_id") == final_scene_row_id
            and (attempt.details_json or {}).get("execution_id") == execution_id
        ]
        if len(matching_attempts) > 1:
            raise ValueError("archive attempt audit is not unique")
        if matching_attempts:
            archive_attempt = matching_attempts[0]
        else:
            archive_attempt = AttemptTracker(
                scene_id=scene_id,
                chapter_id=final_scene.chapter_id,
                step="archive",
                status="completed",
                source_bundle_id=final_scene.source_bundle_id,
                details_json={
                    "final_scene_row_id": final_scene_row_id,
                    "qc_report_id": qc_report_id,
                    "execution_id": execution_id,
                    "final_text_gate": _gate_audit_summary(final_text_gate),
                },
            )
            self.session.add(archive_attempt)
        self.session.flush()

        return {
            "scene_memory_row_id": memory_row_id,
            "chapter_rolling_note_row_id": rolling.row_id,
            "archive_attempt_id": archive_attempt.attempt_id,
            "scene_status": state.scene_status,
            "final_text_gate": final_text_gate,
        }


def _scene_memory_row_id(scene_id: str, final_scene_row_id: str) -> str:
    final_prefix = f"final_scene_{scene_id}"
    if final_scene_row_id.startswith(final_prefix):
        return f"scene_memory_{scene_id}{final_scene_row_id[len(final_prefix):]}"
    return f"scene_memory_{scene_id}_{final_scene_row_id}"


def _gate_audit_summary(result: dict[str, Any]) -> dict[str, Any]:
    literary = result.get("literary_quality") or {}
    return {
        "schema_version": result.get("schema_version"),
        "content_hash": result.get("content_hash"),
        "source_bundle_id": result.get("source_bundle_id"),
        "archivable": bool(result.get("archivable")),
        "auto_promotable": bool(result.get("auto_promotable")),
        "archive_blockers": list(result.get("archive_blockers") or []),
        "promotion_blockers": list(result.get("promotion_blockers") or []),
        "literary_scores": dict(literary.get("scores") or {}),
        "risky_dimensions": list(literary.get("risky_dimensions") or []),
    }
