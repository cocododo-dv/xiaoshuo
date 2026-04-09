from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AttemptTracker,
    ChapterRollingNote,
    ChapterState,
    FinalScene,
    SceneMemory,
    SceneRunState,
)


class Archiver:
    def __init__(self, session: Session) -> None:
        self.session = session

    def archive_final_scene(self, scene_id: str, final_scene_row_id: str, qc_report_id: str | None = None) -> dict:
        final_scene = self.session.get(FinalScene, final_scene_row_id)
        state = self.session.get(SceneRunState, scene_id)
        chapter_state = self.session.get(ChapterState, final_scene.chapter_id)

        existing_memory = self.session.execute(
            select(SceneMemory).where(SceneMemory.scene_id == scene_id, SceneMemory.active_flag == 1)
        ).scalars().first()
        if existing_memory:
            existing_memory.active_flag = 0
            existing_memory.runtime_eligible = 0

        memory_row_id = f"scene_memory_{scene_id}"
        memory = SceneMemory(
            row_id=memory_row_id,
            scene_id=scene_id,
            chapter_id=final_scene.chapter_id,
            content=final_scene.content,
            carry_notes_json=[],
            source_bundle_id=final_scene.source_bundle_id,
            final_scene_row_id=final_scene_row_id,
            active_flag=1,
            runtime_eligible=1,
            runtime_eligibility_basis="direct_read",
        )
        self.session.merge(memory)

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
            rolling.source_scene_memory_row_id = memory_row_id
            rolling.note_text = final_scene.content
            rolling.revision_no += 1

        state.scene_status = "archived"
        self.session.add(
            AttemptTracker(
                scene_id=scene_id,
                chapter_id=final_scene.chapter_id,
                step="archive",
                status="completed",
                source_bundle_id=final_scene.source_bundle_id,
                details_json={"final_scene_row_id": final_scene_row_id, "qc_report_id": qc_report_id},
            )
        )
        self.session.flush()

        return {"scene_memory_row_id": memory_row_id, "scene_status": state.scene_status}
