from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    BannedRuleCluster,
    CalibrationLine,
    ChapterMemory,
    ForeshadowTracker,
    NarrativePattern,
    RelationProfile,
    SceneCard,
    SceneMemory,
    StyleRule,
    VoiceProfile,
    WorldRule,
)


class Resolver:
    @staticmethod
    def _scoped_clause(model_cls, scene: SceneCard):
        return or_(
            model_cls.scope == "global",
            and_(model_cls.scope == "chapter", model_cls.scope_ref_id == scene.chapter_id),
            and_(model_cls.scope == "scene", model_cls.scope_ref_id == scene.scene_id),
        )

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

    def resolve_active_style_rules(self, session: Session, scene: SceneCard) -> list[StyleRule]:
        return session.execute(
            select(StyleRule)
            .where(
                StyleRule.active_flag == 1,
                StyleRule.runtime_eligible == 1,
                self._scoped_clause(StyleRule, scene),
            )
            .order_by(StyleRule.created_at.asc(), StyleRule.row_id.asc())
        ).scalars().all()

    def resolve_active_banned_rule_clusters(self, session: Session, scene: SceneCard) -> list[BannedRuleCluster]:
        return session.execute(
            select(BannedRuleCluster)
            .where(
                BannedRuleCluster.active_flag == 1,
                BannedRuleCluster.runtime_eligible == 1,
                self._scoped_clause(BannedRuleCluster, scene),
            )
            .order_by(BannedRuleCluster.created_at.asc(), BannedRuleCluster.row_id.asc())
        ).scalars().all()

    def resolve_active_narrative_patterns(self, session: Session, scene: SceneCard) -> list[NarrativePattern]:
        return session.execute(
            select(NarrativePattern)
            .where(
                NarrativePattern.active_flag == 1,
                NarrativePattern.runtime_eligible == 1,
                self._scoped_clause(NarrativePattern, scene),
            )
            .order_by(NarrativePattern.created_at.asc(), NarrativePattern.row_id.asc())
        ).scalars().all()

    def resolve_active_world_rules(self, session: Session, scene: SceneCard) -> list[WorldRule]:
        now = datetime.now(UTC).isoformat()
        return session.execute(
            select(WorldRule)
            .where(
                WorldRule.active_flag == 1,
                WorldRule.runtime_eligible == 1,
                self._scoped_clause(WorldRule, scene),
                or_(WorldRule.expires_at.is_(None), WorldRule.expires_at > now),
            )
            .order_by(WorldRule.created_at.asc(), WorldRule.row_id.asc())
        ).scalars().all()

    def resolve_active_calibration_lines(self, session: Session, scene: SceneCard) -> list[CalibrationLine]:
        return session.execute(
            select(CalibrationLine)
            .where(
                CalibrationLine.active_flag == 1,
                CalibrationLine.runtime_eligible == 1,
                self._scoped_clause(CalibrationLine, scene),
            )
            .order_by(CalibrationLine.created_at.asc(), CalibrationLine.row_id.asc())
        ).scalars().all()

    def resolve_open_foreshadow_trackers(self, session: Session, scene: SceneCard) -> list[ForeshadowTracker]:
        return session.execute(
            select(ForeshadowTracker)
            .where(
                ForeshadowTracker.active_flag == 1,
                ForeshadowTracker.tracker_status == "open",
                ForeshadowTracker.chapter_id == scene.chapter_id,
                or_(ForeshadowTracker.scene_id.is_(None), ForeshadowTracker.scene_id == scene.scene_id),
            )
            .order_by(ForeshadowTracker.created_at.asc(), ForeshadowTracker.row_id.asc())
        ).scalars().all()

    def resolve_scene_summary(self, session: Session, scene: SceneCard) -> SceneMemory | None:
        return session.execute(
            select(SceneMemory)
            .where(
                SceneMemory.scene_id == scene.scene_id,
                SceneMemory.active_flag == 1,
                SceneMemory.source_review_id.is_not(None),
            )
            .order_by(SceneMemory.created_at.desc(), SceneMemory.row_id.desc())
        ).scalars().first()

    def resolve_chapter_summary(self, session: Session, scene: SceneCard) -> ChapterMemory | None:
        return session.execute(
            select(ChapterMemory)
            .where(
                ChapterMemory.chapter_id == scene.chapter_id,
                ChapterMemory.active_flag == 1,
                ChapterMemory.source_review_id.is_not(None),
            )
            .order_by(ChapterMemory.created_at.desc(), ChapterMemory.row_id.desc())
        ).scalars().first()
