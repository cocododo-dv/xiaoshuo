from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import WorkProfile


DEFAULT_WORK_PROFILES: dict[str, dict[str, Any]] = {
    "strong_plot": {
        "display_name": "强情节",
        "description": "强调选择压力、行动代价、信息释放和结尾驱动。",
        "profile_json": {
            "choice_pressure_policy": "strict",
            "ending_drive_policy": "strict",
            "diagnosis_tone": "decisive",
            "blocking_dimensions": ["continuity", "fact_blocker"],
            "profile_sensitive_dimensions": ["choice_pressure", "ending_drive", "reader_hook"],
        },
    },
    "relationship": {
        "display_name": "人物关系",
        "description": "强调关系转折、潜台词、权力变化和对白边缘。",
        "profile_json": {
            "choice_pressure_policy": "relationship_cost",
            "ending_drive_policy": "medium",
            "diagnosis_tone": "editorial",
            "blocking_dimensions": ["continuity", "fact_blocker"],
            "profile_sensitive_dimensions": ["relationship_tension", "dialogue_subtext", "power_shift"],
        },
    },
    "mystery": {
        "display_name": "悬疑推理",
        "description": "强调线索释放、误导控制、证据链和承诺兑现。",
        "profile_json": {
            "choice_pressure_policy": "medium",
            "ending_drive_policy": "clue_or_question",
            "diagnosis_tone": "forensic",
            "blocking_dimensions": ["continuity", "fact_blocker", "unsupported_event"],
            "profile_sensitive_dimensions": ["information_rhythm", "promise_payoff", "reader_hook"],
        },
    },
    "daily_life": {
        "display_name": "日常流",
        "description": "允许低冲突推进，强调生活质感、微小关系变化和余味。",
        "profile_json": {
            "choice_pressure_policy": "suggest",
            "ending_drive_policy": "soft",
            "diagnosis_tone": "gentle",
            "blocking_dimensions": ["continuity", "fact_blocker"],
            "profile_sensitive_dimensions": ["voice_distinction", "image_necessity", "reader_aftertaste"],
        },
    },
    "quiet_literary": {
        "display_name": "文学慢热",
        "description": "允许内倾和慢热，强调声音辨识、主题压力、歧义和余韵。",
        "profile_json": {
            "choice_pressure_policy": "suggest",
            "ending_drive_policy": "soft",
            "diagnosis_tone": "editorial",
            "blocking_dimensions": ["continuity", "fact_blocker"],
            "profile_sensitive_dimensions": ["voice_distinction", "theme_pressure", "valid_ambiguity"],
        },
    },
    "light_comedy": {
        "display_name": "轻喜剧",
        "description": "强调节奏、反差、人物误解和关系回弹。",
        "profile_json": {
            "choice_pressure_policy": "comic_consequence",
            "ending_drive_policy": "button_or_reversal",
            "diagnosis_tone": "playful_editorial",
            "blocking_dimensions": ["continuity", "fact_blocker"],
            "profile_sensitive_dimensions": ["dialogue_edge", "relationship_tension", "rhythm"],
        },
    },
}


class WorkProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def for_chapter(self, chapter_id: str | None) -> dict[str, Any]:
        row = None
        if chapter_id:
            row = self.session.execute(
                select(WorkProfile)
                .where(
                    WorkProfile.scope_type == "chapter",
                    WorkProfile.scope_ref_id == chapter_id,
                    WorkProfile.status == "active",
                )
                .order_by(WorkProfile.updated_at.desc(), WorkProfile.profile_id.desc())
            ).scalars().first()
        if row is None:
            row = self.session.execute(
                select(WorkProfile)
                .where(
                    WorkProfile.scope_type == "global",
                    WorkProfile.scope_ref_id == "global",
                    WorkProfile.status == "active",
                )
                .order_by(WorkProfile.updated_at.desc(), WorkProfile.profile_id.desc())
            ).scalars().first()
        return self.serialize(row) if row is not None else self.default_profile("strong_plot")

    @staticmethod
    def default_profile(profile_key: str) -> dict[str, Any]:
        base = DEFAULT_WORK_PROFILES.get(profile_key, DEFAULT_WORK_PROFILES["strong_plot"])
        return {
            "profile_id": f"default:{profile_key}",
            "scope_type": "default",
            "scope_ref_id": "default",
            "profile_key": profile_key,
            "display_name": base["display_name"],
            "description": base["description"],
            "profile_json": dict(base["profile_json"]),
            "status": "active",
            "created_by": "system_default",
            "created_at": None,
            "updated_at": None,
        }

    @staticmethod
    def serialize(row: WorkProfile) -> dict[str, Any]:
        base = DEFAULT_WORK_PROFILES.get(row.profile_key, DEFAULT_WORK_PROFILES["strong_plot"])
        return {
            "profile_id": row.profile_id,
            "scope_type": row.scope_type,
            "scope_ref_id": row.scope_ref_id,
            "profile_key": row.profile_key,
            "display_name": row.display_name or base["display_name"],
            "description": row.description or base["description"],
            "profile_json": {**base["profile_json"], **(row.profile_json or {})},
            "status": row.status,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
