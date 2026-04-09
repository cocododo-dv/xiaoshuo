from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AttemptTracker,
    ChapterGoal,
    ChapterMemory,
    ChapterRollingNote,
    ChapterState,
    FinalScene,
    HumanReviewEvent,
    ReindexJob,
    ReviewItem,
    SceneBundle,
    SceneCard,
    SceneDraft,
    SceneMemory,
    SceneRunState,
    StyleObservation,
    VectorAliasRegistry,
    VerifyJob,
    VersionRegistry,
)
from novel_system.db.session import SessionLocal

DEMO_CHAPTER = {
    "chapter_id": "CH001",
    "planned_scene_count": 3,
    "chapter_goal": "重逢与试探成立",
    "main_plot_push": "旧信线索被正式打开",
    "emotional_target": "由迟疑转入警觉",
    "ending_effect": "留下余波",
}

DEMO_SCENES = [
    {
        "scene_id": "CH001_SC01",
        "chapter_id": "CH001",
        "scene_seq": 1,
        "pov_character_id": "CHAR_A",
        "onstage_chars_json": ["CHAR_A", "CHAR_B"],
        "location": "旧城门廊",
        "scene_goal": "让两人重新见面并建立张力",
        "beats_json": ["重逢", "试探", "留钩子"],
        "must_include_text": "旧信寄件人的线索",
        "target_length_band": "short",
        "scene_type": "reunion",
        "is_chapter_last": 0,
    },
    {
        "scene_id": "CH001_SC02",
        "chapter_id": "CH001",
        "scene_seq": 2,
        "pov_character_id": "CHAR_B",
        "onstage_chars_json": ["CHAR_A", "CHAR_B", "CHAR_C"],
        "location": "档案库侧室",
        "scene_goal": "把旧信中的矛盾线索抬到台面上",
        "beats_json": ["核对笔迹", "暴露缺口", "压下结论"],
        "must_include_text": "档案页边角的旧印记",
        "target_length_band": "medium",
        "scene_type": "investigation",
        "is_chapter_last": 0,
    },
    {
        "scene_id": "CH001_SC03",
        "chapter_id": "CH001",
        "scene_seq": 3,
        "pov_character_id": "CHAR_A",
        "onstage_chars_json": ["CHAR_A", "CHAR_C"],
        "location": "雨夜码头",
        "scene_goal": "让角色带着未解问题进入下一章",
        "beats_json": ["追到码头", "交换条件", "余波收束"],
        "must_include_text": "远处汽笛压住最后一句话",
        "target_length_band": "medium",
        "scene_type": "cliffhanger",
        "is_chapter_last": 1,
    },
]

DEMO_STYLE_OBSERVATION_REVIEW = {
    "review_id": "review_demo_style_observation",
    "scene_id": "CH001_SC01",
    "chapter_id": "CH001",
    "item_type": "style_observation",
    "status": "pending",
    "candidate_text": "收尾保留半句停顿，让情绪压在门后。",
    "candidate_payload_json": {
        "scope": "global",
        "scope_ref_id": "global",
        "lineage_key": "STY_DEMO_001",
        "text": "收尾保留半句停顿，让情绪压在门后。",
    },
    "active_on_approve": 0,
    "materialize_status": "pending",
    "retry_count": 0,
    "max_retry": 3,
    "approved_item_row_id": None,
    "approved_item_id": None,
}
DEMO_ALIAS_SCOPE = "style_observation:global:global"


def _upsert(session: Any, model: type[Any], identity: str, payload: dict[str, Any]) -> Any:
    row = session.get(model, payload[identity])
    if row is None:
        row = model(**payload)
        session.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    return row


def _upsert_chapter(session: Any, payload: dict[str, Any]) -> None:
    _upsert(session, ChapterGoal, "chapter_id", payload)
    _upsert(
        session,
        ChapterState,
        "chapter_id",
        {
            "chapter_id": payload["chapter_id"],
            "current_phase": "drafting",
            "chapter_passed_scene_count": 0,
            "chapter_backfill_pending_count": 0,
            "mid_aggregate_enabled_effective": 0,
            "aggregate_block_reason": "none",
            "last_interim_memory_row_id": None,
            "last_final_memory_row_id": None,
        },
    )


