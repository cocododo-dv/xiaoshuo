from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    FinalScene,
    QcReport,
    SceneCard,
    SceneDraft,
    SceneExecutionContract,
    SceneQualityContract,
    SceneRunState,
    StoryProject,
)
from novel_system.services.project_backtracks import PROJECT_BACKTRACK_BLOCK_REASON, ProjectBacktrackService


class ProjectRuntimeInvalidationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.backtracks = ProjectBacktrackService(session)

    def invalidate_for_snowflake_step(self, project_id: str, step_key: str) -> None:
        project = self.session.get(StoryProject, project_id)
        if project is None:
            return
        scenes = self.session.execute(
            select(SceneCard).where(SceneCard.project_id == project_id, SceneCard.trashed_flag == 0)
        ).scalars().all()
        if not scenes:
            return
        scene_ids = [scene.scene_id for scene in scenes]
        chapter_ids = sorted({scene.chapter_id for scene in scenes})

        for row in self.session.execute(
            select(SceneExecutionContract).where(
                SceneExecutionContract.scene_id.in_(scene_ids),
                SceneExecutionContract.status.in_(("active", "blocked")),
            )
        ).scalars().all():
            row.status = "stale"

        for row in self.session.execute(
            select(SceneDraft).where(SceneDraft.scene_id.in_(scene_ids), SceneDraft.status != "stale")
        ).scalars().all():
            row.status = "stale"

        for row in self.session.execute(
            select(QcReport).where(QcReport.scene_id.in_(scene_ids), QcReport.status != "stale")
        ).scalars().all():
            row.status = "stale"

        for row in self.session.execute(
            select(SceneQualityContract).where(
                SceneQualityContract.scene_id.in_(scene_ids),
                SceneQualityContract.status == "active",
            )
        ).scalars().all():
            row.status = "superseded"

        final_row_ids = [
            row.current_final_scene_row_id
            for row in self.session.execute(select(SceneRunState).where(SceneRunState.scene_id.in_(scene_ids))).scalars().all()
            if row.current_final_scene_row_id
        ]
        if final_row_ids:
            for row in self.session.execute(
                select(FinalScene).where(FinalScene.row_id.in_(final_row_ids))
            ).scalars().all():
                row.status = "stale"

        for state in self.session.execute(select(SceneRunState).where(SceneRunState.scene_id.in_(scene_ids))).scalars().all():
            state.scene_status = "needs_replan"
            state.current_bundle_id = None
            state.current_bundle_hash = None
            state.current_neutral_draft_row_id = None
            state.current_style_draft_row_id = None
            state.current_final_scene_row_id = None
            state.current_human_review_event_id = None
            state.current_qc_report_id = None

        for chapter_id in chapter_ids:
            state = self.session.get(ChapterState, chapter_id)
            if state is None:
                state = ChapterState(
                    chapter_id=chapter_id,
                    current_phase="planning",
                    mid_aggregate_enabled_effective=0,
                    aggregate_block_reason=PROJECT_BACKTRACK_BLOCK_REASON,
                )
                self.session.add(state)
            state.current_phase = "planning"
            state.aggregate_block_reason = PROJECT_BACKTRACK_BLOCK_REASON

        scope = _scope_for_step(step_key)
        self.backtracks.ensure_item(
            project_id=project_id,
            chapter_id=None,
            scene_id=None,
            scope=scope,
            target_ref=f"snowflake:{step_key}",
            problem_summary=f"Snowflake step {step_key} was reapproved, so downstream runtime artifacts are stale.",
            recommended_fix="Review the updated snowflake output, regenerate execution contracts, and rerun the affected scenes.",
            reason_codes=["snowflake_reapproved", step_key],
            created_by="snowflake_planner",
        )
        if project.status not in {"completed"}:
            project.status = "chapter_blocked"


def _scope_for_step(step_key: str) -> str:
    if step_key in {"character_sheets", "character_synopses", "character_bibles"}:
        return "character"
    if step_key in {"scene_list", "scene_details"}:
        return "scene_list"
    return "synopsis"
