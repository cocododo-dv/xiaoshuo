from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from novel_system.db.models import (
    HumanReviewEvent,
    IdempotencyKey,
    OperationLog,
    ReconcileFault,
    ReindexJob,
    ReviewItem,
    StyleObservation,
    VectorAliasRegistry,
    VerifyJob,
    VersionRegistry,
)
from novel_system.services.idempotency import canonical_request_hash
from novel_system.services.vector_store import InMemoryVectorStore
from .test_orchestrator_flow import seed_story


import pytest as _pytest_ap
from tests.real_llm_fakes import install_online_pipeline as _install_online_pipeline


@_pytest_ap.fixture(autouse=True)
def _auto_online_pipeline(monkeypatch):
    """假生成已退役：给场景管线未显式注入的子服务兜底在线记账替身。"""
    _install_online_pipeline(monkeypatch)



def test_index_jobs_expose_runtime_diagnostics(client, session) -> None:
    session.add(
        ReindexJob(
            job_id="reindex_job_diag",
            review_id="review_diag_reindex",
            status="failed",
            object_type="style_observation",
            alias_scope="style_observation:global:global",
            target_snapshot_version="snapshot__style_observation_STY_DIAG_REINDEX_v1",
            target_embedding_version="embed__style_observation_STY_DIAG_REINDEX_v1",
            worker_id="reindex-worker-1",
            attempt_no=2,
            heartbeat_at="2026-04-09T16:00:00+00:00",
            lease_expires_at="2026-04-09T16:03:00+00:00",
            started_at="2026-04-09T15:59:00+00:00",
            finished_at="2026-04-09T16:01:00+00:00",
            error_text="job target no longer matches current candidate",
        )
    )
    session.add(
        VerifyJob(
            job_id="verify_job_diag",
            review_id="review_diag_verify",
            status="failed",
            object_type="style_observation",
            alias_scope="style_observation:global:global",
            target_snapshot_version="snapshot__style_observation_STY_DIAG_VERIFY_v1",
            target_embedding_version="embed__style_observation_STY_DIAG_VERIFY_v1",
            worker_id="verify-worker-2",
            attempt_no=3,
            heartbeat_at="2026-04-09T16:04:00+00:00",
            lease_expires_at="2026-04-09T16:07:00+00:00",
            started_at="2026-04-09T16:02:00+00:00",
            finished_at="2026-04-09T16:05:00+00:00",
            error_text="candidate alias verify failed",
        )
    )
    session.commit()

    response = client.get("/api/v1/index/jobs")

    assert response.status_code == 200
    items = {item["job_id"]: item for item in response.json()["data"]["items"]}
    assert items["reindex_job_diag"]["target_snapshot_version"] == "snapshot__style_observation_STY_DIAG_REINDEX_v1"
    assert items["reindex_job_diag"]["target_embedding_version"] == "embed__style_observation_STY_DIAG_REINDEX_v1"
    assert items["reindex_job_diag"]["worker_id"] == "reindex-worker-1"
    assert items["reindex_job_diag"]["attempt_no"] == 2
    assert items["reindex_job_diag"]["heartbeat_at"] == "2026-04-09T16:00:00+00:00"
    assert items["reindex_job_diag"]["lease_expires_at"] == "2026-04-09T16:03:00+00:00"
    assert items["reindex_job_diag"]["error_text"] == "job target no longer matches current candidate"
    assert items["verify_job_diag"]["error_text"] == "candidate alias verify failed"


def test_alias_scope_exposes_latest_alias_mismatch_fault_summary(client, session) -> None:
    session.add(
        VectorAliasRegistry(
            alias_scope="style_observation:global:global",
            object_type="style_observation",
            scope="global",
            scope_ref_id="global",
            collection_family="style_observation_global_global",
            active_alias="style_observation_global_global__candidate__style_observation_STY_ACTIVE_v1",
            candidate_alias=None,
            active_snapshot_version="snapshot__style_observation_STY_ACTIVE_v1",
            candidate_snapshot_version=None,
            active_embedding_version="embed__style_observation_STY_ACTIVE_v1",
            candidate_embedding_version=None,
            verify_status="failed",
            sample_query_success=0,
        )
    )
    session.add(
        ReconcileFault(
            fault_scope="alias_mismatch",
            severity="warning",
            object_ref="style_observation:global:global",
            details_json={"candidate_alias": "old_candidate_alias"},
            created_at="2026-04-09T15:00:00+00:00",
        )
    )
    session.add(
        ReconcileFault(
            fault_scope="alias_mismatch",
            severity="blocking",
            object_ref="style_observation:global:global",
            details_json={
                "candidate_alias": "style_observation_global_global__candidate__style_observation_STY_NEW_v1",
                "approved_row_id": "style_observation_STY_NEW_v1",
            },
            created_at="2026-04-09T16:00:00+00:00",
        )
    )
    session.add(
        ReconcileFault(
            fault_scope="other_fault",
            severity="blocking",
            object_ref="style_observation:global:global",
            details_json={"ignored": True},
            created_at="2026-04-09T17:00:00+00:00",
        )
    )
    session.commit()

    response = client.get(
        "/api/v1/index/alias-scopes",
        params={"object_type": "style_observation", "scope": "global", "scope_ref_id": "global"},
    )

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 1
    data = items[0]
    assert data["collection_family"] == "style_observation_global_global"
    assert data["sample_query_success"] is False
    assert data["recent_fault_summary"] == {
        "fault_scope": "alias_mismatch",
        "severity": "blocking",
        "object_ref": "style_observation:global:global",
        "details_json": {
            "candidate_alias": "style_observation_global_global__candidate__style_observation_STY_NEW_v1",
            "approved_row_id": "style_observation_STY_NEW_v1",
        },
        "created_at": "2026-04-09T16:00:00+00:00",
    }


