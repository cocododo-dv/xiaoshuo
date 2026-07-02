from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ChapterGoal,
    ChapterMemory,
    SceneMemory,
    VolumeSummary,
)
from novel_system.services.chapter_state import ensure_chapter_state

# §2 summary tower: roll chapters up into a volume every N chapters so long books
# (50+ scenes) have a far-horizon ATMOSPHERE context the chapter layer is too fine for.
VOLUME_CHAPTER_SPAN = 5


class Aggregator:
    def __init__(self, session: Session) -> None:
        self.session = session

    def maybe_aggregate_volume(self, chapter_id: str) -> dict | None:
        """§2 summary tower: roll up a volume when a chapter completes a span boundary.

        Triggered at chapter finalization. When the just-finished chapter is the Nth
        (VOLUME_CHAPTER_SPAN) in display order with no later volume covering it, build a
        volume-level atmosphere summary from the chapters' final memories. Idempotent:
        re-running for the same window supersedes the prior volume summary.
        """
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is None or chapter.project_id is None or chapter.display_order is None:
            return {"status": "no_op", "reason": "chapter_unmapped"}

        project_id = chapter.project_id
        # Ordered, non-trashed chapters of this project up to and including the current one.
        ordered = list(self.session.execute(
            select(ChapterGoal)
            .where(
                ChapterGoal.project_id == project_id,
                ChapterGoal.trashed_flag == 0,
                ChapterGoal.display_order.isnot(None),
                ChapterGoal.display_order <= chapter.display_order,
            )
            .order_by(ChapterGoal.display_order.asc())
        ).scalars().all())
        if len(ordered) % VOLUME_CHAPTER_SPAN != 0:
            return {"status": "no_op", "reason": "not_at_volume_boundary", "chapter_count": len(ordered)}

        volume_seq = len(ordered) // VOLUME_CHAPTER_SPAN
        window = ordered[-VOLUME_CHAPTER_SPAN:]
        return self.aggregate_volume_summary(project_id, volume_seq, [c.chapter_id for c in window])

    def aggregate_volume_summary(
        self, project_id: str, volume_seq: int, chapter_ids: list[str],
    ) -> dict | None:
        """Build a volume-level atmosphere summary from the chapters' final memories.

        Deterministic by default (concatenated, clearly labeled as atmosphere — NOT
        facts, per §2). Supersedes any prior volume summary for the same (project,seq).
        """
        if not chapter_ids:
            return {"status": "no_op", "reason": "empty_window"}

        memories = list(self.session.execute(
            select(ChapterMemory)
            .where(
                ChapterMemory.chapter_id.in_(chapter_ids),
                ChapterMemory.aggregate_stage == "final",
                ChapterMemory.active_flag == 1,
            )
        ).scalars().all())
        if not memories:
            return {"status": "no_op", "reason": "no_chapter_memories"}

        # Preserve chapter order in the window for a coherent far-horizon arc.
        order = {cid: i for i, cid in enumerate(chapter_ids)}
        memories.sort(key=lambda m: order.get(m.chapter_id, 0))
        atmosphere = "\n\n".join(
            f"【第{order.get(m.chapter_id, 0) + 1}章 氛围】{m.content}".strip()
            for m in memories if m.content
        )

        # Supersede prior volume summary for this (project, seq).
        prior = list(self.session.execute(
            select(VolumeSummary).where(
                VolumeSummary.project_id == project_id,
                VolumeSummary.volume_seq == volume_seq,
                VolumeSummary.active_flag == 1,
            )
        ).scalars().all())
        for old in prior:
            old.active_flag = 0
            old.runtime_eligible = 0
            old.runtime_eligibility_basis = "superseded"

        row_id = f"volume_summary_{project_id}_v{volume_seq}_{len(prior) + 1}"
        summary = VolumeSummary(
            row_id=row_id,
            project_id=project_id,
            volume_seq=volume_seq,
            chapter_id_start=chapter_ids[0],
            chapter_id_end=chapter_ids[-1],
            chapter_count=len(chapter_ids),
            atmosphere_summary=atmosphere,
            active_flag=1,
            runtime_eligible=1,
            runtime_eligibility_basis="direct_read",
        )
        self.session.add(summary)
        self.session.flush()
        return {
            "status": "created",
            "reason": "volume_rolled_up",
            "volume_summary_row_id": row_id,
            "volume_seq": volume_seq,
            "chapter_count": len(chapter_ids),
        }

    def run_final_aggregate(self, chapter_id: str) -> dict | None:
        # 目录冷启动章可能没有状态行（审计 P-1）：缺行补建
        chapter_state = ensure_chapter_state(self.session, chapter_id)
        if chapter_state.chapter_backfill_pending_count != 0 or chapter_state.aggregate_block_reason != "none":
            return {
                "status": "blocked",
                "reason": "aggregate_gate_blocked",
                "chapter_memory_row_id": None,
            }

        scene_memories = self.session.execute(
            select(SceneMemory).where(SceneMemory.chapter_id == chapter_id, SceneMemory.active_flag == 1)
        ).scalars().all()
        if not scene_memories:
            return {
                "status": "no_op",
                "reason": "no_scene_memories",
                "chapter_memory_row_id": None,
            }

        content = "\n".join(memory.content for memory in scene_memories)
        existing_finals = self.session.execute(
            select(ChapterMemory)
            .where(ChapterMemory.chapter_id == chapter_id, ChapterMemory.aggregate_stage == "final")
            .order_by(ChapterMemory.row_id.asc())
        ).scalars().all()
        for existing in existing_finals:
            if existing.active_flag == 1:
                existing.active_flag = 0
                existing.runtime_eligible = 0
                existing.runtime_eligibility_basis = "superseded"

        row_id = f"chapter_memory_final_{chapter_id}_v{len(existing_finals) + 1}"
        memory = ChapterMemory(
            row_id=row_id,
            chapter_id=chapter_id,
            aggregate_stage="final",
            content=content,
            active_flag=1,
            runtime_eligible=1,
            runtime_eligibility_basis="direct_read",
        )
        self.session.add(memory)
        chapter_state.last_final_memory_row_id = row_id
        return {"status": "created", "reason": "scene_memories_aggregated", "chapter_memory_row_id": row_id}
