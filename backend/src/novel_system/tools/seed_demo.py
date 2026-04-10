from __future__ import annotations

import argparse
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
    IdempotencyKey,
    OperationLog,
    ReindexJob,
    RelationProfile,
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
    VoiceProfile,
)
from novel_system.db.session import SessionLocal
from novel_system.services.idempotency import canonical_request_hash

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
DEMO_VOICE_PROFILES = [
    {
        "row_id": "voice_profile_VOICE_CHAR_A_v1",
        "voice_profile_id": "VOICE_CHAR_A",
        "version": 1,
        "character_id": "CHAR_A",
        "content": "short clipped lines; pressure makes the tone harder",
        "active_flag": 1,
        "source_note": "demo baseline",
    },
    {
        "row_id": "voice_profile_VOICE_CHAR_B_v1",
        "voice_profile_id": "VOICE_CHAR_B",
        "version": 1,
        "character_id": "CHAR_B",
        "content": "measured, observant phrasing; rarely answers directly",
        "active_flag": 1,
        "source_note": "demo baseline",
    },
]
DEMO_RELATION_PROFILES = [
    {
        "row_id": "relation_profile_REL_CHAR_A_CHAR_B_v1",
        "relation_profile_id": "REL_CHAR_A_CHAR_B",
        "left_character_id": "CHAR_A",
        "right_character_id": "CHAR_B",
        "version": 1,
        "content": "reunion tension; B knows slightly more than A",
        "active_flag": 1,
        "source_note": "demo baseline",
    },
    {
        "row_id": "relation_profile_REL_CHAR_A_CHAR_C_v1",
        "relation_profile_id": "REL_CHAR_A_CHAR_C",
        "left_character_id": "CHAR_A",
        "right_character_id": "CHAR_C",
        "version": 1,
        "content": "uneasy cooperation; both sides hold back a condition",
        "active_flag": 1,
        "source_note": "demo baseline",
    },
]

