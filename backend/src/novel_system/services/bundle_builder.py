from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.contracts.bundle import BundleSnapshotHashProjection
from novel_system.db.models import ChapterGoal, SceneBundle, SceneCard, SceneMemory, SceneRunState
from novel_system.services.hash_engine import compute_bundle_hash_projection
from novel_system.services.resolver import Resolver


class BundleBuilder:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.resolver = Resolver()

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

        voice_id = self.resolver.resolve_voice_id(scene)
        relation_id = self.resolver.resolve_relation_id(scene)
        if voice_id:
            source_version_refs["voice_id"] = voice_id
            ordered_injections.append({"slot": "pov_voice", "ref_id": voice_id, "digest_key": "voice_card"})
            inline_digests["voice_card"] = f"voice profile for {scene.pov_character_id}"
        if relation_id:
            source_version_refs["relation_id"] = relation_id
            ordered_injections.append({"slot": "relation", "ref_id": relation_id, "digest_key": "relation_card"})
            inline_digests["relation_card"] = "relation context resolved"
        if previous_memory:
            source_version_refs["scene_memory_prev"] = previous_memory.scene_id
            ordered_injections.append(
                {"slot": "prev_scene_memory", "ref_id": previous_memory.scene_id, "digest_key": "scene_memory"}
            )
            inline_digests["scene_memory"] = previous_memory.content

        projection = BundleSnapshotHashProjection(
            contract_version="BSHASH_v1",
            stage_allowlist_name="bundle_build_allowlist_v1",
            source_version_refs=source_version_refs,
            resolved_ref_ids={
                "relation_ids": [relation_id] if relation_id else [],
                "world_rule_ids": [],
                "open_foreshadow_ids": [],
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
