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
    ) -> dict:
        final_scene = self.session.get(FinalScene, final_scene_row_id)
        state = self.session.get(SceneRunState, scene_id)
        # 目录冷启动章可能没有状态行（审计 P-1）：缺行补建而不是 None 解引用崩掉整跑
        chapter_state = ensure_chapter_state(self.session, final_scene.chapter_id)

        existing_memory = self.session.execute(
            select(SceneMemory).where(SceneMemory.scene_id == scene_id, SceneMemory.active_flag == 1)
        ).scalars().first()
        if existing_memory:
            existing_memory.active_flag = 0
            existing_memory.runtime_eligible = 0

        memory_row_id = _scene_memory_row_id(scene_id, final_scene_row_id)
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

        # 治理 §5.2 状态词表统一：归档态由本事务写入的权威状态表示，
        # 下游（章节聚合/回放）不再依赖 approved/near_final_ready 的字符串巧合
        final_scene.status = "archived"
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


def _scene_memory_row_id(scene_id: str, final_scene_row_id: str) -> str:
    final_prefix = f"final_scene_{scene_id}"
    if final_scene_row_id.startswith(final_prefix):
        return f"scene_memory_{scene_id}{final_scene_row_id[len(final_prefix):]}"
    return f"scene_memory_{scene_id}_{final_scene_row_id}"
