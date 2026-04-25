from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.contracts.bundle import BundleSnapshotHashProjection
from novel_system.db.models import (
    AuthorPreferenceProfile,
    ChapterGoal,
    GenerationPlanningArtifact,
    LongformStructureGuidance,
    SceneBlueprint,
    SceneBundle,
    SceneCard,
    SceneMemory,
    SceneRunState,
)
from novel_system.db.models import StyleObservation
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import compute_bundle_hash_projection
from novel_system.services.resolver import Resolver
from novel_system.services.character_continuity import CHARACTER_CONTRACT_VERSION, build_character_contract_digest
from novel_system.services.scene_digest import scene_card_digest
from novel_system.services.style_profile import STYLE_FEATURE_CONTRACT_VERSION, StyleProfileService
from novel_system.services.writer_review import normalize_chapter_writer_brief, normalize_scene_writer_brief, writer_brief_has_content


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

    def _next_bundle_id(self, scene_id: str, state: SceneRunState) -> tuple[str, int]:
        build_no = (state.bundle_build_count or 0) + 1
        while True:
            bundle_id = f"bundle_{scene_id}_v{build_no}"
            if self.session.get(SceneBundle, bundle_id) is None:
                return bundle_id, build_no
            build_no += 1

    def build(self, scene_id: str, execution_mode: str = "P2", force_rebuild: bool = False) -> dict[str, Any]:
        scene = self.session.get(SceneCard, scene_id)
        chapter = self.session.get(ChapterGoal, scene.chapter_id)
        state = self.session.get(SceneRunState, scene_id)
        previous_memory = self.session.execute(
            select(SceneMemory)
            .join(SceneCard, SceneCard.scene_id == SceneMemory.scene_id)
            .where(
                SceneMemory.chapter_id == scene.chapter_id,
                SceneMemory.active_flag == 1,
                SceneMemory.runtime_eligible == 1,
                SceneCard.trashed_flag == 0,
                SceneCard.scene_seq < scene.scene_seq,
            )
            .order_by(SceneCard.scene_seq.desc(), SceneMemory.created_at.desc())
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
            "scene_card": scene_card_digest(scene),
        }
        chapter_writer_brief = normalize_chapter_writer_brief(chapter.writer_brief_json)
        if writer_brief_has_content(chapter_writer_brief):
            source_version_refs["chapter_writer_brief"] = chapter.chapter_id
            ordered_injections.append(
                {
                    "slot": "chapter_writer_brief",
                    "ref_id": chapter.chapter_id,
                    "digest_key": "chapter_writer_brief",
                }
            )
            inline_digests["chapter_writer_brief"] = json.dumps(
                chapter_writer_brief,
                ensure_ascii=False,
                sort_keys=True,
            )
        scene_writer_brief = normalize_scene_writer_brief(scene.writer_brief_json)
        if writer_brief_has_content(scene_writer_brief):
            source_version_refs["scene_writer_brief"] = scene.scene_id
            ordered_injections.append(
                {
                    "slot": "scene_writer_brief",
                    "ref_id": scene.scene_id,
                    "digest_key": "scene_writer_brief",
                }
            )
            inline_digests["scene_writer_brief"] = json.dumps(
                scene_writer_brief,
                ensure_ascii=False,
                sort_keys=True,
            )

        scene_blueprint = self.session.execute(
            select(SceneBlueprint)
            .where(SceneBlueprint.scene_id == scene.scene_id, SceneBlueprint.status.in_(("accepted", "draft")))
            .order_by(SceneBlueprint.created_at.desc(), SceneBlueprint.row_id.desc())
        ).scalars().first()
        if scene_blueprint is not None:
            source_version_refs["scene_blueprint_row_id"] = scene_blueprint.row_id
            ordered_injections.append(
                {
                    "slot": "scene_blueprint",
                    "ref_id": scene_blueprint.row_id,
                    "digest_key": "scene_blueprint",
                }
            )
            inline_digests["scene_blueprint"] = json.dumps(
                scene_blueprint.blueprint_json or {},
                ensure_ascii=False,
                sort_keys=True,
            )

        character_pressure = self._latest_planning_artifact(
            artifact_type="character_pressure_blueprint",
            object_type="scene",
            object_id=scene.scene_id,
        )
        if character_pressure is not None:
            source_version_refs["character_pressure_artifact_row_id"] = character_pressure.row_id
            ordered_injections.append(
                {
                    "slot": "character_pressure",
                    "ref_id": character_pressure.row_id,
                    "digest_key": "character_pressure",
                }
            )
            inline_digests["character_pressure"] = json.dumps(
                character_pressure.payload_json or {},
                ensure_ascii=False,
                sort_keys=True,
            )

        chapter_architecture = self._latest_planning_artifact(
            artifact_type="chapter_story_architecture",
            object_type="chapter",
            object_id=scene.chapter_id,
        )
        if chapter_architecture is not None:
            source_version_refs["chapter_story_architecture_artifact_row_id"] = chapter_architecture.row_id
            ordered_injections.append(
                {
                    "slot": "chapter_story_architecture",
                    "ref_id": chapter_architecture.row_id,
                    "digest_key": "chapter_story_architecture",
                }
            )
            inline_digests["chapter_story_architecture"] = json.dumps(
                chapter_architecture.payload_json or {},
                ensure_ascii=False,
                sort_keys=True,
            )

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

        character_contract = build_character_contract_digest(
            pov_character_id=scene.pov_character_id,
            onstage_character_ids=scene.onstage_chars_json,
            voice_profile_content=voice_profile.content if voice_profile else None,
            relation_profile_content=relation_profile.content if relation_profile else None,
        )
        if character_contract:
            source_version_refs["character_contract"] = CHARACTER_CONTRACT_VERSION
            ordered_injections.append(
                {
                    "slot": "character_contract",
                    "ref_id": CHARACTER_CONTRACT_VERSION,
                    "digest_key": "character_contract",
                }
            )
            inline_digests["character_contract"] = character_contract

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

        narrative_patterns = self.resolver.resolve_active_narrative_patterns(self.session, scene)
        if narrative_patterns:
            narrative_ids = [row.narrative_pattern_id for row in narrative_patterns]
            source_version_refs["narrative_pattern_ids"] = narrative_ids
            ordered_injections.append(
                {
                    "slot": "narrative_patterns",
                    "ref_id": narrative_ids[0],
                    "digest_key": "narrative_pattern",
                }
            )
            inline_digests["narrative_pattern"] = self._combined_text(narrative_patterns, "content")

        calibration_lines = self.resolver.resolve_active_calibration_lines(self.session, scene)
        if calibration_lines:
            calibration_ids = [row.calibration_line_id for row in calibration_lines]
            source_version_refs["calibration_line_ids"] = calibration_ids
            ordered_injections.append(
                {"slot": "calibration_lines", "ref_id": calibration_ids[0], "digest_key": "calibration_line"}
            )
            inline_digests["calibration_line"] = self._combined_text(calibration_lines, "text")

        style_profile = StyleProfileService.build_profile(
            style_rules=style_rules,
            style_observations=style_observations,
            banned_rule_clusters=banned_rule_clusters,
            calibration_lines=calibration_lines,
            voice_profile=voice_profile,
        )
        if style_profile:
            source_version_refs["style_profile_contract"] = STYLE_FEATURE_CONTRACT_VERSION
            ordered_injections.append(
                {
                    "slot": "style_profile",
                    "ref_id": STYLE_FEATURE_CONTRACT_VERSION,
                    "digest_key": "style_profile",
                }
            )
            inline_digests["style_profile"] = StyleProfileService.render_profile_digest(style_profile)

        author_preference_profile = self._approved_runtime_author_preference_profile()
        if author_preference_profile is not None:
            source_version_refs["author_preference_profile_id"] = author_preference_profile.profile_id
            source_version_refs["author_preference_profile_updated_at"] = author_preference_profile.updated_at
            ordered_injections.append(
                {
                    "slot": "author_preference_profile",
                    "ref_id": author_preference_profile.profile_id,
                    "digest_key": "author_preference_profile",
                }
            )
            inline_digests["author_preference_profile"] = json.dumps(
                {
                    "profile_id": author_preference_profile.profile_id,
                    "kind": "approved_author_preference_profile",
                    "summary": author_preference_profile.summary_json or {},
                },
                ensure_ascii=False,
                sort_keys=True,
            )

        longform_guidance = self._approved_runtime_longform_guidance(scene)
        if longform_guidance:
            guidance_ids = [row.guidance_id for row in longform_guidance]
            source_version_refs["longform_structure_guidance_ids"] = guidance_ids
            source_version_refs["longform_structure_guidance_updated_at"] = [
                row.updated_at for row in longform_guidance
            ]
            ordered_injections.append(
                {
                    "slot": "longform_structure_guidance",
                    "ref_id": guidance_ids[0],
                    "digest_key": "longform_structure_guidance",
                }
            )
            inline_digests["longform_structure_guidance"] = json.dumps(
                [
                    {
                        "guidance_id": row.guidance_id,
                        "scope_type": row.scope_type,
                        "scope_ref_id": row.scope_ref_id,
                        "content": row.content,
                        "source_review_id": row.source_review_id,
                    }
                    for row in longform_guidance
                ],
                ensure_ascii=False,
                sort_keys=True,
            )

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
        bundle_id, build_count = self._next_bundle_id(scene.scene_id, state)
        snapshot = projection.model_dump(mode="json")
        snapshot["scene_id"] = scene.scene_id
        snapshot["chapter_id"] = scene.chapter_id

        bundle = SceneBundle(
            bundle_id=bundle_id,
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            execution_mode=execution_mode,
            bundle_snapshot_hash=bundle_hash,
            frozen_snapshot_json=snapshot,
        )
        self.session.add(bundle)

        state.current_bundle_id = bundle_id
        state.current_bundle_hash = bundle_hash
        state.bundle_build_count = build_count
        state.scene_status = "bundle_built"
        self.session.flush()

        return {"bundle_id": bundle_id, "bundle_snapshot_hash": bundle_hash, "snapshot": snapshot}

    def _latest_planning_artifact(
        self,
        *,
        artifact_type: str,
        object_type: str,
        object_id: str,
    ) -> GenerationPlanningArtifact | None:
        return self.session.execute(
            select(GenerationPlanningArtifact)
            .where(
                GenerationPlanningArtifact.artifact_type == artifact_type,
                GenerationPlanningArtifact.object_type == object_type,
                GenerationPlanningArtifact.object_id == object_id,
                GenerationPlanningArtifact.status == "active",
            )
            .order_by(GenerationPlanningArtifact.created_at.desc(), GenerationPlanningArtifact.row_id.desc())
        ).scalars().first()

    def _approved_runtime_author_preference_profile(self) -> AuthorPreferenceProfile | None:
        return self.session.execute(
            select(AuthorPreferenceProfile)
            .where(
                AuthorPreferenceProfile.scope_type == "global",
                AuthorPreferenceProfile.scope_ref_id == "global",
                AuthorPreferenceProfile.status == "approved",
                AuthorPreferenceProfile.runtime_eligible == 1,
            )
            .order_by(AuthorPreferenceProfile.updated_at.desc(), AuthorPreferenceProfile.profile_id.desc())
        ).scalars().first()

    def _approved_runtime_longform_guidance(self, scene: SceneCard) -> list[LongformStructureGuidance]:
        scope_pairs = {
            ("global", "global"),
            ("chapter", scene.chapter_id),
            ("scene", scene.scene_id),
        }
        character_ids = {item for item in [scene.pov_character_id, *(scene.onstage_chars_json or [])] if item}
        scope_pairs.update(("character", character_id) for character_id in character_ids)
        rows = self.session.execute(
            select(LongformStructureGuidance)
            .where(
                LongformStructureGuidance.status == "approved",
                LongformStructureGuidance.runtime_eligible == 1,
            )
            .order_by(LongformStructureGuidance.created_at.asc(), LongformStructureGuidance.guidance_id.asc())
        ).scalars().all()
        return [row for row in rows if (row.scope_type, row.scope_ref_id) in scope_pairs]