def _upsert_scene(session: Any, payload: dict[str, Any]) -> None:
    _upsert(session, SceneCard, "scene_id", payload)
    _upsert(
        session,
        SceneRunState,
        "scene_id",
        {
            "scene_id": payload["scene_id"],
            "scene_status": "ready",
            "current_bundle_id": None,
            "current_bundle_hash": None,
            "current_neutral_draft_row_id": None,
            "current_style_draft_row_id": None,
            "current_final_scene_row_id": None,
            "current_human_review_event_id": None,
            "current_qc_report_id": None,
            "bundle_build_count": 0,
            "hard_partial_rewrite_count": 0,
            "hard_full_rewrite_count": 0,
            "soft_patch_count": 0,
            "total_attempt_count": 0,
            "attempt_budget": 4,
            "repeat_issue_key": None,
            "repeat_issue_count": 0,
        },
    )


def _upsert_review_item(session: Any, payload: dict[str, Any]) -> None:
    _upsert(session, ReviewItem, "review_id", payload)


def _cleanup_demo_runtime(session: Session) -> None:
    chapter_id = DEMO_CHAPTER["chapter_id"]
    review_id = DEMO_STYLE_OBSERVATION_REVIEW["review_id"]
    lineage_key = DEMO_STYLE_OBSERVATION_REVIEW["candidate_payload_json"]["lineage_key"]

    session.execute(delete(AttemptTracker).where(AttemptTracker.chapter_id == chapter_id))
    session.execute(delete(SceneBundle).where(SceneBundle.chapter_id == chapter_id))
    session.execute(delete(SceneDraft).where(SceneDraft.chapter_id == chapter_id))
    session.execute(delete(FinalScene).where(FinalScene.chapter_id == chapter_id))
    session.execute(delete(SceneMemory).where(SceneMemory.chapter_id == chapter_id))
    session.execute(delete(ChapterMemory).where(ChapterMemory.chapter_id == chapter_id))
    session.execute(delete(ChapterRollingNote).where(ChapterRollingNote.chapter_id == chapter_id))
    session.execute(delete(HumanReviewEvent).where(HumanReviewEvent.chapter_id == chapter_id))
    session.execute(delete(ReindexJob).where(ReindexJob.review_id == review_id))
    session.execute(delete(VerifyJob).where(VerifyJob.review_id == review_id))
    session.execute(
        delete(VersionRegistry).where(
            or_(
                VersionRegistry.lineage_key == lineage_key,
                VersionRegistry.physical_row_id.like(f"style_observation_{lineage_key}_%"),
            )
        )
    )
    session.execute(
        delete(StyleObservation).where(
            or_(
                StyleObservation.style_observation_id == lineage_key,
                StyleObservation.source_review_id == review_id,
            )
        )
    )

    remaining_global_style_count = session.scalar(
        select(func.count()).select_from(StyleObservation).where(
            StyleObservation.scope == "global",
            func.coalesce(StyleObservation.scope_ref_id, "global") == "global",
        )
    )
    if remaining_global_style_count == 0:
        alias = session.get(VectorAliasRegistry, DEMO_ALIAS_SCOPE)
        if alias is not None:
            session.delete(alias)


def _seed_demo(session: Session) -> dict[str, list[str] | str]:
    _cleanup_demo_runtime(session)
    _upsert_chapter(session, DEMO_CHAPTER)
    for payload in DEMO_SCENES:
        _upsert_scene(session, payload)
    _upsert_review_item(session, DEMO_STYLE_OBSERVATION_REVIEW)
    return {
        "chapter_id": DEMO_CHAPTER["chapter_id"],
        "scene_ids": [item["scene_id"] for item in DEMO_SCENES],
        "review_ids": [DEMO_STYLE_OBSERVATION_REVIEW["review_id"]],
    }


def seed_demo(session: Session | None = None) -> dict[str, list[str] | str]:
    if session is not None:
        return _seed_demo(session)

    with SessionLocal() as managed_session:
        summary = _seed_demo(managed_session)
        managed_session.commit()
        return summary


def main() -> None:
    print(json.dumps(seed_demo(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
