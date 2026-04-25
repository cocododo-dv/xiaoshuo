from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import SceneBlueprint, SceneCard
from novel_system.services.resolver import Resolver
from novel_system.services.writer_review import normalize_scene_writer_brief


class SceneRunPreflightService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.resolver = Resolver()

    def build(self, scene: SceneCard, chapter_state: dict[str, Any]) -> dict[str, Any]:
        blocking_items = self._blocking_items(scene)
        warning_items = self._warning_items(scene)
        context_items = self._context_items(chapter_state)
        missing_dependencies = self._missing_dependencies(scene)
        create_actions = self._create_actions(missing_dependencies)
        constraint_conflicts = self._constraint_conflicts(scene)

        if blocking_items or constraint_conflicts:
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
            "missing_dependencies": missing_dependencies,
            "create_actions": create_actions,
            "constraint_conflicts": constraint_conflicts,
        }

    def _missing_dependencies(self, scene: SceneCard) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        voice_profile_id = self.resolver.resolve_voice_profile_id(scene)
        if voice_profile_id and self.resolver.resolve_active_voice_profile(self.session, scene) is None:
            items.append(
                {
                    "dependency_type": "voice_card",
                    "lineage_key": voice_profile_id,
                    "character_id": scene.pov_character_id,
                    "blocking_code": "VOICE_PROFILE_MISSING",
                }
            )

        relation_profile_id = self.resolver.resolve_relation_profile_id(scene)
        if relation_profile_id and self.resolver.resolve_active_relation_profile(self.session, scene) is None:
            character_ids = list(dict.fromkeys(scene.onstage_chars_json or []))
            items.append(
                {
                    "dependency_type": "relation_card",
                    "lineage_key": relation_profile_id,
                    "character_ids": character_ids[:2],
                    "blocking_code": "RELATION_PROFILE_MISSING",
                }
            )

        return items

    def _create_actions(self, missing_dependencies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for dependency in missing_dependencies:
            dependency_type = dependency.get("dependency_type")
            lineage_key = str(dependency.get("lineage_key") or "")
            if dependency_type == "voice_card":
                character_id = str(dependency.get("character_id") or "")
                actions.append(
                    {
                        "action": "create_minimal_voice_card",
                        "lineage_key": lineage_key,
                        "label": f"Create voice card for {character_id}",
                        "review": {
                            "item_type": "voice_profile",
                            "candidate_payload_json": {
                                "lineage_key": lineage_key,
                                "character_id": character_id,
                                "content": f"{character_id}: keep speech and interiority consistent.",
                                "source": "scene_run_preflight",
                            },
                        },
                    }
                )
            elif dependency_type == "relation_card":
                character_ids = [str(item) for item in dependency.get("character_ids", [])]
                actions.append(
                    {
                        "action": "create_minimal_relation_card",
                        "lineage_key": lineage_key,
                        "label": f"Create relation card for {' / '.join(character_ids)}",
                        "review": {
                            "item_type": "relation_profile",
                            "candidate_payload_json": {
                                "lineage_key": lineage_key,
                                "character_ids": character_ids,
                                "content": "Define the current emotional pressure, information asymmetry, and trust boundary.",
                                "source": "scene_run_preflight",
                            },
                        },
                    }
                )
        return actions

    def _constraint_conflicts(self, scene: SceneCard) -> list[dict[str, Any]]:
        forbidden_terms = self._constraint_terms(scene.forbidden_text)
        if not forbidden_terms:
            return []
        positive_sources = self._positive_constraint_sources(scene)
        conflicts: list[dict[str, Any]] = []
        for term in forbidden_terms:
            for source_name, source_text in positive_sources:
                if term in source_text:
                    conflicts.append(
                        {
                            "term": term,
                            "required_source": source_name,
                            "forbidden_source": "scene_card.forbidden_text",
                            "severity": "blocking",
                            "human_readable_reason": "场景要求使用该词，但禁用规则又禁止该词；请先选择保留或替换。",
                        }
                    )
                    break
        return conflicts

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


    @staticmethod
    def _constraint_terms(text: Any) -> list[str]:
        if not isinstance(text, str) or not text.strip():
            return []
        return [term.strip() for term in re.split(r"[,，、;；\n]+", text) if len(term.strip()) >= 2]


    @staticmethod
    def _positive_constraint_sources(scene: SceneCard) -> list[tuple[str, str]]:
        sources: list[tuple[str, str]] = []
        for name, value in (
            ("scene_card.must_include_text", scene.must_include_text),
            ("scene_card.hook", scene.hook),
            ("scene_card.exit_change", scene.exit_change),
            ("scene_card.scene_goal", scene.scene_goal),
        ):
            if isinstance(value, str) and value.strip():
                sources.append((name, value))
        beats = scene.beats_json if isinstance(scene.beats_json, list) else []
        for index, beat in enumerate(beats):
            if isinstance(beat, str) and beat.strip():
                sources.append((f"scene_card.beats_json[{index}]", beat))
        return sources

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
        latest_blueprint = self.session.execute(
            select(SceneBlueprint)
            .where(SceneBlueprint.scene_id == scene.scene_id, SceneBlueprint.status.in_(("accepted", "draft")))
            .order_by(SceneBlueprint.created_at.desc(), SceneBlueprint.row_id.desc())
        ).scalars().first()
        if latest_blueprint is None:
            items.append(
                {
                    "code": "SCENE_BLUEPRINT_MISSING",
                    "title": "Scene literary blueprint is missing",
                    "detail": "The run can auto-generate it, but the author should review the scene intent before drafting.",
                    "technical_hint": "POST /api/v1/scenes/{scene_id}/literary-blueprint",
                }
            )
        brief = normalize_scene_writer_brief(scene.writer_brief_json)
        missing_intent = [
            key
            for key in ("choice_under_pressure", "power_shift", "new_information", "emotional_turn", "image_anchor", "reader_aftertaste")
            if not brief.get(key)
        ]
        if missing_intent:
            items.append(
                {
                    "code": "SCENE_LITERARY_INTENT_INCOMPLETE",
                    "title": "Scene literary intent is incomplete",
                    "detail": "Consider filling the v2 writer brief fields before generation: " + ", ".join(missing_intent),
                    "technical_hint": "scene_card.writer_brief_json",
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