DEMO_RUNTIME_OPS_E2E_FIXTURE = "runtime_ops_e2e"
DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_REVIEW = {
    "review_id": "review_demo_due_promotion",
    "scene_id": "CH001_SC02",
    "chapter_id": "CH001",
    "item_type": "style_observation",
    "status": "approved",
    "candidate_text": "promote the verified scene-scope note during runtime ops",
    "candidate_payload_json": {
        "scope": "scene",
        "scope_ref_id": "CH001_SC02",
        "lineage_key": "STY_DEMO_DUE_PROMOTION",
        "text": "promote the verified scene-scope note during runtime ops",
        "effective_at": "2000-01-01T00:00:00+00:00",
    },
    "active_on_approve": 1,
    "materialize_status": "succeeded",
    "retry_count": 0,
    "max_retry": 3,
    "approved_item_row_id": "style_observation_STY_DEMO_DUE_PROMOTION_v1",
    "approved_item_id": "STY_DEMO_DUE_PROMOTION",
}
DEMO_RUNTIME_OPS_E2E_RECOVERY_REVIEW = {
    "review_id": "review_demo_recovery_followup",
    "scene_id": "CH001_SC03",
    "chapter_id": "CH001",
    "item_type": "style_observation",
    "status": "pending",
    "candidate_text": "replay the stranded approve request and finish the follow-up chain",
    "candidate_payload_json": {
        "scope": "scene",
        "scope_ref_id": "CH001_SC03",
        "lineage_key": "STY_DEMO_RECOVERY_FOLLOWUP",
        "text": "replay the stranded approve request and finish the follow-up chain",
    },
    "active_on_approve": 0,
    "materialize_status": "pending",
    "retry_count": 0,
    "max_retry": 3,
    "approved_item_row_id": None,
    "approved_item_id": None,
}
DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ACTIVE_ROW = {
    "row_id": "style_observation_STY_ACTIVE_SC02_v1",
    "style_observation_id": "STY_ACTIVE_SC02",
    "version": 1,
    "scope": "scene",
    "scope_ref_id": "CH001_SC02",
    "text": "the current scene note stays active until due promotion runs",
    "source_review_id": "review_demo_active_scene_seed",
    "active_flag": 1,
    "runtime_eligible": 1,
    "runtime_eligibility_basis": "vector_ready",
}
DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ROW = {
    "row_id": "style_observation_STY_DEMO_DUE_PROMOTION_v1",
    "style_observation_id": "STY_DEMO_DUE_PROMOTION",
    "version": 1,
    "scope": "scene",
    "scope_ref_id": "CH001_SC02",
    "text": "promote the verified scene-scope note during runtime ops",
    "source_review_id": "review_demo_due_promotion",
    "active_flag": 0,
    "runtime_eligible": 0,
    "runtime_eligibility_basis": "future_effective",
    "effective_at": "2000-01-01T00:00:00+00:00",
}
DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_REGISTRY = {
    "object_type": "style_observation",
    "lineage_key": "STY_DEMO_DUE_PROMOTION",
    "version": 1,
    "physical_row_id": "style_observation_STY_DEMO_DUE_PROMOTION_v1",
    "alias_scope": "style_observation:scene:CH001_SC02",
    "materialize_status": "succeeded",
    "reindex_status": "succeeded",
    "verify_status": "succeeded",
}
DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ALIAS = {
    "alias_scope": "style_observation:scene:CH001_SC02",
    "object_type": "style_observation",
    "scope": "scene",
    "scope_ref_id": "CH001_SC02",
    "collection_family": "style_observation_scene_CH001_SC02",
    "active_alias": "style_observation_scene_CH001_SC02__candidate__style_observation_STY_ACTIVE_SC02_v1",
    "candidate_alias": "style_observation_scene_CH001_SC02__candidate__style_observation_STY_DEMO_DUE_PROMOTION_v1",
    "active_snapshot_version": "snapshot__style_observation_STY_ACTIVE_SC02_v1",
    "candidate_snapshot_version": "snapshot__style_observation_STY_DEMO_DUE_PROMOTION_v1",
    "active_embedding_version": "embed__style_observation_STY_ACTIVE_SC02_v1",
    "candidate_embedding_version": "embed__style_observation_STY_DEMO_DUE_PROMOTION_v1",
    "verify_status": "succeeded",
    "sample_query_success": 1,
}
DEMO_RUNTIME_OPS_E2E_RECLAIMABLE_VERIFY_JOB = {
    "job_id": "verify_job_demo_reclaimable",
    "review_id": None,
    "status": "running",
    "object_type": "style_observation",
    "alias_scope": "style_observation:scene:CH001_SC01",
    "target_snapshot_version": "snapshot__style_observation_STY_RECLAIMABLE_v1",
    "target_embedding_version": "embed__style_observation_STY_RECLAIMABLE_v1",
    "worker_id": "verify-worker-stale",
    "attempt_no": 2,
    "heartbeat_at": "2026-04-09T16:00:00+00:00",
    "lease_expires_at": "2000-01-01T00:00:00+00:00",
    "started_at": "2026-04-09T15:59:00+00:00",
    "finished_at": None,
    "error_text": None,
}
DEMO_RUNTIME_OPS_E2E_FAILED_VERIFY_JOB = {
    "job_id": "verify_job_demo_failed_recent",
    "review_id": None,
    "status": "failed",
    "object_type": "style_observation",
    "alias_scope": "style_observation:scene:CH001_SC01",
    "target_snapshot_version": "snapshot__style_observation_STY_FAILED_v1",
    "target_embedding_version": "embed__style_observation_STY_FAILED_v1",
    "worker_id": "verify-worker-failed",
    "attempt_no": 3,
    "heartbeat_at": "2026-04-09T16:04:00+00:00",
    "lease_expires_at": "2026-04-09T16:07:00+00:00",
    "started_at": "2026-04-09T16:02:00+00:00",
    "finished_at": "2026-04-09T16:05:00+00:00",
    "error_text": "candidate alias verify failed",
}
DEMO_RUNTIME_OPS_E2E_RECOVERY_IDEMPOTENCY_KEY = "approve-review-demo-recovery-followup"
DEMO_RUNTIME_OPS_E2E_RECOVERY_REQUEST_PAYLOAD = {"review_id": "review_demo_recovery_followup"}
DEMO_RUNTIME_OPS_E2E_RECOVERY_REQUEST_HASH = canonical_request_hash(
    "POST",
    "/api/v1/review-items/{review_id}/approve",
    DEMO_RUNTIME_OPS_E2E_RECOVERY_REQUEST_PAYLOAD,
)
DEMO_RUNTIME_OPS_E2E_REVIEW_IDS = [
    DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_REVIEW["review_id"],
    DEMO_RUNTIME_OPS_E2E_RECOVERY_REVIEW["review_id"],
]
DEMO_RUNTIME_OPS_E2E_STYLE_IDS = [
    DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ACTIVE_ROW["style_observation_id"],
    DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ROW["style_observation_id"],
    DEMO_RUNTIME_OPS_E2E_RECOVERY_REVIEW["candidate_payload_json"]["lineage_key"],
]
DEMO_RUNTIME_OPS_E2E_STYLE_ROW_IDS = [
    DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ACTIVE_ROW["row_id"],
    DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ROW["row_id"],
]
DEMO_RUNTIME_OPS_E2E_JOB_IDS = [
    DEMO_RUNTIME_OPS_E2E_RECLAIMABLE_VERIFY_JOB["job_id"],
    DEMO_RUNTIME_OPS_E2E_FAILED_VERIFY_JOB["job_id"],
    "reindex_review_demo_recovery_followup",
    "verify_review_demo_recovery_followup",
]
DEMO_RUNTIME_OPS_E2E_EVENT_IDS = [
    "human_review_idempotency_recovery_approve-review-demo-recovery-followup",
]
DEMO_RUNTIME_OPS_E2E_ALIAS_SCOPES = [
    ("global", "global"),
    ("scene", "CH001_SC02"),
    ("scene", "CH001_SC03"),
]


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