def test_runtime_ledger_exposes_latest_recovery_followup_receipt_and_timeline(client, session) -> None:
    session.add(
        OperationLog(
            event_type="runtime_job_reclaimed",
            object_type="runtime_activity",
            object_ref="verify_job_reclaimable",
            payload_json={
                "actor_ref": "system/recovery_sweep",
                "summary": "reclaimed stale verify lease",
                "job_type": "verify",
                "job_id": "verify_job_reclaimable",
                "alias_scope": "style_observation:global:global",
            },
            created_at="2026-04-10T01:20:00+00:00",
        )
    )
    session.add(
        OperationLog(
            event_type="runtime_due_promotion",
            object_type="runtime_activity",
            object_ref="style_observation_STY_RELEASED_v1",
            payload_json={
                "actor_ref": "system/due_promotion",
                "summary": "promoted verified future-effective candidate",
                "review_id": "review_style_released",
                "alias_scope": "style_observation:global:global",
            },
            created_at="2026-04-10T01:40:00+00:00",
        )
    )
    session.add(
        OperationLog(
            event_type="human_review_action",
            object_type="human_review_event",
            object_ref="human_review_idempotency_recovery_approve-review-stale",
            payload_json={
                "actor_ref": "ops.duwei",
                "action": "retry_verify",
                "status_before": "needs_followup",
                "status_after": "needs_followup",
                "resolution_reason": "verify succeeded but review still awaits manual release",
                "linked_target": {
                    "target_type": "review_item",
                    "target_id": "review_style_pending",
                    "target_ref": "review_item:review_style_pending",
                },
                "followup_target": {
                    "target_type": "review_item",
                    "target_id": "review_style_pending",
                    "target_ref": "review_item:review_style_pending",
                },
                "replay_target": {
                    "target_type": "verify_job",
                    "target_id": "verify_review_style_pending",
                    "target_ref": "verify_job:verify_review_style_pending",
                },
            },
            created_at="2026-04-10T01:32:00+00:00",
        )
    )
    session.add(
        HumanReviewEvent(
            event_id="human_review_idempotency_recovery_release-review-stale",
            object_ref="release-review-stale",
            event_source="idempotency_recovery",
            priority="high",
            status="resolved",
            allowed_actions_json=["inspect"],
            result_status_map_json={"inspect": "resolved"},
            details_json={
                "linked_target_type": "review_item",
                "linked_target_id": "review_style_released",
                "linked_target_ref": "review_item:review_style_released",
                "resolution_reason": "review released and active alias promoted",
                "last_action": "release_review",
                "last_action_at": "2026-04-10T01:35:00+00:00",
                "last_action_status": "resolved",
                "last_actor_ref": "ops.duwei",
                "last_replay_result": {"review_id": "review_style_released", "released": True},
            },
            default_action="inspect",
            created_at="2026-04-10T01:00:00+00:00",
        )
    )
    session.add(
        HumanReviewEvent(
            event_id="human_review_idempotency_recovery_approve-review-stale",
            object_ref="approve-review-stale",
            event_source="idempotency_recovery",
            priority="high",
            status="needs_followup",
            allowed_actions_json=["inspect", "retry_verify"],
            result_status_map_json={"inspect": "needs_followup", "retry_verify": "needs_followup"},
            details_json={
                "linked_target_type": "review_item",
                "linked_target_id": "review_style_pending",
                "linked_target_ref": "review_item:review_style_pending",
                "resolution_reason": "review approved; verify job is ready to run",
                "followup_action": "retry_verify",
                "followup_target_type": "verify_job",
                "followup_target_id": "verify_review_style_pending",
                "followup_target_ref": "verify_job:verify_review_style_pending",
                "last_action": "retry_request",
                "last_action_at": "2026-04-10T01:30:00+00:00",
                "last_action_status": "needs_followup",
                "last_actor_ref": "ops.duwei",
                "last_replay_result": {"review_id": "review_style_pending", "materialize_status": "succeeded"},
            },
            default_action="retry_verify",
            created_at="2026-04-10T00:55:00+00:00",
        )
    )
    session.add(
        HumanReviewEvent(
            event_id="human_review_manual_scene",
            object_ref="CH001_SC01",
            event_source="manual_scene_review",
            priority="normal",
            status="open",
            allowed_actions_json=["inspect"],
            result_status_map_json={"inspect": "open"},
            details_json={},
            default_action="inspect",
            created_at="2026-04-10T02:00:00+00:00",
        )
    )
    session.commit()

    response = client.get("/api/v1/index/runtime-ledger")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["latest_recovery_action_receipt"] == {
        "event_id": "human_review_idempotency_recovery_release-review-stale",
        "event_source": "idempotency_recovery",
        "status": "resolved",
        "action": "release_review",
        "action_at": "2026-04-10T01:35:00+00:00",
        "actor_ref": "ops.duwei",
        "object_ref": "release-review-stale",
        "linked_target": {
            "target_type": "review_item",
            "target_id": "review_style_released",
            "target_ref": "review_item:review_style_released",
        },
        "linked_target_ref": "review_item:review_style_released",
        "resolution_reason": "review released and active alias promoted",
        "followup_action": None,
        "followup_target": None,
        "followup_target_ref": None,
        "replay_result": {"review_id": "review_style_released", "released": True},
        "replay_target": {
            "target_type": "review_item",
            "target_id": "review_style_released",
            "target_ref": "review_item:review_style_released",
        },
    }
    assert [item["event_id"] for item in data["recovery_timeline_items"]] == [
        "human_review_idempotency_recovery_release-review-stale",
        "human_review_idempotency_recovery_approve-review-stale",
    ]
    assert data["recovery_timeline_items"][0]["last_action"] == "release_review"
    assert data["recovery_timeline_items"][0]["linked_target"] == {
        "target_type": "review_item",
        "target_id": "review_style_released",
        "target_ref": "review_item:review_style_released",
    }
    assert data["recovery_timeline_items"][0]["linked_target_ref"] == "review_item:review_style_released"
    assert data["recovery_timeline_items"][0]["replay_target"] == {
        "target_type": "review_item",
        "target_id": "review_style_released",
        "target_ref": "review_item:review_style_released",
    }
    assert data["recovery_timeline_items"][1]["followup_action"] == "retry_verify"
    assert data["recovery_timeline_items"][1]["followup_target"] == {
        "target_type": "verify_job",
        "target_id": "verify_review_style_pending",
        "target_ref": "verify_job:verify_review_style_pending",
    }
    assert data["recovery_timeline_items"][1]["followup_target_ref"] == "verify_job:verify_review_style_pending"
    assert data["system_runtime_timeline_items"] == [
        {
            "operation_id": 2,
            "event_type": "runtime_due_promotion",
            "object_ref": "style_observation_STY_RELEASED_v1",
            "actor_ref": "system/due_promotion",
            "summary": "promoted verified future-effective candidate",
            "created_at": "2026-04-10T01:40:00+00:00",
            "target_refs": [
                {
                    "target_type": "review_item",
                    "target_id": "review_style_released",
                    "target_ref": "review_item:review_style_released",
                }
            ],
            "payload_json": {
                "actor_ref": "system/due_promotion",
                "summary": "promoted verified future-effective candidate",
                "review_id": "review_style_released",
                "alias_scope": "style_observation:global:global",
            },
        },
        {
            "operation_id": 1,
            "event_type": "runtime_job_reclaimed",
            "object_ref": "verify_job_reclaimable",
            "actor_ref": "system/recovery_sweep",
            "summary": "reclaimed stale verify lease",
            "created_at": "2026-04-10T01:20:00+00:00",
            "target_refs": [
                {
                    "target_type": "verify_job",
                    "target_id": "verify_job_reclaimable",
                    "target_ref": "verify_job:verify_job_reclaimable",
                }
            ],
            "payload_json": {
                "actor_ref": "system/recovery_sweep",
                "summary": "reclaimed stale verify lease",
                "job_type": "verify",
                "job_id": "verify_job_reclaimable",
                "alias_scope": "style_observation:global:global",
            },
        },
    ]
    assert data["operator_action_timeline_items"] == [
        {
            "operation_id": 3,
            "event_type": "human_review_action",
            "event_id": "human_review_idempotency_recovery_approve-review-stale",
            "object_ref": "human_review_idempotency_recovery_approve-review-stale",
            "actor_ref": "ops.duwei",
            "action": "retry_verify",
            "status_before": "needs_followup",
            "status_after": "needs_followup",
            "resolution_reason": "verify succeeded but review still awaits manual release",
            "created_at": "2026-04-10T01:32:00+00:00",
            "target_refs": [
                {
                    "target_type": "human_review_event",
                    "target_id": "human_review_idempotency_recovery_approve-review-stale",
                    "target_ref": "human_review_event:human_review_idempotency_recovery_approve-review-stale",
                },
                {
                    "target_type": "review_item",
                    "target_id": "review_style_pending",
                    "target_ref": "review_item:review_style_pending",
                },
                {
                    "target_type": "verify_job",
                    "target_id": "verify_review_style_pending",
                    "target_ref": "verify_job:verify_review_style_pending",
                },
            ],
            "payload_json": {
                "actor_ref": "ops.duwei",
                "action": "retry_verify",
                "status_before": "needs_followup",
                "status_after": "needs_followup",
                "resolution_reason": "verify succeeded but review still awaits manual release",
                "linked_target": {
                    "target_type": "review_item",
                    "target_id": "review_style_pending",
                    "target_ref": "review_item:review_style_pending",
                },
                "followup_target": {
                    "target_type": "review_item",
                    "target_id": "review_style_pending",
                    "target_ref": "review_item:review_style_pending",
                },
                "replay_target": {
                    "target_type": "verify_job",
                    "target_id": "verify_review_style_pending",
                    "target_ref": "verify_job:verify_review_style_pending",
                },
            },
        }
    ]
    released_group = next(
        item for item in data["target_activity_groups"] if item["target"]["target_ref"] == "review_item:review_style_released"
    )
    assert released_group == {
        "target": {
            "target_type": "review_item",
            "target_id": "review_style_released",
            "target_ref": "review_item:review_style_released",
        },
        "latest_at": "2026-04-10T01:40:00+00:00",
        "activity_count": 2,
        "sources": ["system_runtime", "recovery_timeline"],
        "latest_activity_key": "system_runtime:2",
        "activity_items": [
            {
                "activity_key": "system_runtime:2",
                "source": "system_runtime",
                "timestamp": "2026-04-10T01:40:00+00:00",
                "actor_ref": "system/due_promotion",
                "label": "runtime_due_promotion",
                "status": None,
                "summary": "promoted verified future-effective candidate",
                "object_ref": "style_observation_STY_RELEASED_v1",
                "target_refs": [
                    {
                        "target_type": "review_item",
                        "target_id": "review_style_released",
                        "target_ref": "review_item:review_style_released",
                    }
                ],
            },
            {
                "activity_key": "recovery_timeline:human_review_idempotency_recovery_release-review-stale",
                "source": "recovery_timeline",
                "timestamp": "2026-04-10T01:35:00+00:00",
                "actor_ref": "ops.duwei",
                "label": "release_review",
                "status": "resolved",
                "summary": "review released and active alias promoted",
                "object_ref": "release-review-stale",
                "target_refs": [
                    {
                        "target_type": "review_item",
                        "target_id": "review_style_released",
                        "target_ref": "review_item:review_style_released",
                    }
                ],
            },
        ],
    }
    pending_group = next(
        item for item in data["target_activity_groups"] if item["target"]["target_ref"] == "review_item:review_style_pending"
    )
    assert pending_group["latest_at"] == "2026-04-10T01:32:00+00:00"
    assert pending_group["activity_count"] == 2
    assert pending_group["sources"] == ["operator_action", "recovery_timeline"]
    assert [item["source"] for item in pending_group["activity_items"]] == ["operator_action", "recovery_timeline"]


