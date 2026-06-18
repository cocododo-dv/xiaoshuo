"""Controlling idea & theme validation — blueprint §12.

Every project should have a one-sentence controlling idea (主题判断) that anchors
all narrative decisions. This service stores it, validates scene relevance, and
enforces the expression spectrum (显→隐, prefer implicit).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import ChapterGoal, SceneCard, WorkProfile


EXPRESSION_SPECTRUM = (
    ("direct_commentary", "直接议论", "全书最多 1-2 次，留给最高潮"),
    ("dialogue_hint", "对话暗示", "每三四章允许一次"),
    ("action_embodiment", "行动体现", "每章都可以"),
    ("imagery_osmosis", "意象渗透", "自然融入描写"),
    ("structure_mapping", "结构映射", "规划时确定"),
)


@dataclass(slots=True)
class CounterpointEntry:
    character_id: str
    thesis: str
    arc_summary: str


@dataclass(slots=True)
class ThemeRelevanceCheck:
    scene_id: str
    relevant: bool
    connection: str
    suggestion: str


@dataclass(slots=True)
class ThemeHealthReport:
    project_id: str
    controlling_idea: str | None = None
    scene_count: int = 0
    checked_count: int = 0
    irrelevant_scenes: list[str] = field(default_factory=list)
    expression_spectrum_guidance: str = ""


class ThemeAnchorService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_controlling_idea(self, project_id: str) -> str | None:
        profile = self.session.execute(
            select(WorkProfile)
            .where(
                WorkProfile.scope_ref_id == project_id,
                WorkProfile.profile_key == "controlling_idea",
                WorkProfile.status == "active",
            )
        ).scalars().first()
        if profile is None:
            return None
        return (profile.profile_json or {}).get("idea")

    def set_controlling_idea(self, project_id: str, idea: str) -> None:
        profile = self.session.execute(
            select(WorkProfile)
            .where(
                WorkProfile.scope_ref_id == project_id,
                WorkProfile.profile_key == "controlling_idea",
            )
        ).scalars().first()
        if profile is None:
            import uuid
            profile = WorkProfile(
                profile_id=f"wp_ci_{uuid.uuid4().hex[:12]}",
                scope_type="global",
                scope_ref_id=project_id,
                profile_key="controlling_idea",
                display_name="控制性理念",
                status="active",
                profile_json={"idea": idea.strip()[:500]},
            )
            self.session.add(profile)
        else:
            pj = dict(profile.profile_json or {})
            pj["idea"] = idea.strip()[:500]
            profile.profile_json = pj
            profile.status = "active"
        self.session.flush()

    def get_counterpoint_map(self, project_id: str) -> list[CounterpointEntry]:
        profile = self.session.execute(
            select(WorkProfile)
            .where(
                WorkProfile.scope_ref_id == project_id,
                WorkProfile.profile_key == "theme_counterpoint",
                WorkProfile.status == "active",
            )
        ).scalars().first()
        if profile is None:
            return []
        entries = (profile.profile_json or {}).get("entries", [])
        return [
            CounterpointEntry(
                character_id=e.get("character_id", ""),
                thesis=e.get("thesis", ""),
                arc_summary=e.get("arc_summary", ""),
            )
            for e in entries
            if e.get("character_id")
        ]

    def set_counterpoint_map(self, project_id: str, entries: list[CounterpointEntry]) -> None:
        profile = self.session.execute(
            select(WorkProfile)
            .where(
                WorkProfile.scope_ref_id == project_id,
                WorkProfile.profile_key == "theme_counterpoint",
            )
        ).scalars().first()
        payload = {
            "entries": [
                {"character_id": e.character_id, "thesis": e.thesis, "arc_summary": e.arc_summary}
                for e in entries
            ]
        }
        if profile is None:
            import uuid
            profile = WorkProfile(
                profile_id=f"wp_cp_{uuid.uuid4().hex[:12]}",
                scope_type="global",
                scope_ref_id=project_id,
                profile_key="theme_counterpoint",
                display_name="主题对位叙事",
                status="active",
                profile_json=payload,
            )
            self.session.add(profile)
        else:
            profile.profile_json = payload
            profile.status = "active"
        self.session.flush()

    def validate_counterpoint_coverage(
        self,
        project_id: str,
        chapter_id: str,
    ) -> dict[str, Any]:
        """Check which counterpoint characters appear and flag stale ones."""
        counterpoints = self.get_counterpoint_map(project_id)
        if not counterpoints:
            return {"covered": [], "stale": [], "missing_from_chapter": []}

        cp_char_ids = {e.character_id for e in counterpoints}

        scenes_in_chapter = list(self.session.execute(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
        ).scalars().all())
        chapter_chars: set[str] = set()
        for sc in scenes_in_chapter:
            if sc.pov_character_id:
                chapter_chars.add(sc.pov_character_id)
            for c in (sc.onstage_chars_json or []):
                chapter_chars.add(c)

        covered = cp_char_ids & chapter_chars
        missing_from_chapter = cp_char_ids - chapter_chars

        all_chapters = list(self.session.execute(
            select(ChapterGoal.chapter_id)
            .where(ChapterGoal.project_id == project_id)
            .order_by(ChapterGoal.display_order.asc())
        ).scalars().all())

        chapter_idx = all_chapters.index(chapter_id) if chapter_id in all_chapters else len(all_chapters)
        stale: list[str] = []
        for char_id in cp_char_ids:
            last_appearance = None
            for ci in range(chapter_idx - 1, -1, -1):
                ch = all_chapters[ci]
                has_char = self.session.execute(
                    select(SceneCard.scene_id)
                    .where(
                        SceneCard.chapter_id == ch,
                        SceneCard.trashed_flag == 0,
                        (SceneCard.pov_character_id == char_id)
                        | SceneCard.onstage_chars_json.contains(char_id),
                    )
                    .limit(1)
                ).scalars().first()
                if has_char:
                    last_appearance = ci
                    break
            if last_appearance is not None and (chapter_idx - last_appearance) >= 3:
                stale.append(char_id)

        return {
            "covered": sorted(covered),
            "stale": sorted(stale),
            "missing_from_chapter": sorted(missing_from_chapter),
        }

    def check_scene_relevance(
        self,
        scene: SceneCard,
        controlling_idea: str,
    ) -> ThemeRelevanceCheck:
        """Heuristic check: does this scene's goal/exit_change connect to the theme?"""
        idea_lower = controlling_idea.lower()
        idea_keywords = _extract_theme_keywords(idea_lower)

        scene_text = " ".join(filter(None, [
            scene.scene_goal,
            scene.exit_change,
            scene.hook,
            str(scene.writer_brief_json.get("scene_crucible", "")) if scene.writer_brief_json else "",
        ])).lower()

        matches = [kw for kw in idea_keywords if kw in scene_text]
        if matches:
            return ThemeRelevanceCheck(
                scene_id=scene.scene_id,
                relevant=True,
                connection=f"Theme keywords present: {', '.join(matches[:3])}",
                suggestion="",
            )

        cost_terms = ("代价", "牺牲", "失去", "放弃", "选择", "cost", "sacrifice", "lose", "choose")
        has_cost = any(t in scene_text for t in cost_terms)
        if has_cost:
            return ThemeRelevanceCheck(
                scene_id=scene.scene_id,
                relevant=True,
                connection="Scene involves cost/choice (implicit theme pressure)",
                suggestion="",
            )

        return ThemeRelevanceCheck(
            scene_id=scene.scene_id,
            relevant=False,
            connection="No visible theme connection in scene spec",
            suggestion=f"Consider how this scene relates to: '{controlling_idea}'. "
                        "Even breathing scenes should touch the theme through imagery or structure.",
        )

    def validate_chapter_theme_pressure(
        self,
        project_id: str,
        chapter_id: str,
    ) -> ThemeHealthReport:
        """Check all scenes in a chapter for theme relevance."""
        idea = self.get_controlling_idea(project_id)
        report = ThemeHealthReport(
            project_id=project_id,
            controlling_idea=idea,
            expression_spectrum_guidance=self.expression_spectrum_text(),
        )
        if not idea:
            return report

        scenes = list(self.session.execute(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
            .order_by(SceneCard.scene_seq.asc())
        ).scalars().all())
        report.scene_count = len(scenes)

        for scene in scenes:
            check = self.check_scene_relevance(scene, idea)
            report.checked_count += 1
            if not check.relevant:
                report.irrelevant_scenes.append(scene.scene_id)

        return report

    def format_theme_prompt(self, project_id: str) -> str | None:
        """Format controlling idea + counterpoint map as a prompt section."""
        idea = self.get_controlling_idea(project_id)
        if not idea:
            return None
        lines = [
            "## Controlling Idea (全书主题锚)",
            f"'{idea}'",
            "",
            "This scene must connect to this idea — through action, cost, imagery, or structure.",
            "Do NOT state the theme directly in dialogue. Let it emerge through what characters do and sacrifice.",
        ]
        counterpoints = self.get_counterpoint_map(project_id)
        if counterpoints:
            lines.append("")
            lines.append("## Theme Counterpoint — each character embodies the theme differently:")
            for cp in counterpoints:
                lines.append(f"- {cp.character_id}: {cp.thesis} (arc: {cp.arc_summary})")
            lines.append("")
            lines.append(
                "In this scene, express the theme through the POV character's unique "
                "relationship to it. Do NOT homogenize character perspectives."
            )
        return "\n".join(lines)

    @staticmethod
    def expression_spectrum_text() -> str:
        lines = ["Theme expression priority (most hidden → most visible, prefer hidden):"]
        for _, cn_label, frequency in EXPRESSION_SPECTRUM:
            lines.append(f"  - {cn_label}: {frequency}")
        return "\n".join(lines)


    # ------------------------------------------------------------------
    # Blueprint §12: Expression Spectrum Frequency Enforcement
    # ------------------------------------------------------------------

    # Hard frequency caps per expression level (per project lifetime)
    EXPRESSION_FREQUENCY_CAPS: dict[str, int | None] = {
        "direct_commentary": 2,      # 全书最多 1-2 次
        "dialogue_hint": None,        # per-chapter (checked separately)
        "action_embodiment": None,    # 每章都可以 — no cap
        "imagery_osmosis": None,      # 自然融入 — no cap
        "structure_mapping": None,    # 规划时确定 — no cap
    }

    # Per-chapter cap for dialogue_hint: every 3-4 chapters allows one
    DIALOGUE_HINT_CHAPTER_INTERVAL = 3

    def get_expression_usage(self, project_id: str) -> dict[str, int]:
        """Get current expression spectrum usage counts for the project."""
        profile = self.session.execute(
            select(WorkProfile)
            .where(
                WorkProfile.scope_ref_id == project_id,
                WorkProfile.profile_key == "expression_spectrum_usage",
                WorkProfile.status == "active",
            )
        ).scalars().first()
        if profile is None:
            return {key: 0 for key, _, _ in EXPRESSION_SPECTRUM}
        return dict(profile.profile_json or {})

    def record_expression_usage(
        self,
        project_id: str,
        expression_level: str,
        scene_id: str,
        chapter_id: str,
    ) -> dict[str, Any]:
        """Record usage of an expression level and check against caps.

        Returns a dict with 'allowed' (bool), 'warning' (str|None),
        and updated 'usage' counts.
        """
        usage = self.get_expression_usage(project_id)
        current_count = usage.get(expression_level, 0)
        cap = self.EXPRESSION_FREQUENCY_CAPS.get(expression_level)

        warning = None
        allowed = True

        if cap is not None and current_count >= cap:
            allowed = False
            level_label = next(
                (cn for key, cn, _ in EXPRESSION_SPECTRUM if key == expression_level),
                expression_level,
            )
            warning = (
                f"Expression level '{level_label}' has been used {current_count} times "
                f"(cap: {cap}). Blueprint §12: '{level_label}' 全书上限已达到。"
                f" Use a more implicit expression level instead."
            )

        if expression_level == "dialogue_hint":
            chapters_since_last = self._chapters_since_last_dialogue_hint(
                project_id, chapter_id,
            )
            if chapters_since_last is not None and chapters_since_last < self.DIALOGUE_HINT_CHAPTER_INTERVAL:
                allowed = False
                warning = (
                    f"'对话暗示' was used {chapters_since_last} chapters ago "
                    f"(minimum interval: {self.DIALOGUE_HINT_CHAPTER_INTERVAL}). "
                    f"Use a more implicit level."
                )

        if allowed:
            usage[expression_level] = current_count + 1
            self._persist_expression_usage(project_id, usage, scene_id)

        return {"allowed": allowed, "warning": warning, "usage": usage}

    def check_expression_budget(self, project_id: str) -> list[dict[str, Any]]:
        """Check which expression levels are approaching or at their cap."""
        usage = self.get_expression_usage(project_id)
        warnings: list[dict[str, Any]] = []
        for key, cn_label, freq_desc in EXPRESSION_SPECTRUM:
            cap = self.EXPRESSION_FREQUENCY_CAPS.get(key)
            count = usage.get(key, 0)
            if cap is not None:
                if count >= cap:
                    warnings.append({
                        "level": key,
                        "label": cn_label,
                        "count": count,
                        "cap": cap,
                        "status": "exhausted",
                        "message": f"'{cn_label}' 已达全书上限 ({cap})，请使用更隐蔽的表达层级",
                    })
                elif count >= cap - 1:
                    warnings.append({
                        "level": key,
                        "label": cn_label,
                        "count": count,
                        "cap": cap,
                        "status": "near_cap",
                        "message": f"'{cn_label}' 仅剩 {cap - count} 次使用额度",
                    })
        return warnings

    def _chapters_since_last_dialogue_hint(
        self, project_id: str, current_chapter_id: str,
    ) -> int | None:
        """Count how many chapters since the last dialogue_hint usage."""
        profile = self.session.execute(
            select(WorkProfile)
            .where(
                WorkProfile.scope_ref_id == project_id,
                WorkProfile.profile_key == "expression_spectrum_log",
                WorkProfile.status == "active",
            )
        ).scalars().first()
        if profile is None:
            return None

        log_entries = (profile.profile_json or {}).get("entries", [])
        chapters = list(self.session.execute(
            select(ChapterGoal.chapter_id)
            .where(ChapterGoal.project_id == project_id)
            .order_by(ChapterGoal.display_order.asc())
        ).scalars().all())

        current_idx = chapters.index(current_chapter_id) if current_chapter_id in chapters else len(chapters)

        for entry in reversed(log_entries):
            if entry.get("level") == "dialogue_hint":
                entry_chapter = entry.get("chapter_id")
                if entry_chapter in chapters:
                    entry_idx = chapters.index(entry_chapter)
                    return current_idx - entry_idx
        return None

    def _persist_expression_usage(
        self, project_id: str, usage: dict[str, int], scene_id: str,
    ) -> None:
        """Persist updated usage counts."""
        import uuid

        # Update the counts profile
        profile = self.session.execute(
            select(WorkProfile)
            .where(
                WorkProfile.scope_ref_id == project_id,
                WorkProfile.profile_key == "expression_spectrum_usage",
            )
        ).scalars().first()
        if profile is None:
            profile = WorkProfile(
                profile_id=f"wp_esu_{uuid.uuid4().hex[:12]}",
                scope_type="global",
                scope_ref_id=project_id,
                profile_key="expression_spectrum_usage",
                display_name="表达光谱使用计数",
                status="active",
                profile_json=usage,
            )
            self.session.add(profile)
        else:
            profile.profile_json = usage
            profile.status = "active"
        self.session.flush()


def _extract_theme_keywords(idea: str) -> list[str]:
    """Extract meaningful bigrams + English words from a controlling idea."""
    import re
    stop_chars = set("的是在了也和与可以而但不一个本身自己")
    words: list[str] = []
    for token in re.findall(r"[a-z]{3,}", idea.lower()):
        stop_en = {"the", "and", "that", "this", "was", "were", "are", "for"}
        if token not in stop_en:
            words.append(token)
    cjk = re.findall(r"[一-鿿]", idea)
    cjk_filtered = [c for c in cjk if c not in stop_chars]
    for i in range(len(cjk_filtered) - 1):
        bigram = cjk_filtered[i] + cjk_filtered[i + 1]
        if bigram not in words:
            words.append(bigram)
    return words[:10]