def _upsert_version_registry(session: Session, payload: dict[str, Any]) -> None:
    row = session.execute(
        select(VersionRegistry).where(VersionRegistry.physical_row_id == payload["physical_row_id"])
    ).scalar_one_or_none()
    if row is None:
        session.add(VersionRegistry(**payload))
        return
    for key, value in payload.items():
        setattr(row, key, value)


def _delete_alias_if_scope_empty(session: Session, scope: str, scope_ref_id: str) -> None:
    remaining_scope_count = session.scalar(
        select(func.count()).select_from(StyleObservation).where(
            StyleObservation.scope == scope,
            func.coalesce(StyleObservation.scope_ref_id, "global") == scope_ref_id,
        )
    )
    if remaining_scope_count == 0:
        alias = session.get(VectorAliasRegistry, f"style_observation:{scope}:{scope_ref_id}")
        if alias is not None:
            session.delete(alias)


def _cleanup_demo_runtime(session: Session) -> None:
    chapter_id = DEMO_CHAPTER["chapter_id"]
    all_demo_review_ids = [DEMO_STYLE_OBSERVATION_REVIEW["review_id"], *DEMO_RUNTIME_OPS_E2E_REVIEW_IDS]
    all_demo_lineage_keys = [DEMO_STYLE_OBSERVATION_REVIEW["candidate_payload_json"]["lineage_key"], *DEMO_RUNTIME_OPS_E2E_STYLE_IDS]
    all_demo_style_row_ids = [
        "style_observation_STY_DEMO_001_v1",
        *DEMO_RUNTIME_OPS_E2E_STYLE_ROW_IDS,
    ]
    all_demo_job_ids = [
        "reindex_review_demo_style_observation",
        "verify_review_demo_style_observation",
        *DEMO_RUNTIME_OPS_E2E_JOB_IDS,
    ]
    all_demo_operation_refs = [
        *all_demo_review_ids,
        *all_demo_style_row_ids,
        *all_demo_job_ids,
        DEMO_RUNTIME_OPS_E2E_RECOVERY_IDEMPOTENCY_KEY,
        *DEMO_RUNTIME_OPS_E2E_EVENT_IDS,
    ]
    demo_voice_ids = [item["voice_profile_id"] for item in DEMO_VOICE_PROFILES]
    demo_relation_ids = [item["relation_profile_id"] for item in DEMO_RELATION_PROFILES]

    session.execute(delete(AttemptTracker).where(AttemptTracker.chapter_id == chapter_id))
    session.execute(delete(SceneBundle).where(SceneBundle.chapter_id == chapter_id))
    session.execute(delete(SceneDraft).where(SceneDraft.chapter_id == chapter_id))
    session.execute(delete(FinalScene).where(FinalScene.chapter_id == chapter_id))
    session.execute(delete(SceneMemory).where(SceneMemory.chapter_id == chapter_id))
    session.execute(delete(ChapterMemory).where(ChapterMemory.chapter_id == chapter_id))
    session.execute(delete(ChapterRollingNote).where(ChapterRollingNote.chapter_id == chapter_id))
    session.execute(delete(HumanReviewEvent).where(HumanReviewEvent.chapter_id == chapter_id))
    session.execute(delete(OperationLog).where(OperationLog.object_ref.in_(all_demo_operation_refs)))
    session.execute(delete(IdempotencyKey).where(IdempotencyKey.idempotency_key == DEMO_RUNTIME_OPS_E2E_RECOVERY_IDEMPOTENCY_KEY))
    session.execute(
        delete(ReindexJob).where(
            or_(
                ReindexJob.review_id.in_(all_demo_review_ids),
                ReindexJob.job_id.in_(all_demo_job_ids),
            )
        )
    )
    session.execute(
        delete(VerifyJob).where(
            or_(
                VerifyJob.review_id.in_(all_demo_review_ids),
                VerifyJob.job_id.in_(all_demo_job_ids),
            )
        )
    )
    session.execute(
        delete(VersionRegistry).where(
            or_(
                VersionRegistry.lineage_key.in_(all_demo_lineage_keys),
                VersionRegistry.physical_row_id.in_(all_demo_style_row_ids),
            )
        )
    )
    session.execute(
        delete(StyleObservation).where(
            or_(
                StyleObservation.style_observation_id.in_(all_demo_lineage_keys),
                StyleObservation.source_review_id.in_(all_demo_review_ids),
                StyleObservation.row_id.in_(all_demo_style_row_ids),
            )
        )
    )
    session.execute(delete(ReviewItem).where(ReviewItem.review_id.in_(DEMO_RUNTIME_OPS_E2E_REVIEW_IDS)))
    session.execute(delete(VoiceProfile).where(VoiceProfile.voice_profile_id.in_(demo_voice_ids)))
    session.execute(delete(RelationProfile).where(RelationProfile.relation_profile_id.in_(demo_relation_ids)))

    for scope, scope_ref_id in DEMO_RUNTIME_OPS_E2E_ALIAS_SCOPES:
        _delete_alias_if_scope_empty(session, scope, scope_ref_id)