def test_human_review_event_detail_exposes_structured_targets(client, session) -> None:
    # HumanReviewEvent now enforces its scene/chapter foreign keys; this test
    # exercises response shaping, so seed the referenced target explicitly.
    seed_story(client, session)
    session.add(
        HumanReviewEvent(
            event_id="human_review_manual_scene_structured",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            object_ref="CH001_SC01",
            event_source="manual_scene_review",
            priority="normal",
            status="open",
            allowed_actions_json=["inspect"],
            result_status_map_json={"inspect": "open"},
            details_json={},
            default_action="inspect",
        )
    )
    session.add(
        HumanReviewEvent(
            event_id="human_review_idempotency_recovery_structured",
            object_ref="approve-review-structured",
            event_source="idempotency_recovery",
            priority="high",
            status="needs_followup",
            allowed_actions_json=["inspect", "retry_verify"],
            result_status_map_json={"inspect": "needs_followup", "retry_verify": "needs_followup"},
            details_json={
                "linked_target_type": "review_item",
                "linked_target_id": "review_structured",
                "linked_target_ref": "review_item:review_structured",
                "followup_target_type": "verify_job",
                "followup_target_id": "verify_review_structured",
                "followup_target_ref": "verify_job:verify_review_structured",
            },
            default_action="retry_verify",
        )
    )
    session.commit()

    response = client.get("/api/v1/human-review-events")

    assert response.status_code == 200
    items = {item["event_id"]: item for item in response.json()["data"]["items"]}
    assert items["human_review_manual_scene_structured"]["linked_target"] == {
        "target_type": "scene_card",
        "target_id": "CH001_SC01",
        "target_ref": "scene_card:CH001_SC01",
    }
    assert items["human_review_manual_scene_structured"]["followup_target"] is None
    assert items["human_review_idempotency_recovery_structured"]["linked_target"] == {
        "target_type": "review_item",
        "target_id": "review_structured",
        "target_ref": "review_item:review_structured",
    }
    assert items["human_review_idempotency_recovery_structured"]["followup_target"] == {
        "target_type": "verify_job",
        "target_id": "verify_review_structured",
        "target_ref": "verify_job:verify_review_structured",
    }


