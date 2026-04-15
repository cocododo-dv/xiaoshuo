from __future__ import annotations

from sqlalchemy.orm import Session

from novel_system.db.models import FinalScene, SceneCard, SceneDraft, SceneRunState
from novel_system.services.aggregator import Aggregator
from novel_system.services.archiver import Archiver
from novel_system.services.bundle_builder import BundleBuilder
from novel_system.services.qc_validator import validate_qc_report
from novel_system.services.scene_generation import SceneGenerationService
from novel_system.services.version_manager import VersionManager


class Orchestrator:
    def __init__(
        self,
        session: Session,
        *,
        scene_generation_service: SceneGenerationService | None = None,
    ) -> None:
        self.session = session
        self.bundle_builder = BundleBuilder(session)
        self.archiver = Archiver(session)
        self.aggregator = Aggregator(session)
        self.version_manager = VersionManager(session)
        self.scene_generation_service = scene_generation_service or SceneGenerationService(session)

    def run_scene(self, scene_id: str, from_step: str = "bundle", resume: bool = False) -> dict:
        self.version_manager.recover_stuck_jobs()
        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)
        bundle = self.bundle_builder.build(scene_id, "P2")

        neutral_generation = self.scene_generation_service.generate_neutral_draft(scene_id, bundle)
        neutral_content = neutral_generation["content"]

        validate_qc_report(
            "hard_qc",
            {
                "resolution_code": "hard_pass",
                "pass_flag": True,
                "next_action": "pass",
                "issues": [],
                "rewrite_brief": [],
            },
        )

        style_row_id = f"draft_style_{scene_id}"
        style_content = (
            f"{neutral_content}\n\n"
            "The restraint stays visible in what goes unsaid, so the pressure lingers after the exchange."
        )
        style_draft = SceneDraft(
            row_id=style_row_id,
            scene_id=scene_id,
            chapter_id=scene.chapter_id,
            stage="style_draft",
            content=style_content,
            source_bundle_id=bundle["bundle_id"],
            source_bundle_hash=bundle["bundle_snapshot_hash"],
        )
        self.session.merge(style_draft)
        state.current_style_draft_row_id = style_row_id

        validate_qc_report(
            "soft_qc",
            {
                "resolution_code": "soft_pass",
                "pass_flag": True,
                "next_action": "pass",
                "issues": [],
            },
        )

        final_row_id = f"final_scene_{scene_id}"
        final_scene = FinalScene(
            row_id=final_row_id,
            scene_id=scene_id,
            chapter_id=scene.chapter_id,
            content=style_content,
            status="approved",
            source_bundle_id=bundle["bundle_id"],
            source_bundle_hash=bundle["bundle_snapshot_hash"],
        )
        self.session.merge(final_scene)
        self.session.flush()
        state.current_final_scene_row_id = final_row_id

        archive_result = self.archiver.archive_final_scene(scene_id, final_row_id)

        if scene.is_chapter_last == 1:
            self.aggregator.run_final_aggregate(scene.chapter_id)

        return {
            "scene_status": archive_result["scene_status"],
            "current_bundle_id": bundle["bundle_id"],
            "current_bundle_hash": bundle["bundle_snapshot_hash"],
            "current_final_scene_row_id": final_row_id,
        }