def _seed_runtime_ops_e2e(session: Session) -> list[str]:
    _upsert_review_item(session, DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_REVIEW)
    _upsert_review_item(session, DEMO_RUNTIME_OPS_E2E_RECOVERY_REVIEW)
    _upsert(session, StyleObservation, "row_id", DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ACTIVE_ROW)
    _upsert(session, StyleObservation, "row_id", DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ROW)
    _upsert_version_registry(session, DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_REGISTRY)
    _upsert(session, VectorAliasRegistry, "alias_scope", DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ALIAS)
    _upsert(session, VerifyJob, "job_id", DEMO_RUNTIME_OPS_E2E_RECLAIMABLE_VERIFY_JOB)
    _upsert(session, VerifyJob, "job_id", DEMO_RUNTIME_OPS_E2E_FAILED_VERIFY_JOB)
    _upsert(
        session,
        IdempotencyKey,
        "idempotency_key",
        {
            "idempotency_key": DEMO_RUNTIME_OPS_E2E_RECOVERY_IDEMPOTENCY_KEY,
            "request_hash": DEMO_RUNTIME_OPS_E2E_RECOVERY_REQUEST_HASH,
            "status": "started",
            "response_json": None,
            "worker_id": "http",
            "attempt_no": 2,
            "heartbeat_at": "2026-04-09T16:00:00+00:00",
            "lease_expires_at": "2000-01-01T00:00:00+00:00",
        },
    )
    session.add(
        OperationLog(
            event_type="idempotency_started",
            object_type="idempotency_key",
            object_ref=DEMO_RUNTIME_OPS_E2E_RECOVERY_IDEMPOTENCY_KEY,
            payload_json={
                "request_hash": DEMO_RUNTIME_OPS_E2E_RECOVERY_REQUEST_HASH,
                "request_method": "POST",
                "request_path_template": "/api/v1/review-items/{review_id}/approve",
                "request_payload": DEMO_RUNTIME_OPS_E2E_RECOVERY_REQUEST_PAYLOAD,
                "attempt_no": 2,
                "actor_ref": "system/e2e_fixture",
            },
        )
    )
    return [
        DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_REVIEW["review_id"],
        DEMO_RUNTIME_OPS_E2E_RECOVERY_REVIEW["review_id"],
    ]


def _seed_demo(session: Session, *, fixture: str | None = None) -> dict[str, list[str] | str]:
    _cleanup_demo_runtime(session)
    _upsert_chapter(session, DEMO_CHAPTER)
    for payload in DEMO_SCENES:
        _upsert_scene(session, payload)
    for payload in DEMO_VOICE_PROFILES:
        _upsert(session, VoiceProfile, "row_id", payload)
    for payload in DEMO_RELATION_PROFILES:
        _upsert(session, RelationProfile, "row_id", payload)
    _upsert_review_item(session, DEMO_STYLE_OBSERVATION_REVIEW)
    review_ids = [DEMO_STYLE_OBSERVATION_REVIEW["review_id"]]
    if fixture is None:
        pass
    elif fixture == DEMO_RUNTIME_OPS_E2E_FIXTURE:
        review_ids.extend(_seed_runtime_ops_e2e(session))
    else:
        raise ValueError(f"Unsupported demo fixture: {fixture}")
    return {
        "chapter_id": DEMO_CHAPTER["chapter_id"],
        "scene_ids": [item["scene_id"] for item in DEMO_SCENES],
        "review_ids": review_ids,
    }


def seed_demo(session: Session | None = None, *, fixture: str | None = None) -> dict[str, list[str] | str]:
    if session is not None:
        return _seed_demo(session, fixture=fixture)

    with SessionLocal() as managed_session:
        summary = _seed_demo(managed_session, fixture=fixture)
        managed_session.commit()
        return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", choices=[DEMO_RUNTIME_OPS_E2E_FIXTURE])
    args = parser.parse_args(argv)
    print(json.dumps(seed_demo(fixture=args.fixture), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
