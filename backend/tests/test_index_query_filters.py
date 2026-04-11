from __future__ import annotations

from novel_system.db.models import HumanReviewEvent, OperationLog, ReindexJob, VectorAliasRegistry, VerifyJob


def test_alias_scopes_and_jobs_apply_supported_filters(client, session) -> None:
    session.add_all(
        [
            VectorAliasRegistry(
                alias_scope="style_observation:global:global",
                object_type="style_observation",
                scope="global",
                scope_ref_id="global",
                collection_family="style_observation_global_global",
                active_alias="style_observation_global_global__active__v1",
                verify_status="succeeded",
            ),
            VectorAliasRegistry(
                alias_scope="style_observation:scene:CH001_SC02",
                object_type="style_observation",
                scope="scene",
                scope_ref_id="CH001_SC02",
                collection_family="style_observation_scene_CH001_SC02",
                active_alias="style_observation_scene_CH001_SC02__active__v1",
                verify_status="failed",
            ),
            VerifyJob(
                job_id="verify_job_match",
                review_id="review_scene_pending",
                status="failed",
                object_type="style_observation",
                alias_scope="style_observation:global:global",
                target_snapshot_version="snapshot__review_scene_pending",
                target_embedding_version="embed__review_scene_pending",
            ),
            ReindexJob(
                job_id="reindex_job_other",
                review_id="review_other",
                status="queued",
                object_type="style_observation",
                alias_scope="style_observation:scene:CH001_SC02",
                target_snapshot_version="snapshot__review_other",
                target_embedding_version="embed__review_other",
            ),
        ]
    )
    session.commit()

    alias_response = client.get(
        "/api/v1/index/alias-scopes",
        params={"object_type": "style_observation", "scope": "global", "scope_ref_id": "global", "verify_status": "succeeded"},
    )
    job_response = client.get(
        "/api/v1/index/jobs",
        params={"job_type": "verify", "status": "failed", "object_type": "style_observation", "review_id": "review_scene_pending"},
    )

    assert [item["alias_scope"] for item in alias_response.json()["data"]["items"]] == ["style_observation:global:global"]
    assert [item["job_id"] for item in job_response.json()["data"]["items"]] == ["verify_job_match"]


def test_runtime_ledger_filters_by_target_source_and_actor_and_rebuilds_groups(client, session) -> None:
    session.add_all(
        [
            HumanReviewEvent(
                event_id="human_review_runtime_match",
                object_ref="approve-review-runtime-match",
                event_source="idempotency_recovery",
                priority="high",
                status="needs_followup",
                allowed_actions_json=["inspect"],
                result_status_map_json={"inspect": "needs_followup"},
                details_json={
                    "linked_target_type": "review_item",
                    "linked_target_id": "review_scene_pending",
                    "linked_target_ref": "review_item:review_scene_pending",
                    "last_action": "retry_verify",
                    "last_action_at": "2026-04-11T09:00:00+00:00",
                    "last_actor_ref": "ops.duwei",
                },
                default_action="inspect",
            ),
            OperationLog(
                event_type="runtime_due_promotion",
                object_type="runtime_activity",
                object_ref="style_observation_row",
                payload_json={
                    "actor_ref": "system/due_promotion",
                    "summary": "promoted review_scene_pending",
                    "review_id": "review_scene_pending",
                },
                created_at="2026-04-11T09:05:00+00:00",
            ),
            OperationLog(
                event_type="human_review_action",
                object_type="human_review_event",
                object_ref="human_review_runtime_match",
                payload_json={
                    "actor_ref": "ops.duwei",
                    "action": "retry_verify",
                    "target_refs": [
                        {
                            "target_type": "review_item",
                            "target_id": "review_scene_pending",
                            "target_ref": "review_item:review_scene_pending",
                        }
                    ],
                },
                created_at="2026-04-11T09:03:00+00:00",
            ),
            OperationLog(
                event_type="operator_action",
                object_type="review_item",
                object_ref="review_other",
                payload_json={"actor_ref": "ops.other", "action": "inspect"},
                created_at="2026-04-11T09:04:00+00:00",
            ),
        ]
    )
    session.commit()

    response = client.get(
        "/api/v1/index/runtime-ledger",
        params={
            "target_ref": "review_item:review_scene_pending",
            "source": "operator_action",
            "actor_ref": "ops.duwei",
        },
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert data["recovery_timeline_items"] == []
    assert data["system_runtime_timeline_items"] == []
    assert [item["action"] for item in data["operator_action_timeline_items"]] == ["retry_verify"]
    assert [group["target"]["target_ref"] for group in data["target_activity_groups"]] == ["review_item:review_scene_pending"]
    assert data["target_activity_groups"][0]["sources"] == ["operator_action"]
    assert data["latest_recovery_action_receipt"] is None
