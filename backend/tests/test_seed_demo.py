from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy import func, select

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
from novel_system.tools.seed_demo import main, seed_demo


def _count_rows(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_seed_demo_creates_first_chapter_and_review_item(session) -> None:
    summary = seed_demo(session)
    session.commit()

    assert summary["chapter_id"] == "CH001"
    assert summary["scene_ids"] == ["CH001_SC01", "CH001_SC02", "CH001_SC03"]
    assert summary["review_ids"] == ["review_demo_style_observation"]
    assert _count_rows(session, ChapterGoal) == 1
    assert _count_rows(session, SceneCard) == 3
    assert _count_rows(session, SceneRunState) == 3
    assert _count_rows(session, ReviewItem) == 1


def test_seed_demo_runtime_ops_e2e_fixture_creates_promotable_and_recoverable_state(session) -> None:
    summary = seed_demo(session, fixture="runtime_ops_e2e")
    session.commit()

    assert summary["review_ids"] == [
        "review_demo_style_observation",
        "review_demo_due_promotion",
        "review_demo_recovery_followup",
    ]

    due_promotion_review = session.get(ReviewItem, "review_demo_due_promotion")
    assert due_promotion_review is not None
    assert due_promotion_review.status == "approved"
    assert due_promotion_review.materialize_status == "succeeded"

    due_promotion_row = session.get(StyleObservation, "style_observation_STY_DEMO_DUE_PROMOTION_v1")
    assert due_promotion_row is not None
    assert due_promotion_row.runtime_eligibility_basis == "future_effective"
    assert due_promotion_row.effective_at == "2000-01-01T00:00:00+00:00"

    due_promotion_alias = session.get(VectorAliasRegistry, "style_observation:scene:CH001_SC02")
    assert due_promotion_alias is not None
    assert due_promotion_alias.candidate_alias == (
        "style_observation_scene_CH001_SC02__candidate__style_observation_STY_DEMO_DUE_PROMOTION_v1"
    )
    assert due_promotion_alias.verify_status == "succeeded"

    recovery_review = session.get(ReviewItem, "review_demo_recovery_followup")
    assert recovery_review is not None
    assert recovery_review.status == "pending"
    assert recovery_review.materialize_status == "pending"

    stale_key = session.get(IdempotencyKey, "approve-review-demo-recovery-followup")
    assert stale_key is not None
    assert stale_key.status == "started"
    assert stale_key.worker_id == "http"
    assert stale_key.lease_expires_at == "2000-01-01T00:00:00+00:00"

    stale_log = session.execute(
        select(OperationLog)
        .where(
            OperationLog.object_type == "idempotency_key",
            OperationLog.object_ref == "approve-review-demo-recovery-followup",
            OperationLog.event_type == "idempotency_started",
        )
    ).scalars().one()
    assert stale_log.payload_json["request_path_template"] == "/api/v1/review-items/{review_id}/approve"
    assert stale_log.payload_json["request_payload"] == {"review_id": "review_demo_recovery_followup"}

    reclaimable_verify = session.get(VerifyJob, "verify_job_demo_reclaimable")
    assert reclaimable_verify is not None
    assert reclaimable_verify.status == "running"
    assert reclaimable_verify.worker_id == "verify-worker-stale"
    assert reclaimable_verify.lease_expires_at == "2000-01-01T00:00:00+00:00"

    failed_verify = session.get(VerifyJob, "verify_job_demo_failed_recent")
    assert failed_verify is not None
    assert failed_verify.status == "failed"
    assert failed_verify.error_text == "candidate alias verify failed"


def test_seed_demo_cli_accepts_runtime_ops_e2e_fixture(capsys) -> None:
    main(["--fixture", "runtime_ops_e2e"])

    summary = json.loads(capsys.readouterr().out)
    assert summary["review_ids"] == [
        "review_demo_style_observation",
        "review_demo_due_promotion",
        "review_demo_recovery_followup",
    ]


def test_seed_demo_is_idempotent(session) -> None:
    first = seed_demo(session)
    session.commit()
    second = seed_demo(session)
    session.commit()

    assert first == second
    assert _count_rows(session, SceneCard) == 3
    assert _count_rows(session, ReviewItem) == 1


def test_seed_demo_creates_traceable_voice_and_relation_profiles(session) -> None:
    seed_demo(session)
    session.commit()

    voice = session.execute(
        text(
            "SELECT row_id, voice_profile_id, version, active_flag, content "
            "FROM voice_profiles WHERE row_id = 'voice_profile_VOICE_CHAR_A_v1'"
        )
    ).mappings().one()
    relation = session.execute(
        text(
            "SELECT row_id, relation_profile_id, version, active_flag, content "
            "FROM relation_profiles WHERE row_id = 'relation_profile_REL_CHAR_A_CHAR_B_v1'"
        )
    ).mappings().one()

    assert voice["voice_profile_id"] == "VOICE_CHAR_A"
    assert voice["version"] == 1
    assert voice["active_flag"] == 1
    assert voice["content"] == "short clipped lines; pressure makes the tone harder"
    assert relation["relation_profile_id"] == "REL_CHAR_A_CHAR_B"
    assert relation["version"] == 1
    assert relation["active_flag"] == 1
    assert relation["content"] == "reunion tension; B knows slightly more than A"


def test_seed_demo_resets_demo_runtime_state(session) -> None:
    seed_demo(session)
    session.commit()

    chapter_state = session.get(ChapterState, "CH001")
    scene_state = session.get(SceneRunState, "CH001_SC01")
    review_item = session.get(ReviewItem, "review_demo_style_observation")

    chapter_state.current_phase = "archived"
    chapter_state.chapter_passed_scene_count = 2
    chapter_state.last_final_memory_row_id = "memory_final_demo"
    scene_state.scene_status = "archived"
    scene_state.current_bundle_id = "bundle_demo"
    scene_state.total_attempt_count = 4
    scene_state.repeat_issue_key = "demo_repeat"
    review_item.status = "approved"
    review_item.materialize_status = "succeeded"
    review_item.approved_item_row_id = "style_observation_demo"
    review_item.approved_item_id = "STY_DEMO_001"
    session.commit()

    seed_demo(session)
    session.commit()
    session.expire_all()

    reset_chapter_state = session.get(ChapterState, "CH001")
    reset_scene_state = session.get(SceneRunState, "CH001_SC01")
    reset_review_item = session.get(ReviewItem, "review_demo_style_observation")

    assert reset_chapter_state.current_phase == "drafting"
    assert reset_chapter_state.chapter_passed_scene_count == 0
    assert reset_chapter_state.last_final_memory_row_id is None
    assert reset_scene_state.scene_status == "ready"
    assert reset_scene_state.current_bundle_id is None
    assert reset_scene_state.total_attempt_count == 0
    assert reset_scene_state.repeat_issue_key is None
    assert reset_review_item.status == "pending"
    assert reset_review_item.materialize_status == "pending"
    assert reset_review_item.approved_item_row_id is None
    assert reset_review_item.approved_item_id is None


def test_seed_demo_clears_demo_derived_records(session) -> None:
    seed_demo(session)
    session.commit()

    session.add(
        AttemptTracker(
            scene_id="CH001_SC01",
            chapter_id="CH001",
            step="neutral_draft",
            status="completed",
            source_bundle_id="bundle_CH001_SC01",
            details_json={"row_id": "draft_neutral_CH001_SC01"},
        )
    )
    session.add(
        SceneBundle(
            bundle_id="bundle_CH001_SC01",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            bundle_snapshot_hash="bundle_hash_demo",
            frozen_snapshot_json={"scene_id": "CH001_SC01"},
        )
    )
    session.add(
        SceneDraft(
            row_id="draft_neutral_CH001_SC01",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            stage="neutral_draft",
            content="demo draft",
            source_bundle_id="bundle_CH001_SC01",
            source_bundle_hash="bundle_hash_demo",
        )
    )
    session.add(
        FinalScene(
            row_id="final_scene_CH001_SC01",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            content="demo final",
            status="approved",
            source_bundle_id="bundle_CH001_SC01",
            source_bundle_hash="bundle_hash_demo",
        )
    )
    session.add(
        SceneMemory(
            row_id="scene_memory_CH001_SC01",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            content="demo memory",
            carry_notes_json=[],
            source_bundle_id="bundle_CH001_SC01",
            final_scene_row_id="final_scene_CH001_SC01",
        )
    )
    session.add(
        ChapterMemory(
            row_id="chapter_memory_CH001",
            chapter_id="CH001",
            aggregate_stage="final",
            content="demo chapter memory",
        )
    )
    session.add(
        ChapterRollingNote(
            row_id="rolling_note_CH001_SC01",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            source_scene_memory_row_id="scene_memory_CH001_SC01",
            note_text="demo note",
        )
    )
    session.add(
        HumanReviewEvent(
            event_id="human_review_demo",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            allowed_actions_json=["approve"],
            result_status_map_json={"approve": "approved"},
            default_action="approve",
        )
    )
    session.add(
        StyleObservation(
            row_id="style_observation_STY_DEMO_001_v1",
            style_observation_id="STY_DEMO_001",
            version=1,
            scope="global",
            scope_ref_id="global",
            text="demo style observation",
            source_review_id="review_demo_style_observation",
            active_flag=1,
            runtime_eligible=1,
            runtime_eligibility_basis="vector_ready",
        )
    )
    session.add(
        VersionRegistry(
            object_type="style_observation",
            lineage_key="STY_DEMO_001",
            version=1,
            physical_row_id="style_observation_STY_DEMO_001_v1",
            alias_scope="style_observation:global:global",
            materialize_status="succeeded",
            reindex_status="succeeded",
            verify_status="succeeded",
        )
    )
    session.add(
        ReindexJob(
            job_id="reindex_review_demo_style_observation",
            review_id="review_demo_style_observation",
            status="succeeded",
            object_type="style_observation",
            alias_scope="style_observation:global:global",
            target_snapshot_version="snapshot__style_observation_STY_DEMO_001_v1",
            target_embedding_version="embed__style_observation_STY_DEMO_001_v1",
        )
    )
    session.add(
        VerifyJob(
            job_id="verify_review_demo_style_observation",
            review_id="review_demo_style_observation",
            status="succeeded",
            object_type="style_observation",
            alias_scope="style_observation:global:global",
            target_snapshot_version="snapshot__style_observation_STY_DEMO_001_v1",
            target_embedding_version="embed__style_observation_STY_DEMO_001_v1",
        )
    )
    session.add(
        VectorAliasRegistry(
            alias_scope="style_observation:global:global",
            object_type="style_observation",
            scope="global",
            scope_ref_id="global",
            collection_family="style_observation_global_global",
            active_alias="style_observation_global_global__candidate__style_observation_STY_DEMO_001_v1",
            candidate_alias=None,
            active_snapshot_version="snapshot__style_observation_STY_DEMO_001_v1",
            candidate_snapshot_version=None,
            active_embedding_version="embed__style_observation_STY_DEMO_001_v1",
            candidate_embedding_version=None,
            verify_status="succeeded",
            sample_query_success=1,
        )
    )
    session.commit()

    seed_demo(session)
    session.commit()

    assert _count_rows(session, AttemptTracker) == 0
    assert _count_rows(session, SceneBundle) == 0
    assert _count_rows(session, SceneDraft) == 0
    assert _count_rows(session, FinalScene) == 0
    assert _count_rows(session, SceneMemory) == 0
    assert _count_rows(session, ChapterMemory) == 0
    assert _count_rows(session, ChapterRollingNote) == 0
    assert _count_rows(session, HumanReviewEvent) == 0
    assert _count_rows(session, StyleObservation) == 0
    assert _count_rows(session, VersionRegistry) == 0
    assert _count_rows(session, ReindexJob) == 0
    assert _count_rows(session, VerifyJob) == 0
    assert session.get(VectorAliasRegistry, "style_observation:global:global") is None


def test_seed_demo_review_can_verify_and_release_with_memory_backend(client, session) -> None:
    seed_demo(session)
    session.commit()

    run_scene = client.post(
        "/api/v1/scenes/CH001_SC01/run/full",
        headers={
            "X-Idempotency-Key": "seed-demo-run-scene",
            "X-Operator-Ref": "ops.seed-demo",
        },
    )
    assert run_scene.status_code == 200

    approved = client.post(
        "/api/v1/review-items/review_demo_style_observation/approve",
        headers={
            "X-Idempotency-Key": "seed-demo-approve-review",
            "X-Operator-Ref": "ops.seed-demo",
        },
    )
    assert approved.status_code == 200

    verify = client.post(
        "/api/v1/index/verify/verify_review_demo_style_observation/retry",
        headers={
            "X-Idempotency-Key": "seed-demo-verify-review",
            "X-Operator-Ref": "ops.seed-demo",
        },
    )
    assert verify.status_code == 200

    released = client.post(
        "/api/v1/review-items/review_demo_style_observation/release",
        headers={
            "X-Idempotency-Key": "seed-demo-release-review",
            "X-Operator-Ref": "ops.seed-demo",
        },
    )
    assert released.status_code == 200

    alias = session.get(VectorAliasRegistry, "style_observation:global:global")
    assert alias is not None
    assert alias.active_alias == "style_observation_global_global__candidate__style_observation_STY_DEMO_001_v1"
    assert alias.candidate_alias is None
