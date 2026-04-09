from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import RelationProfile, SceneCard, VoiceProfile


class Resolver:
    def resolve_relation_profile_id(self, scene: SceneCard) -> str | None:
        if scene.resolved_relation_id:
            return scene.resolved_relation_id
        chars = list(dict.fromkeys(scene.onstage_chars_json or []))
        if len(chars) == 2:
            return f"REL_{chars[0]}_{chars[1]}"
        return None

    def resolve_voice_profile_id(self, scene: SceneCard) -> str | None:
        if scene.pov_character_id:
            return f"VOICE_{scene.pov_character_id}"
        return None

    def resolve_active_relation_profile(self, session: Session, scene: SceneCard) -> RelationProfile | None:
        relation_profile_id = self.resolve_relation_profile_id(scene)
        if relation_profile_id is None:
            return None
        return session.execute(
            select(RelationProfile)
            .where(
                RelationProfile.relation_profile_id == relation_profile_id,
                RelationProfile.active_flag == 1,
            )
            .order_by(RelationProfile.version.desc())
        ).scalars().first()

    def resolve_active_voice_profile(self, session: Session, scene: SceneCard) -> VoiceProfile | None:
        voice_profile_id = self.resolve_voice_profile_id(scene)
        if voice_profile_id is None:
            return None
        return session.execute(
            select(VoiceProfile)
            .where(
                VoiceProfile.voice_profile_id == voice_profile_id,
                VoiceProfile.active_flag == 1,
            )
            .order_by(VoiceProfile.version.desc())
        ).scalars().first()
