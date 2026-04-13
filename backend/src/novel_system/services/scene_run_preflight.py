from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from novel_system.db.models import SceneCard
from novel_system.services.resolver import Resolver


class SceneRunPreflightService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.resolver = Resolver()

    def build(self, scene: SceneCard, chapter_state: dict[str, Any]) -> dict[str, Any]:
        blocking_items = self._blocking_items(scene)
        warning_items = self._warning_items(scene)
        context_items = self._context_items(chapter_state)

        if blocking_items:
            overall_status = "blocked"
            can_run = False
        elif warning_items or context_items:
            overall_status = "warning"
            can_run = True
        else:
            overall_status = "ready"
            can_run = True

        return {
            "can_run": can_run,
            "overall_status": overall_status,
            "blocking_items": blocking_items,
            "warning_items": warning_items,
            "context_items": context_items,
        }

    def _blocking_items(self, scene: SceneCard) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        voice_profile_id = self.resolver.resolve_voice_profile_id(scene)
        if voice_profile_id and self.resolver.resolve_active_voice_profile(self.session, scene) is None:
            items.append(
                {
                    "code": "VOICE_PROFILE_MISSING",
                    "title": "缺少 POV 声线档案，当前不宜运行场景",
                    "detail": "请先补齐当前 POV 角色的可用声线档案，再执行完整场景运行。",
                    "technical_hint": f"expected active voice profile: {voice_profile_id}",
                }
            )

        relation_profile_id = self.resolver.resolve_relation_profile_id(scene)
        if relation_profile_id and self.resolver.resolve_active_relation_profile(self.session, scene) is None:
            items.append(
                {
                    "code": "RELATION_PROFILE_MISSING",
                    "title": "缺少同场角色关系档案，当前不宜运行场景",
                    "detail": "请先补齐当前同场角色组合的可用关系档案，再执行完整场景运行。",
                    "technical_hint": f"expected active relation profile: {relation_profile_id}",
                }
            )

        return items

    def _warning_items(self, scene: SceneCard) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        if not (scene.scene_goal or "").strip():
            items.append(
                {
                    "code": "SCENE_GOAL_MISSING",
                    "title": "场景目标为空",
                    "detail": "建议先补充这场戏要推进的目标，再执行完整场景运行。",
                    "technical_hint": "scene_card.scene_goal is blank",
                }
            )
        if not (scene.location or "").strip():
            items.append(
                {
                    "code": "SCENE_LOCATION_MISSING",
                    "title": "场景地点为空",
                    "detail": "建议先补充场景地点，让运行结果有更稳定的空间锚点。",
                    "technical_hint": "scene_card.location is blank",
                }
            )
        if not (scene.pov_character_id or "").strip():
            items.append(
                {
                    "code": "SCENE_POV_MISSING",
                    "title": "POV 角色为空",
                    "detail": "建议先明确这场戏的 POV 角色，避免运行结果失去主视角。",
                    "technical_hint": "scene_card.pov_character_id is blank",
                }
            )
        if not list(scene.onstage_chars_json or []):
            items.append(
                {
                    "code": "SCENE_ONSTAGE_CHARACTERS_MISSING",
                    "title": "同场角色列表为空",
                    "detail": "建议先补齐同场角色，让运行时关系与互动上下文更完整。",
                    "technical_hint": "scene_card.onstage_chars_json is empty",
                }
            )
        if not list(scene.beats_json or []):
            items.append(
                {
                    "code": "SCENE_BEATS_MISSING",
                    "title": "场景节拍为空",
                    "detail": "建议先补齐场景 beats，让运行结果更容易贴合预期推进。",
                    "technical_hint": "scene_card.beats_json is empty",
                }
            )

        return items

    def _context_items(self, chapter_state: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        manual_hold_reason = (chapter_state.get("manual_hold_reason") or "").strip()
        if manual_hold_reason:
            items.append(
                {
                    "code": "CHAPTER_MANUAL_HOLD_ACTIVE",
                    "title": "本章已设置人工挂起",
                    "detail": "这不会阻止当前场景运行，但会继续阻止章节级 final aggregate。",
                    "technical_hint": f"manual hold reason: {manual_hold_reason}",
                }
            )

        pending_backfill_count = int(chapter_state.get("chapter_backfill_pending_count") or 0)
        if pending_backfill_count > 0:
            items.append(
                {
                    "code": "CHAPTER_BACKFILL_PENDING",
                    "title": "本章仍有待处理的 staged backfill",
                    "detail": "这不会阻止当前场景运行，但会继续阻止章节级 final aggregate。",
                    "technical_hint": f"pending staged backfill count: {pending_backfill_count}",
                }
            )

        return items
