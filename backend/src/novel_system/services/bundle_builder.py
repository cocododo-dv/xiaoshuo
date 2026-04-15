from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.contracts.bundle import BundleSnapshotHashProjection
from novel_system.db.models import ChapterGoal, SceneBundle, SceneCard, SceneMemory, SceneRunState
from novel_system.db.models import StyleObservation
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import compute_bundle_hash_projection
from novel_system.services.resolver import Resolver


class BundleBuilder:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.resolver = Resolver()

    @staticmethod
    def _single_or_list(values: list[str]) -> str | list[str]:
        return values[0] if len(values) == 1 else values

    @staticmethod
    def _combined_text(rows: list[Any], text_field: str) -> str:
        return "\n\n".join(str(getattr(row, text_field)) for row in rows if getattr(row, text_field, None))

    def build(self, scene_id: str, execution_mode: str = "P2", force_rebuild: bool = False) -> dict[str, Any]:
        scene = self.session.get(SceneCard, scene_id)
        chapter = self.session.get(ChapterGoal, scene.chapter_id)
        state = self.session.get(SceneRunState, scene_id)
        previous_memory = self.session.execute(
            select(SceneMemory)
            .where(SceneMemory.chapter_id == scene.chapter_id, SceneMemory.active_flag == 1)
            .order_by(SceneMemory.created_at.desc())
        ).scalars().first()

        source_version_refs = {
            "chapter_goal": chapter.chapter_id,
            "scene_card": scene.scene_id,
        }
        ordered_injections = [
            {"slot": "chapter_goal", "ref_id": chapter.chapter_id, "digest_key": "chapter_goal"},
            {"slot": "scene_card", "ref_id": scene.scene_id, "digest_key": "scene_card"},
        ]
        inline_digests = {
            "chapter_goal": chapter.chapter_goal,
            "scene_card": scene.scene_goal,
        }

        voice_profile_id = self.resolver.resolve_voice_profile_id(scene)
        voice_profile = self.resolver.resolve_active_voice_profile(self.session, scene)
        if voice_profile_id and voice_profile is None:
            raise DomainError(
                "BUNDLE_SOURCE_MISSING",
                f"active voice profile missing for {voice_profile_id}",
                status_code=409,
            )
        if voice_profile:
            source_version_refs["voice_profile_id"] = voice_profile.voice_profile_id
            source_version_refs["voice_profile_row_id"] = voice_profile.row_id
            source_version_refs["voice_profile_version"] = voice_profile.version
            ordered_injections.append(
                {"slot": "pov_voice", "ref_id": voice_profile.voice_profile_id, "digest_key": "voice_card"}
            )
            inline_digests["voice_card"] = voice_profile.content

        relation_profile_id = self.resolver.resolve_relation_profile_id(scene)
        relation_profile = self.resolver.resolve_active_relation_profile(self.session, scene)
        if relation_profile_id and relation_profile is None:
            raise DomainError(
                "BUNDLE_SOURCE_MISSING",
                f"active relation profile missing for {relation_profile_id}",
                status_code=409,
            )
        if relation_profile:
            source_version_refs["relation_profile_id"] = relation_profile.relation_profile_id
            source_version_refs["relation_profile_row_id"] = relation_profile.row_id
            source_version_refs["relation_profile_version"] = relation_profile.version
            ordered_injections.append(
                {"slot": "relation", "ref_id": relation_profile.relation_profile_id, "digest_key": "relation_card"}
            )
            inline_digests["relation_card"] = relation_profile.content
        if previous_memory:
            source_version_refs["scene_memory_prev"] = previous_memory.scene_id
            ordered_injections.append(
                {"slot": "prev_scene_memory", "ref_id": previous_memory.scene_id, "digest_key": "scene_memory"}
            )
            inline_digests["scene_memory"] = previous_memory.content

        style_rules = self.resolver.resolve_active_style_rules(self.session, scene)
        if style_rules:
            style_rule_ids = [row.style_rule_set_id for row in style_rules]
            source_version_refs["style_rule_set_id"] = self._single_or_list(style_rule_ids)
            ordered_injections.append(
                {"slot": "style_rules", "ref_id": style_rule_ids[0], "digest_key": "style_rule"}
            )
            inline_digests["style_rule"] = self._combined_text(style_rules, "content")

        style_observations = self.session.execute(
            select(StyleObservation)
            .where(
                StyleObservation.active_flag == 1,
                StyleObservation.runtime_eligible == 1,
                self.resolver._scoped_clause(StyleObservation, scene),
            )
            .order_by(StyleObservation.created_at.asc(), StyleObservation.row_id.asc())
        ).scalars().all()
        if style_observations:
            style_observation_ids = [row.style_observation_id for row in style_observations]
            source_version_refs["style_observation_ids"] = style_observation_ids
            ordered_injections.append(
                {
                    "slot": "style_observations",
                    "ref_id": style_observation_ids[0],
                    "digest_key": "style_observation",
                }
            )
            inline_digests["style_observation"] = self._combined_text(style_observations, "text")

        banned_rule_clusters = self.resolver.resolve_active_banned_rule_clusters(self.session, scene)
        if banned_rule_clusters:
            banned_ids = [row.banned_cluster_id for row in banned_rule_clusters]
            source_version_refs["banned_cluster_id"] = self._single_or_list(banned_ids)
            ordered_injections.append(
                {"slot": "banned_rules", "ref_id": banned_ids[0], "digest_key": "banned_rule"}
            )
            inline_digests["banned_rule"] = self._combined_text(banned_rule_clusters, "content")

        calibration_lines = self.resolver.resolve_active_calibration_lines(self.session, scene)
        if calibration_lines:
            calibration_ids = [row.calibration_line_id for row in calibration_lines]
            source_version_refs["calibration_line_ids"] = calibration_ids
            ordered_injections.append(
                {"slot": "calibration_lines", "ref_id": calibration_ids[0], "digest_key": "calibration_line"}
            )
            inline_digests["calibration_line"] = self._combined_text(calibration_lines, "text")

        world_rules = self.resolver.resolve_active_world_rules(self.session, scene)
        if world_rules:
            ordered_injections.append(
                {"slot": "world_rules", "ref_id": world_rules[0].world_rule_id, "digest_key": "world_rule"}
            )
            inline_digests["world_rule"] = self._combined_text(world_rules, "content")

        open_foreshadows = self.resolver.resolve_open_foreshadow_trackers(self.session, scene)
        if open_foreshadows:
            ordered_injections.append(
                {"slot": "foreshadow", "ref_id": open_foreshadows[0].foreshadow_id, "digest_key": "foreshadow"}
            )
            inline_digests["foreshadow"] = self._combined_text(open_foreshadows, "text")

        scene_summary = self.resolver.resolve_scene_summary(self.session, scene)
        if scene_summary:
            source_version_refs["scene_summary_id"] = scene_summary.scene_id
            ordered_injections.append(
                {"slot": "scene_summary", "ref_id": scene_summary.scene_id, "digest_key": "scene_summary"}
            )
            inline_digests["scene_summary"] = scene_summary.content

        chapter_summary = self.resolver.resolve_chapter_summary(self.session, scene)
        if chapter_summary:
            source_version_refs["chapter_summary_id"] = chapter_summary.chapter_id
            ordered_injections.append(
                {"slot": "chapter_summary", "ref_id": chapter_summary.chapter_id, "digest_key": "chapter_summary"}
            )
            inline_digests["chapter_summary"] = chapter_summary.content

        projection = BundleSnapshotHashProjection(
            contract_version="BSHASH_v1",
            stage_allowlist_name="bundle_build_allowlist_v1",
            source_version_refs=source_version_refs,
            resolved_ref_ids={
                "relation_ids": [relation_profile.relation_profile_id] if relation_profile else [],
                "world_rule_ids": [row.world_rule_id for row in world_rules],
                "open_foreshadow_ids": [row.foreshadow_id for row in open_foreshadows],
            },
            ordered_injections=ordered_injections,
            inline_digests=inline_digests,
        )
        bundle_hash = compute_bundle_hash_projection(projection)
        bundle_id = state.current_bundle_id or f"bundle_{scene.scene_id}"
        snapshot = projection.model_dump(mode="json")
        snapshot["scene_id"] = scene.scene_id
        snapshot["chapter_id"] = scene.chapter_id

        bundle = self.session.get(SceneBundle, bundle_id)
        if bundle is None:
            bundle = SceneBundle(
                bundle_id=bundle_id,
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                execution_mode=execution_mode,
                bundle_snapshot_hash=bundle_hash,
                frozen_snapshot_json=snapshot,
            )
            self.session.add(bundle)
        else:
            bundle.bundle_snapshot_hash = bundle_hash
            bundle.frozen_snapshot_json = snapshot

        state.current_bundle_id = bundle_id
        state.current_bundle_hash = bundle_hash
        state.bundle_build_count += 1
        state.scene_status = "bundle_built"
        self.session.flush()

        return {"bundle_id": bundle_id, "bundle_snapshot_hash": bundle_hash, "snapshot": snapshot}
