from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import ChapterMemory, ChapterState, SceneMemory


class Aggregator:
    def __init__(self, session: Session) -> None:
        self.session = session

    def run_final_aggregate(self, chapter_id: str) -> dict | None:
        chapter_state = self.session.get(ChapterState, chapter_id)
        if chapter_state.chapter_backfill_pending_count != 0 or chapter_state.aggregate_block_reason != "none":
            return None

        scene_memories = self.session.execute(
            select(SceneMemory).where(SceneMemory.chapter_id == chapter_id, SceneMemory.active_flag == 1)
        ).scalars().all()
        if not scene_memories:
            return None

        content = "\n".join(memory.content for memory in scene_memories)
        row_id = f"chapter_memory_final_{chapter_id}"
        memory = ChapterMemory(
            row_id=row_id,
            chapter_id=chapter_id,
            aggregate_stage="final",
            content=content,
            active_flag=1,
            runtime_eligible=1,
        )
        self.session.merge(memory)
        chapter_state.last_final_memory_row_id = row_id
        return {"chapter_memory_row_id": row_id}