def test_recovery_sweep_exposes_reclaimed_and_failed_job_summaries(client, session) -> None:
    session.add(
        VerifyJob(
            job_id="verify_job_reclaimable",
            review_id="review_reclaimable",
            status="running",
            object_type="style_observation",
            alias_scope="style_observation:global:global",
            target_snapshot_version="snapshot__style_observation_STY_RECLAIMABLE_v1",
            target_embedding_version="embed__style_observation_STY_RECLAIMABLE_v1",
            worker_id="verify-worker-stale",
            attempt_no=2,
            heartbeat_at="2026-04-09T15:00:00+00:00",
            lease_expires_at="2000-01-01T00:00:00+00:00",
            started_at="2026-04-09T14:59:00+00:00",
            finished_at=None,
            error_text=None,
        )
    )
    session.add(
        VerifyJob(
            job_id="verify_job_failed_recent",
            review_id="review_failed_recent",
            status="failed",
            object_type="style_observation",
            alias_scope="style_observation:global:global",
            target_snapshot_version="snapshot__style_observation_STY_FAILED_v1",
            target_embedding_version="embed__style_observation_STY_FAILED_v1",
            worker_id="verify-worker-failed",
            attempt_no=3,
            heartbeat_at="2026-04-09T16:04:00+00:00",
            lease_expires_at="2026-04-09T16:07:00+00:00",
            started_at="2026-04-09T16:02:00+00:00",
            finished_at="2026-04-09T16:05:00+00:00",
            error_text="candidate alias verify failed",
        )
    )
    session.commit()

    response = client.post(
        "/api/v1/runtime/recovery/sweep",
        headers={
            "X-Idempotency-Key": "recovery-sweep-diagnostics",
            "X-Operator-Ref": "ops.duwei",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["actor_ref"] == "ops.duwei"
    assert data["reclaimed_jobs"] == 1
    assert data["reclaimed_job_summaries"] == [
        {
            "job_id": "verify_job_reclaimable",
            "job_type": "verify",
            "alias_scope": "style_observation:global:global",
            "target": {
                "target_type": "verify_job",
                "target_id": "verify_job_reclaimable",
                "target_ref": "verify_job:verify_job_reclaimable",
            },
            "previous_worker_id": "verify-worker-stale",
            "attempt_no": 2,
            "previous_lease_expires_at": "2000-01-01T00:00:00+00:00",
        }
    ]
    logs = session.execute(
        select(OperationLog)
        .where(OperationLog.object_type == "idempotency_key", OperationLog.object_ref == "recovery-sweep-diagnostics")
        .order_by(OperationLog.operation_id.asc())
    ).scalars().all()
    assert logs[0].payload_json["actor_ref"] == "ops.duwei"
    assert logs[-1].payload_json["actor_ref"] == "ops.duwei"
    runtime_logs = session.execute(
        select(OperationLog)
        .where(OperationLog.object_type == "runtime_activity")
        .order_by(OperationLog.operation_id.asc())
    ).scalars().all()
    assert runtime_logs[0].event_type == "runtime_job_reclaimed"
    assert runtime_logs[0].payload_json["actor_ref"] == "system/recovery_sweep"
    assert runtime_logs[0].payload_json["job_id"] == "verify_job_reclaimable"
    assert data["failed_jobs"] == 1
    assert data["failed_job_summaries"] == [
        {
            "job_id": "verify_job_failed_recent",
            "job_type": "verify",
            "alias_scope": "style_observation:global:global",
            "target": {
                "target_type": "verify_job",
                "target_id": "verify_job_failed_recent",
                "target_ref": "verify_job:verify_job_failed_recent",
            },
            "error_text": "candidate alias verify failed",
            "finished_at": "2026-04-09T16:05:00+00:00",
        }
    ]

    session.expire_all()
    reclaimed = session.get(VerifyJob, "verify_job_reclaimable")
    assert reclaimed is not None
    assert reclaimed.status == "queued"
    assert reclaimed.worker_id is None
    assert reclaimed.heartbeat_at is None
    assert reclaimed.lease_expires_at is None


def test_recovery_sweep_marks_stale_idempotency_keys_failed_and_creates_human_review_event(client, session) -> None:
    session.add(
        IdempotencyKey(
            idempotency_key="approve-review-stale",
            request_hash="request-hash-stale",
            status="started",
            response_json=None,
            worker_id="http",
            attempt_no=2,
            heartbeat_at="2026-04-09T16:00:00+00:00",
            lease_expires_at="2000-01-01T00:00:00+00:00",
        )
    )
    session.add(
        OperationLog(
            event_type="idempotency_started",
            object_type="idempotency_key",
            object_ref="approve-review-stale",
            payload_json={
                "request_hash": "request-hash-stale",
                "request_method": "POST",
                "request_path_template": "/api/v1/review-items/{review_id}/approve",
                "request_payload": {"review_id": "review_stale"},
                "attempt_no": 2,
            },
        )
    )
    session.commit()

    response = client.post(
        "/api/v1/runtime/recovery/sweep",
        headers={"X-Idempotency-Key": "recovery-sweep-idempotency-diagnostics"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reclaimed_idempotency_keys"] == 1
    assert data["failed_idempotency_keys"] == 1
    assert data["reclaimed_idempotency_key_summaries"] == [
        {
            "idempotency_key": "approve-review-stale",
            "previous_worker_id": "http",
            "attempt_no": 2,
            "previous_lease_expires_at": "2000-01-01T00:00:00+00:00",
        }
    ]
    assert data["created_human_review_events"] == 1
    assert data["created_human_review_event_ids"] == [
        "human_review_idempotency_recovery_approve-review-stale"
    ]
    assert data["created_human_review_event_targets"] == [
        {
            "event_id": "human_review_idempotency_recovery_approve-review-stale",
            "target": {
                "target_type": "human_review_event",
                "target_id": "human_review_idempotency_recovery_approve-review-stale",
                "target_ref": "human_review_event:human_review_idempotency_recovery_approve-review-stale",
            },
        }
    ]

    session.expire_all()
    stale_key = session.get(IdempotencyKey, "approve-review-stale")
    assert stale_key is not None
    assert stale_key.status == "failed"
    assert stale_key.worker_id is None
    assert stale_key.heartbeat_at is None
    assert stale_key.lease_expires_at is None

    event = session.get(HumanReviewEvent, "human_review_idempotency_recovery_approve-review-stale")
    assert event is not None
    assert event.event_source == "idempotency_recovery"
    assert event.priority == "high"
    assert event.status == "open"
    assert event.object_ref == "approve-review-stale"
    assert event.allowed_actions_json == ["inspect", "retry_request"]
    assert event.default_action == "inspect"
    assert event.details_json == {
        "idempotency_key": "approve-review-stale",
        "request_hash": "request-hash-stale",
        "request_method": "POST",
        "request_path_template": "/api/v1/review-items/{review_id}/approve",
        "request_payload": {"review_id": "review_stale"},
        "created_by_ref": "system/recovery_sweep",
        "created_reason": "stale_idempotency_key_recovered",
        "linked_target_type": "review_item",
        "linked_target_id": "review_stale",
        "linked_target_ref": "review_item:review_stale",
        "attempt_no": 2,
        "previous_worker_id": "http",
        "previous_lease_expires_at": "2000-01-01T00:00:00+00:00",
    }
    runtime_logs = session.execute(
        select(OperationLog)
        .where(OperationLog.object_type == "runtime_activity")
        .order_by(OperationLog.operation_id.asc())
    ).scalars().all()
    assert runtime_logs[-1].event_type == "runtime_recovery_event_created"
    assert runtime_logs[-1].payload_json["actor_ref"] == "system/recovery_sweep"
    assert runtime_logs[-1].payload_json["event_id"] == "human_review_idempotency_recovery_approve-review-stale"
    assert runtime_logs[-1].payload_json["idempotency_key"] == "approve-review-stale"


def test_human_review_retry_request_replays_original_approve_action(client, session) -> None:
    payload = {"review_id": "review_retry_request"}
    request_hash = canonical_request_hash("POST", "/api/v1/review-items/{review_id}/approve", payload)
    session.add(
        ReviewItem(
            review_id="review_retry_request",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            item_type="style_observation",
            candidate_text="retry the stranded approve request",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STY_RETRY_REQUEST",
                "text": "retry the stranded approve request",
            },
            active_on_approve=0,
        )
    )
    session.add(
        IdempotencyKey(
            idempotency_key="approve-review-retry-request",
            request_hash=request_hash,
            status="failed",
            response_json=None,
            worker_id=None,
            attempt_no=2,
            heartbeat_at=None,
            lease_expires_at=None,
        )
    )
    session.add(
        HumanReviewEvent(
            event_id="human_review_idempotency_recovery_approve-review-retry-request",
            object_ref="approve-review-retry-request",
            event_source="idempotency_recovery",
            priority="high",
            status="open",
            allowed_actions_json=["inspect", "retry_request"],
            result_status_map_json={"inspect": "open", "retry_request": "pending"},
            details_json={
                "idempotency_key": "approve-review-retry-request",
                "request_hash": request_hash,
                "request_method": "POST",
                "request_path_template": "/api/v1/review-items/{review_id}/approve",
                "request_payload": payload,
                "attempt_no": 2,
                "previous_worker_id": "http",
                "previous_lease_expires_at": "2000-01-01T00:00:00+00:00",
            },
            default_action="inspect",
        )
    )
    session.commit()

    response = client.post(
        "/api/v1/human-review-events/human_review_idempotency_recovery_approve-review-retry-request/actions",
        json={"action": "retry_request"},
        headers={
            "X-Idempotency-Key": "human-review-action-retry-request",
            "X-Operator-Ref": "ops.duwei",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["event_id"] == "human_review_idempotency_recovery_approve-review-retry-request"
    assert data["action"] == "retry_request"
    assert data["actor_ref"] == "ops.duwei"
    assert data["status"] == "needs_followup"
    assert data["linked_target_ref"] == "review_item:review_retry_request"
    assert data["linked_target"] == {
        "target_type": "review_item",
        "target_id": "review_retry_request",
        "target_ref": "review_item:review_retry_request",
    }
    assert data["resolution_reason"] == "review approved; verify job is ready to run"
    assert data["followup_action"] == "retry_verify"
    assert data["followup_target_ref"] == "verify_job:verify_review_retry_request"
    assert data["followup_target"] == {
        "target_type": "verify_job",
        "target_id": "verify_review_retry_request",
        "target_ref": "verify_job:verify_review_retry_request",
    }
    assert data["replay_result"]["review_id"] == "review_retry_request"
    assert data["replay_result"]["materialize_status"] == "succeeded"
    assert data["replay_target"] == {
        "target_type": "review_item",
        "target_id": "review_retry_request",
        "target_ref": "review_item:review_retry_request",
    }

    session.expire_all()
    event = session.get(HumanReviewEvent, "human_review_idempotency_recovery_approve-review-retry-request")
    assert event is not None
    assert event.status == "needs_followup"
    assert event.details_json["last_action"] == "retry_request"
    assert datetime.fromisoformat(event.details_json["last_action_at"])
    assert event.details_json["last_actor_ref"] == "ops.duwei"
    assert event.details_json["last_action_status"] == "needs_followup"
    assert event.details_json["linked_target_type"] == "review_item"
    assert event.details_json["linked_target_id"] == "review_retry_request"
    assert event.details_json["linked_target_ref"] == "review_item:review_retry_request"
    assert event.details_json["resolution_reason"] == "review approved; verify job is ready to run"
    assert event.details_json["followup_action"] == "retry_verify"
    assert event.details_json["followup_target_type"] == "verify_job"
    assert event.details_json["followup_target_id"] == "verify_review_retry_request"
    assert event.details_json["followup_target_ref"] == "verify_job:verify_review_retry_request"
    assert event.allowed_actions_json == ["inspect", "retry_verify"]
    assert event.default_action == "retry_verify"
    history = event.details_json["action_history"]
    assert len(history) == 1
    assert history[0]["action"] == "retry_request"
    assert history[0]["actor_ref"] == "ops.duwei"
    assert datetime.fromisoformat(history[0]["action_at"])
    assert history[0]["status_after"] == "needs_followup"
    assert history[0]["linked_target_ref"] == "review_item:review_retry_request"
    assert history[0]["resolution_reason"] == "review approved; verify job is ready to run"
    assert history[0]["replay_result"]["review_id"] == "review_retry_request"
    assert history[0]["replay_result"]["materialize_status"] == "succeeded"

    logs = session.execute(
        select(OperationLog)
        .where(OperationLog.object_type == "human_review_event", OperationLog.object_ref == event.event_id)
        .order_by(OperationLog.operation_id.asc())
    ).scalars().all()
    assert len(logs) == 1
    assert logs[0].event_type == "human_review_action"
    assert logs[0].payload_json["action"] == "retry_request"
    assert logs[0].payload_json["actor_ref"] == "ops.duwei"
    assert logs[0].payload_json["status_after"] == "needs_followup"
    assert logs[0].payload_json["linked_target_ref"] == "review_item:review_retry_request"
    assert logs[0].payload_json["linked_target"] == {
        "target_type": "review_item",
        "target_id": "review_retry_request",
        "target_ref": "review_item:review_retry_request",
    }
    assert logs[0].payload_json["followup_target"] == {
        "target_type": "verify_job",
        "target_id": "verify_review_retry_request",
        "target_ref": "verify_job:verify_review_retry_request",
    }
    assert logs[0].payload_json["replay_target"] == {
        "target_type": "review_item",
        "target_id": "review_retry_request",
        "target_ref": "review_item:review_retry_request",
    }
    assert logs[0].payload_json["resolution_reason"] == "review approved; verify job is ready to run"

    review = session.get(ReviewItem, "review_retry_request")
    assert review is not None
    assert review.status == "approved"
    assert review.materialize_status == "succeeded"
    assert review.approved_item_row_id is not None


def test_review_approve_retry_verify_and_release_capture_actor_ref(client, session, monkeypatch) -> None:
    shared_store = InMemoryVectorStore()
    monkeypatch.setattr("novel_system.services.version_manager.get_vector_store", lambda: shared_store)

    session.add(
        ReviewItem(
            review_id="review_actor_ops",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            item_type="style_observation",
            candidate_text="actor-aware operational approval",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STY_ACTOR_OPS",
                "text": "actor-aware operational approval",
            },
            active_on_approve=0,
        )
    )
    session.commit()

    approved = client.post(
        "/api/v1/review-items/review_actor_ops/approve",
        headers={
            "X-Idempotency-Key": "approve-review-actor-ops",
            "X-Operator-Ref": "ops.duwei",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["data"]["actor_ref"] == "ops.duwei"

    verify = client.post(
        "/api/v1/index/verify/verify_review_actor_ops/retry",
        headers={
            "X-Idempotency-Key": "verify-review-actor-ops",
            "X-Operator-Ref": "ops.duwei",
        },
    )
    assert verify.status_code == 200
    assert verify.json()["data"]["actor_ref"] == "ops.duwei"

    release = client.post(
        "/api/v1/review-items/review_actor_ops/release",
        headers={
            "X-Idempotency-Key": "release-review-actor-ops",
            "X-Operator-Ref": "ops.duwei",
        },
    )
    assert release.status_code == 200
    assert release.json()["data"]["actor_ref"] == "ops.duwei"

    approve_logs = session.execute(
        select(OperationLog)
        .where(OperationLog.object_type == "idempotency_key", OperationLog.object_ref == "approve-review-actor-ops")
        .order_by(OperationLog.operation_id.asc())
    ).scalars().all()
    verify_logs = session.execute(
        select(OperationLog)
        .where(OperationLog.object_type == "idempotency_key", OperationLog.object_ref == "verify-review-actor-ops")
        .order_by(OperationLog.operation_id.asc())
    ).scalars().all()
    release_logs = session.execute(
        select(OperationLog)
        .where(OperationLog.object_type == "idempotency_key", OperationLog.object_ref == "release-review-actor-ops")
        .order_by(OperationLog.operation_id.asc())
    ).scalars().all()
    assert approve_logs[0].payload_json["actor_ref"] == "ops.duwei"
    assert approve_logs[-1].payload_json["actor_ref"] == "ops.duwei"
    assert verify_logs[0].payload_json["actor_ref"] == "ops.duwei"
    assert verify_logs[-1].payload_json["actor_ref"] == "ops.duwei"
    assert release_logs[0].payload_json["actor_ref"] == "ops.duwei"
    assert release_logs[-1].payload_json["actor_ref"] == "ops.duwei"


def test_runtime_ledger_persists_review_and_scene_operator_actions(client, session, monkeypatch) -> None:
    seed_story(client, session=session)

    shared_store = InMemoryVectorStore()
    monkeypatch.setattr("novel_system.services.version_manager.get_vector_store", lambda: shared_store)

    session.add(
        ReviewItem(
            review_id="review_operator_runtime_ledger",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            item_type="style_observation",
            candidate_text="persist ordinary operator actions in the runtime ledger",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STY_OPERATOR_LEDGER",
                "text": "persist ordinary operator actions in the runtime ledger",
            },
            active_on_approve=0,
        )
    )
    session.commit()

    approved = client.post(
        "/api/v1/review-items/review_operator_runtime_ledger/approve",
        headers={
            "X-Idempotency-Key": "approve-review-operator-runtime-ledger",
            "X-Operator-Ref": "ops.duwei",
        },
    )
    assert approved.status_code == 200

    verify = client.post(
        "/api/v1/index/verify/verify_review_operator_runtime_ledger/retry",
        headers={
            "X-Idempotency-Key": "verify-review-operator-runtime-ledger",
            "X-Operator-Ref": "ops.duwei",
        },
    )
    assert verify.status_code == 200

    released = client.post(
        "/api/v1/review-items/review_operator_runtime_ledger/release",
        headers={
            "X-Idempotency-Key": "release-review-operator-runtime-ledger",
            "X-Operator-Ref": "ops.duwei",
        },
    )
    assert released.status_code == 200

    ran_scene = client.post(
        "/api/v1/scenes/CH001_SC01/run/full",
        headers={
            "X-Idempotency-Key": "run-scene-operator-runtime-ledger",
            "X-Operator-Ref": "ops.duwei",
        },
    )
    assert ran_scene.status_code == 200

    response = client.get("/api/v1/index/runtime-ledger")

    assert response.status_code == 200
    data = response.json()["data"]
    operator_actions = data["operator_action_timeline_items"]

    approve_action = next(item for item in operator_actions if item["object_ref"] == "review_operator_runtime_ledger" and item["action"] == "approve_review")
    assert approve_action["actor_ref"] == "ops.duwei"
    assert approve_action["target_refs"] == [
        {
            "target_type": "review_item",
            "target_id": "review_operator_runtime_ledger",
            "target_ref": "review_item:review_operator_runtime_ledger",
        },
        {
            "target_type": "reindex_job",
            "target_id": "reindex_review_operator_runtime_ledger",
            "target_ref": "reindex_job:reindex_review_operator_runtime_ledger",
        },
        {
            "target_type": "verify_job",
            "target_id": "verify_review_operator_runtime_ledger",
            "target_ref": "verify_job:verify_review_operator_runtime_ledger",
        },
    ]
    assert approve_action["payload_json"]["request_path_template"] == "/api/v1/review-items/{review_id}/approve"

    release_action = next(item for item in operator_actions if item["object_ref"] == "review_operator_runtime_ledger" and item["action"] == "release_review")
    assert release_action["actor_ref"] == "ops.duwei"
    assert release_action["target_refs"] == [
        {
            "target_type": "review_item",
            "target_id": "review_operator_runtime_ledger",
            "target_ref": "review_item:review_operator_runtime_ledger",
        }
    ]
    assert release_action["payload_json"]["request_path_template"] == "/api/v1/review-items/{review_id}/release"

    verify_action = next(item for item in operator_actions if item["object_ref"] == "verify_review_operator_runtime_ledger" and item["action"] == "retry_verify")
    assert verify_action["actor_ref"] == "ops.duwei"
    assert verify_action["target_refs"] == [
        {
            "target_type": "verify_job",
            "target_id": "verify_review_operator_runtime_ledger",
            "target_ref": "verify_job:verify_review_operator_runtime_ledger",
        },
        {
            "target_type": "review_item",
            "target_id": "review_operator_runtime_ledger",
            "target_ref": "review_item:review_operator_runtime_ledger",
        },
    ]
    assert verify_action["payload_json"]["request_path_template"] == "/api/v1/index/verify/{job_id}/retry"

    scene_action = next(item for item in operator_actions if item["object_ref"] == "CH001_SC01" and item["action"] == "run_scene")
    assert scene_action["actor_ref"] == "ops.duwei"
    assert scene_action["target_refs"] == [
        {
            "target_type": "scene_card",
            "target_id": "CH001_SC01",
            "target_ref": "scene_card:CH001_SC01",
        }
    ]
    assert scene_action["payload_json"]["request_path_template"] == "/api/v1/scenes/{scene_id}/run/full"

    review_group = next(
        item for item in data["target_activity_groups"] if item["target"]["target_ref"] == "review_item:review_operator_runtime_ledger"
    )
    assert "operator_action" in review_group["sources"]
    assert {item["label"] for item in review_group["activity_items"] if item["source"] == "operator_action"} >= {
        "approve_review",
        "release_review",
        "retry_verify",
    }

    scene_group = next(item for item in data["target_activity_groups"] if item["target"]["target_ref"] == "scene_card:CH001_SC01")
    assert scene_group["sources"] == ["operator_action"]
    assert any(item["label"] == "run_scene" for item in scene_group["activity_items"])


def test_runtime_ledger_persists_recovery_and_due_promotion_operator_actions(client, session) -> None:
    approved_row_id = "style_observation_STY_DUE_PROMOTION_OPERATOR_v1"

    session.add(
        VerifyJob(
            job_id="verify_job_recovery_operator",
            review_id="review_recovery_operator",
            status="running",
            object_type="style_observation",
            alias_scope="style_observation:global:global",
            target_snapshot_version="snapshot__style_observation_STY_RECOVERY_OPERATOR_v1",
            target_embedding_version="embed__style_observation_STY_RECOVERY_OPERATOR_v1",
            worker_id="verify-worker-stale",
            attempt_no=2,
            heartbeat_at="2026-04-09T15:00:00+00:00",
            lease_expires_at="2000-01-01T00:00:00+00:00",
            started_at="2026-04-09T14:59:00+00:00",
        )
    )
    session.add(
        ReviewItem(
            review_id="review_due_promotion_operator",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            item_type="style_observation",
            status="approved",
            candidate_text="persist due promotions in the runtime ledger",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STY_DUE_PROMOTION_OPERATOR",
                "text": "persist due promotions in the runtime ledger",
                "effective_at": "2000-01-01T00:00:00+00:00",
            },
            active_on_approve=1,
            materialize_status="succeeded",
            approved_item_row_id=approved_row_id,
            approved_item_id="STY_DUE_PROMOTION_OPERATOR",
        )
    )
    session.add(
        StyleObservation(
            row_id=approved_row_id,
            style_observation_id="STY_DUE_PROMOTION_OPERATOR",
            version=1,
            scope="global",
            scope_ref_id="global",
            text="persist due promotions in the runtime ledger",
            source_review_id="review_due_promotion_operator",
            active_flag=0,
            runtime_eligible=0,
            runtime_eligibility_basis="future_effective",
            effective_at="2000-01-01T00:00:00+00:00",
        )
    )
    session.add(
        VersionRegistry(
            object_type="style_observation",
            lineage_key="STY_DUE_PROMOTION_OPERATOR",
            version=1,
            physical_row_id=approved_row_id,
            alias_scope="style_observation:global:global",
            materialize_status="succeeded",
            reindex_status="succeeded",
            verify_status="succeeded",
        )
    )
    session.add(
        VectorAliasRegistry(
            alias_scope="style_observation:global:global",
            object_type="style_observation",
            scope="global",
            scope_ref_id="global",
            collection_family="style_observation_global_global",
            active_alias="style_observation_global_global__candidate__style_observation_STY_ACTIVE_v1",
            candidate_alias=f"style_observation_global_global__candidate__{approved_row_id}",
            active_snapshot_version="snapshot__style_observation_STY_ACTIVE_v1",
            candidate_snapshot_version=f"snapshot__{approved_row_id}",
            active_embedding_version="embed__style_observation_STY_ACTIVE_v1",
            candidate_embedding_version=f"embed__{approved_row_id}",
            verify_status="succeeded",
            sample_query_success=1,
        )
    )
    session.commit()

    recovery = client.post(
        "/api/v1/runtime/recovery/sweep",
        headers={
            "X-Idempotency-Key": "recovery-operator-runtime-ledger",
            "X-Operator-Ref": "ops.duwei",
        },
    )
    assert recovery.status_code == 200
    assert recovery.json()["data"]["actor_ref"] == "ops.duwei"

    promotions = client.post(
        "/api/v1/runtime/promotions/run-due",
        headers={
            "X-Idempotency-Key": "run-due-promotions-operator-runtime-ledger",
            "X-Operator-Ref": "ops.duwei",
        },
    )
    assert promotions.status_code == 200
    assert promotions.json()["data"]["actor_ref"] == "ops.duwei"

    response = client.get("/api/v1/index/runtime-ledger")

    assert response.status_code == 200
    data = response.json()["data"]
    operator_actions = data["operator_action_timeline_items"]

    recovery_action = next(item for item in operator_actions if item["action"] == "run_recovery_sweep")
    assert recovery_action["actor_ref"] == "ops.duwei"
    assert recovery_action["status_after"] == "completed"
    assert recovery_action["payload_json"]["request_path_template"] == "/api/v1/runtime/recovery/sweep"
    assert recovery_action["payload_json"]["reclaimed_jobs"] == 1
    assert recovery_action["target_refs"] == [
        {
            "target_type": "verify_job",
            "target_id": "verify_job_recovery_operator",
            "target_ref": "verify_job:verify_job_recovery_operator",
        }
    ]

    promotion_action = next(item for item in operator_actions if item["action"] == "run_due_promotions")
    assert promotion_action["actor_ref"] == "ops.duwei"
    assert promotion_action["status_after"] == "completed"
    assert promotion_action["payload_json"]["request_path_template"] == "/api/v1/runtime/promotions/run-due"
    assert promotion_action["payload_json"]["promoted"] == 1
    assert promotion_action["target_refs"] == [
        {
            "target_type": "review_item",
            "target_id": "review_due_promotion_operator",
            "target_ref": "review_item:review_due_promotion_operator",
        }
    ]

    verify_group = next(
        item for item in data["target_activity_groups"] if item["target"]["target_ref"] == "verify_job:verify_job_recovery_operator"
    )
    assert "operator_action" in verify_group["sources"]
    assert any(item["label"] == "run_recovery_sweep" for item in verify_group["activity_items"])

    review_group = next(
        item for item in data["target_activity_groups"] if item["target"]["target_ref"] == "review_item:review_due_promotion_operator"
    )
    assert "operator_action" in review_group["sources"]
    assert any(item["label"] == "run_due_promotions" for item in review_group["activity_items"])


def test_verify_auto_promotion_writes_system_runtime_activity(client, session, monkeypatch) -> None:
    shared_store = InMemoryVectorStore()
    monkeypatch.setattr("novel_system.services.version_manager.get_vector_store", lambda: shared_store)

    session.add(
        ReviewItem(
            review_id="review_auto_promotion_actor",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            item_type="style_observation",
            candidate_text="auto promotion should leave a system activity record",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STY_AUTO_PROMOTION_ACTOR",
                "text": "auto promotion should leave a system activity record",
            },
            active_on_approve=1,
        )
    )
    session.commit()

    approved = client.post(
        "/api/v1/review-items/review_auto_promotion_actor/approve",
        headers={
            "X-Idempotency-Key": "approve-review-auto-promotion-actor",
            "X-Operator-Ref": "ops.duwei",
        },
    )
    assert approved.status_code == 200

    verify = client.post(
        "/api/v1/index/verify/verify_review_auto_promotion_actor/retry",
        headers={
            "X-Idempotency-Key": "verify-review-auto-promotion-actor",
            "X-Operator-Ref": "ops.duwei",
        },
    )
    assert verify.status_code == 200

    runtime_logs = session.execute(
        select(OperationLog)
        .where(OperationLog.object_type == "runtime_activity")
        .order_by(OperationLog.operation_id.asc())
    ).scalars().all()
    assert runtime_logs[-1].event_type == "runtime_auto_promotion"
    assert runtime_logs[-1].payload_json["actor_ref"] == "system/verify_auto_promotion"
    assert runtime_logs[-1].payload_json["review_id"] == "review_auto_promotion_actor"


def test_human_review_retry_verify_exposes_release_review_followup(client, session, monkeypatch) -> None:
    shared_store = InMemoryVectorStore()
    monkeypatch.setattr("novel_system.services.version_manager.get_vector_store", lambda: shared_store)

    payload = {"review_id": "review_followup_verify"}
    request_hash = canonical_request_hash("POST", "/api/v1/review-items/{review_id}/approve", payload)
    session.add(
        ReviewItem(
            review_id="review_followup_verify",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            item_type="style_observation",
            candidate_text="walk the chained followup actions",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STY_FOLLOWUP_VERIFY",
                "text": "walk the chained followup actions",
            },
            active_on_approve=0,
        )
    )
    session.add(
        HumanReviewEvent(
            event_id="human_review_idempotency_recovery_approve-followup-verify",
            object_ref="approve-followup-verify",
            event_source="idempotency_recovery",
            priority="high",
            status="open",
            allowed_actions_json=["inspect", "retry_request"],
            result_status_map_json={"inspect": "open", "retry_request": "pending"},
            details_json={
                "idempotency_key": "approve-followup-verify",
                "request_hash": request_hash,
                "request_method": "POST",
                "request_path_template": "/api/v1/review-items/{review_id}/approve",
                "request_payload": payload,
                "linked_target_type": "review_item",
                "linked_target_id": "review_followup_verify",
                "linked_target_ref": "review_item:review_followup_verify",
            },
            default_action="inspect",
        )
    )
    session.commit()

    prime = client.post(
        "/api/v1/human-review-events/human_review_idempotency_recovery_approve-followup-verify/actions",
        json={"action": "retry_request"},
        headers={"X-Idempotency-Key": "human-review-action-followup-verify-prime"},
    )
    assert prime.status_code == 200

    response = client.post(
        "/api/v1/human-review-events/human_review_idempotency_recovery_approve-followup-verify/actions",
        json={"action": "retry_verify"},
        headers={"X-Idempotency-Key": "human-review-action-followup-verify"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["action"] == "retry_verify"
    assert data["status"] == "needs_followup"
    assert data["resolution_reason"] == "verify succeeded but review still awaits manual release"
    assert data["linked_target"] == {
        "target_type": "review_item",
        "target_id": "review_followup_verify",
        "target_ref": "review_item:review_followup_verify",
    }
    assert data["followup_action"] == "release_review"
    assert data["followup_target_ref"] == "review_item:review_followup_verify"
    assert data["followup_target"] == {
        "target_type": "review_item",
        "target_id": "review_followup_verify",
        "target_ref": "review_item:review_followup_verify",
    }
    assert data["replay_result"]["job_id"] == "verify_review_followup_verify"
    assert data["replay_result"]["status"] == "succeeded"
    assert data["replay_target"] == {
        "target_type": "verify_job",
        "target_id": "verify_review_followup_verify",
        "target_ref": "verify_job:verify_review_followup_verify",
    }

    session.expire_all()
    event = session.get(HumanReviewEvent, "human_review_idempotency_recovery_approve-followup-verify")
    assert event is not None
    assert event.status == "needs_followup"
    assert event.allowed_actions_json == ["inspect", "release_review"]
    assert event.default_action == "release_review"
    assert event.details_json["followup_action"] == "release_review"
    assert event.details_json["followup_target_ref"] == "review_item:review_followup_verify"
    assert event.details_json["resolution_reason"] == "verify succeeded but review still awaits manual release"


def test_human_review_release_review_followup_resolves_event(client, session) -> None:
    approved_row_id = "style_observation_STY_RELEASE_RETRY_v1"
    payload = {"review_id": "review_release_retry"}
    request_hash = canonical_request_hash("POST", "/api/v1/review-items/{review_id}/release", payload)
    session.add(
        ReviewItem(
            review_id="review_release_retry",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            item_type="style_observation",
            status="approved",
            candidate_text="release the recovered request",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STY_RELEASE_RETRY",
                "text": "release the recovered request",
            },
            active_on_approve=0,
            materialize_status="succeeded",
            approved_item_row_id=approved_row_id,
            approved_item_id="STY_RELEASE_RETRY",
        )
    )
    session.add(
        StyleObservation(
            row_id=approved_row_id,
            style_observation_id="STY_RELEASE_RETRY",
            version=1,
            scope="global",
            scope_ref_id="global",
            text="release the recovered request",
            source_review_id="review_release_retry",
            active_flag=0,
            runtime_eligible=0,
            runtime_eligibility_basis="manual_hold",
        )
    )
    session.add(
        VersionRegistry(
            object_type="style_observation",
            lineage_key="STY_RELEASE_RETRY",
            version=1,
            physical_row_id=approved_row_id,
            alias_scope="style_observation:global:global",
            materialize_status="succeeded",
            reindex_status="succeeded",
            verify_status="succeeded",
        )
    )
    session.add(
        VectorAliasRegistry(
            alias_scope="style_observation:global:global",
            object_type="style_observation",
            scope="global",
            scope_ref_id="global",
            collection_family="style_observation_global_global",
            active_alias="style_observation_global_global__candidate__style_observation_STY_ACTIVE_v1",
            candidate_alias=f"style_observation_global_global__candidate__{approved_row_id}",
            active_snapshot_version="snapshot__style_observation_STY_ACTIVE_v1",
            candidate_snapshot_version=f"snapshot__{approved_row_id}",
            active_embedding_version="embed__style_observation_STY_ACTIVE_v1",
            candidate_embedding_version=f"embed__{approved_row_id}",
            verify_status="succeeded",
            sample_query_success=1,
        )
    )
    session.add(
        HumanReviewEvent(
            event_id="human_review_idempotency_recovery_release-review-retry-request",
            object_ref="release-review-retry-request",
            event_source="idempotency_recovery",
            priority="high",
            status="needs_followup",
            allowed_actions_json=["inspect", "release_review"],
            result_status_map_json={"inspect": "needs_followup", "release_review": "resolved"},
            details_json={
                "idempotency_key": "release-review-retry-request",
                "request_hash": request_hash,
                "request_method": "POST",
                "request_path_template": "/api/v1/review-items/{review_id}/release",
                "request_payload": payload,
                "linked_target_type": "review_item",
                "linked_target_id": "review_release_retry",
                "linked_target_ref": "review_item:review_release_retry",
                "followup_action": "release_review",
                "followup_target_type": "review_item",
                "followup_target_id": "review_release_retry",
                "followup_target_ref": "review_item:review_release_retry",
                "attempt_no": 1,
                "previous_worker_id": "http",
                "previous_lease_expires_at": "2000-01-01T00:00:00+00:00",
            },
            default_action="release_review",
        )
    )
    session.commit()

    response = client.post(
        "/api/v1/human-review-events/human_review_idempotency_recovery_release-review-retry-request/actions",
        json={"action": "release_review"},
        headers={"X-Idempotency-Key": "human-review-action-release-retry-request"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["event_id"] == "human_review_idempotency_recovery_release-review-retry-request"
    assert data["action"] == "release_review"
    assert data["status"] == "resolved"
    assert data["linked_target_ref"] == "review_item:review_release_retry"
    assert data["linked_target"] == {
        "target_type": "review_item",
        "target_id": "review_release_retry",
        "target_ref": "review_item:review_release_retry",
    }
    assert data["resolution_reason"] == "review released and active alias promoted"
    assert data["followup_action"] is None
    assert data["followup_target_ref"] is None
    assert data["followup_target"] is None
    assert data["replay_result"] == {"review_id": "review_release_retry", "released": True}
    assert data["replay_target"] == {
        "target_type": "review_item",
        "target_id": "review_release_retry",
        "target_ref": "review_item:review_release_retry",
    }

    session.expire_all()
    event = session.get(HumanReviewEvent, "human_review_idempotency_recovery_release-review-retry-request")
    assert event is not None
    assert event.status == "resolved"
    assert event.details_json["last_action_status"] == "resolved"
    assert event.details_json["linked_target_ref"] == "review_item:review_release_retry"
    assert event.details_json["resolution_reason"] == "review released and active alias promoted"
    assert event.allowed_actions_json == ["inspect"]
    assert event.default_action == "inspect"
    assert "followup_action" not in event.details_json

    alias = session.get(VectorAliasRegistry, "style_observation:global:global")
    assert alias is not None
    assert alias.active_alias == f"style_observation_global_global__candidate__{approved_row_id}"
    assert alias.candidate_alias is None
