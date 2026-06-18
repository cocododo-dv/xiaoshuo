"""Tension curve and scene function tags — blueprint §10.

Provides:
- Tension target validation (scene declares 0-10 target, QC checks alignment)
- Function tag vocabulary and adjacent constraint checking
- Pacing parameter mapping (tension level → writing style guidance)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import ChapterGoal, SceneCard


FUNCTION_TAGS = (
    "advance",     # 推进：情节向前推动
    "deepen",      # 深化：角色关系/心理加深
    "reveal",      # 揭示：信息暴露或秘密揭开
    "breathe",     # 呼吸：节奏放慢、日常化、情感沉淀
    "foreshadow",  # 铺垫：为后续埋线索
    "turn",        # 转折：情势/认知/关系反转
)

TENSION_WRITING_PARAMS: dict[str, dict[str, Any]] = {
    "low": {
        "range": (1, 3),
        "guidance": "长段描写、日常对话、环境渲染、内心独白，节奏放慢。",
        "sentence_style": "long descriptive paragraphs, slow pace",
    },
    "medium": {
        "range": (4, 6),
        "guidance": "对话驱动、信息密度提高、暗流涌动。",
        "sentence_style": "dialogue-driven, rising information density",
    },
    "high": {
        "range": (7, 9),
        "guidance": "短句为主、快速切换、动作密集、省略非必要描写。",
        "sentence_style": "short sentences, rapid cuts, action-dense",
    },
    "extreme": {
        "range": (10, 10),
        "guidance": "极致压缩，每个字指向核心冲突。",
        "sentence_style": "maximum compression, every word points to core conflict",
    },
}


@dataclass(slots=True)
class TensionViolation:
    scene_id: str
    violation_type: str
    message: str


@dataclass(slots=True)
class TensionReport:
    chapter_id: str
    violations: list[TensionViolation] = field(default_factory=list)
    scene_count: int = 0
    tagged_count: int = 0
    tension_set_count: int = 0


def tension_level_label(tension: int) -> str:
    if tension <= 3:
        return "low"
    if tension <= 6:
        return "medium"
    if tension <= 9:
        return "high"
    return "extreme"


def tension_writing_guidance(tension: int) -> str:
    label = tension_level_label(tension)
    return TENSION_WRITING_PARAMS[label]["guidance"]


def get_scene_tension(scene: SceneCard) -> int | None:
    brief = scene.writer_brief_json or {}
    val = brief.get("tension_target")
    if val is not None:
        try:
            return max(0, min(10, int(val)))
        except (ValueError, TypeError):
            pass
    return None


def get_scene_function_tag(scene: SceneCard) -> str | None:
    brief = scene.writer_brief_json or {}
    tag = brief.get("function_tag")
    if isinstance(tag, str) and tag in FUNCTION_TAGS:
        return tag
    return None


class TensionCurveService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def validate_chapter(self, chapter_id: str) -> TensionReport:
        """Check a chapter's scenes for tension/tag issues."""
        scenes = list(self.session.execute(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
            .order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all())

        report = TensionReport(chapter_id=chapter_id, scene_count=len(scenes))
        tags: list[tuple[str, str | None]] = []

        for scene in scenes:
            tension = get_scene_tension(scene)
            tag = get_scene_function_tag(scene)
            if tension is not None:
                report.tension_set_count += 1
            if tag is not None:
                report.tagged_count += 1
            tags.append((scene.scene_id, tag))

        report.violations.extend(self._check_adjacent_tags(tags))
        report.violations.extend(self._check_tension_monotony(scenes))
        return report

    def format_tension_prompt(self, scene: SceneCard) -> str | None:
        """Generate a tension-aware writing guidance section for prompt injection."""
        tension = get_scene_tension(scene)
        tag = get_scene_function_tag(scene)
        if tension is None and tag is None:
            return None

        lines = ["## Tension & Pacing Constraint"]
        if tension is not None:
            label = tension_level_label(tension)
            lines.append(f"Target tension: {tension}/10 ({label})")
            lines.append(f"Writing style: {tension_writing_guidance(tension)}")
        if tag is not None:
            lines.append(f"Scene function: {tag}")
        return "\n".join(lines)

    @staticmethod
    def _check_adjacent_tags(tags: list[tuple[str, str | None]]) -> list[TensionViolation]:
        """Blueprint §10: no two consecutive scenes with the same function tag."""
        violations: list[TensionViolation] = []
        for i in range(1, len(tags)):
            sid, tag = tags[i]
            if tag is None:
                continue
            if tags[i - 1][1] == tag:
                violations.append(TensionViolation(
                    scene_id=sid,
                    violation_type="adjacent_tag_repeat",
                    message=f"2 consecutive scenes with function tag '{tag}' — vary the rhythm.",
                ))
        return violations

    @staticmethod
    def _check_tension_monotony(scenes: list[SceneCard]) -> list[TensionViolation]:
        """Flag 5+ consecutive scenes with same tension level."""
        violations: list[TensionViolation] = []
        levels: list[tuple[str, str | None]] = []
        for scene in scenes:
            t = get_scene_tension(scene)
            levels.append((scene.scene_id, tension_level_label(t) if t is not None else None))

        run_count = 1
        for i in range(1, len(levels)):
            sid, level = levels[i]
            if level is not None and level == levels[i - 1][1]:
                run_count += 1
                if run_count >= 5:
                    violations.append(TensionViolation(
                        scene_id=sid,
                        violation_type="tension_monotony",
                        message=f"{run_count} consecutive scenes at tension level '{level}' — rhythm flattening.",
                    ))
            else:
                run_count = 1

        return violations

    def validate_chapter_hooks(self, chapter_id: str) -> list[TensionViolation]:
        """Blueprint §10: chapter-end hook type classification + adjacency constraint."""
        scenes = list(self.session.execute(
            select(SceneCard)
            .where(
                SceneCard.chapter_id == chapter_id,
                SceneCard.trashed_flag == 0,
                SceneCard.is_chapter_last == 1,
            )
            .order_by(SceneCard.scene_seq.asc())
        ).scalars().all())
        if not scenes:
            return []

        violations: list[TensionViolation] = []
        for scene in scenes:
            hook = scene.hook or ""
            brief = scene.writer_brief_json or {}
            hook_type = brief.get("hook_type")
            if not hook_type and hook:
                hook_type = classify_hook_type(hook)
            if not hook_type:
                violations.append(TensionViolation(
                    scene_id=scene.scene_id,
                    violation_type="missing_hook_type",
                    message="Chapter-ending scene has no classified hook type.",
                ))
        return violations


HOOK_TYPES = ("suspense", "reversal", "emotion", "info_gap")

HOOK_TYPE_KEYWORDS: dict[str, list[str]] = {
    "suspense": ["悬念", "未知", "危险", "秘密", "到底", "结局", "命运", "等待"],
    "reversal": ["反转", "出乎", "意料", "突然", "颠覆", "真相", "发现", "原来"],
    "emotion": ["心痛", "不舍", "温暖", "泪", "感动", "失落", "喜悦", "悲伤"],
    "info_gap": ["信息差", "不知道", "隐瞒", "谎言", "误解", "还不知道", "信以为真"],
}


def classify_hook_type(hook_text: str) -> str:
    """Classify a chapter-end hook into one of 4 types by keyword matching."""
    if not hook_text:
        return "suspense"
    scores: dict[str, int] = {ht: 0 for ht in HOOK_TYPES}
    for hook_type, keywords in HOOK_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in hook_text:
                scores[hook_type] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "suspense"


def check_adjacent_hook_types(hook_types: list[str]) -> list[str]:
    """Blueprint §10: adjacent chapters should not use the same hook type."""
    warnings: list[str] = []
    for i in range(1, len(hook_types)):
        if hook_types[i] == hook_types[i - 1]:
            warnings.append(
                f"Chapters {i} and {i + 1} both use hook type '{hook_types[i]}' — vary for rhythm."
            )
    return warnings
