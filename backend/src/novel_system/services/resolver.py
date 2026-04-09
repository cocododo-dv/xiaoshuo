from __future__ import annotations

from novel_system.db.models import SceneCard


class Resolver:
    def resolve_relation_id(self, scene: SceneCard) -> str | None:
        if scene.resolved_relation_id:
            return scene.resolved_relation_id
        chars = list(dict.fromkeys(scene.onstage_chars_json or []))
        if len(chars) == 2:
            return f"REL_{chars[0]}_{chars[1]}"
        return None

    def resolve_voice_id(self, scene: SceneCard) -> str | None:
        if scene.pov_character_id:
            return f"VOICE_{scene.pov_character_id}"
        return None
