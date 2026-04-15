from __future__ import annotations

from novel_system.db.models import HumanReviewEvent, OperationLog, ReindexJob, VectorAliasRegistry, VerifyJob


def test_jobs_support_page_cursor_worker_and_stuck_filters_on_both_routes(client, session) -> None:
    session.add_all(
        [
            ReindexJob(
                job_id="reindex_job_001",
                review_id="review_job_001",
                status="running",
                object_type="style_observation",
                alias_scope="style_observation:global:global",
                target_snapshot_version="snapshot__review_job_001",
                target_embedding_version="embed__review_job_001",
                worker_id="worker-alpha",
                attempt_no=1,
                lease_expires_at="2026-04-11T08:00:00Z",
            ),
            ReindexJob(
                job_id="reindex_job_002",
                review_id="review_job_002",
                status="running",
                object_type="style_observation",
                alias_scope="style_observation:scene:CH001_SC01",
                target_snapshot_version="snapshot__review_job_002",
                target_embedding_version="embed__review_job_002",
                worker_id="worker-beta",
                attempt_no=1,
                lease_expires_at="2099-04-11T12:00:00Z",
            ),
            VerifyJob(
                job_id="verify_job_001",
                review_id="review_job_003",
                status="failed",
                object_type="style_observation",
                alias_scope="style_observation:global:global",
                target_snapshot_version="snapshot__review_job_003",
                target_embedding_version="embed__review_job_003",
            ),
            VerifyJob(
                job_id="verify_job_002",
                review_id="review_job_004",
                status="running",
                object_type="style_observation",
                alias_scope="style_observation:scene:CH001_SC02",
                target_snapshot_version="snapshot__review_job_004",
                target_embedding_version="embed__review_job_004",
                worker_id="worker-alpha",
                attempt_no=2,
                lease_expires_at="2026-04-11T07:00:00Z",
            ),
        ]
    )
    session.commit()

    index_page = client.get("/api/v1/index/jobs", params={"page": 1, "page_size": 2})
    domain_page = client.get("/api/v1/jobs", params={"page": 1, "page_size": 2})

    assert index_page.status_code == 200
    assert domain_page.status_code == 200
    index_page_data = index_page.json()["data"]
    domain_page_data = domain_page.json()["data"]
    assert [item["job_id"] for item in index_page_data["items"]] == ["reindex_job_001", "reindex_job_002"]
    assert domain_page_data == index_page_data
    assert index_page_data["pagination"]["mode"] == "page"
    assert index_page_data["pagination"]["limit"] == 2
    assert index_page_data["pagination"]["page"] == 1
    assert index_page_data["pagination"]["page_size"] == 2
    assert index_page_data["pagination"]["returned"] == 2
    assert index_page_data["pagination"]["total"] == 4
    assert index_page_data["pagination"]["has_next"] is True
    assert isinstance(index_page_data["pagination"]["next_cursor"], str)
    assert index_page_data["pagination"]["next_cursor"]

    cursor_page = client.get("/api/v1/index/jobs", params={"limit": 2})
    assert cursor_page.status_code == 200
    cursor_page_data = cursor_page.json()["data"]
    assert [item["job_id"] for item in cursor_page_data["items"]] == ["reindex_job_001", "reindex_job_002"]
    assert cursor_page_data["pagination"]["mode"] == "cursor"
    assert cursor_page_data["pagination"]["page"] is None
    assert cursor_page_data["pagination"]["page_size"] is None
    assert cursor_page_data["pagination"]["returned"] == 2
    assert cursor_page_data["pagination"]["total"] == 4
    assert cursor_page_data["pagination"]["has_next"] is True
    assert isinstance(cursor_page_data["pagination"]["next_cursor"], str)
    assert cursor_page_data["pagination"]["next_cursor"]

    next_cursor_page = client.get(
        "/api/v1/index/jobs",
        params={"cursor": cursor_page_data["pagination"]["next_cursor"], "limit": 2},
    )
    assert next_cursor_page.status_code == 200
    next_cursor_data = next_cursor_page.json()["data"]
    assert [item["job_id"] for item in next_cursor_data["items"]] == ["verify_job_001", "verify_job_002"]
    assert next_cursor_data["pagination"]["has_next"] is False
    assert next_cursor_data["pagination"]["next_cursor"] is None

    invalid_cursor_page = client.get("/api/v1/index/jobs", params={"cursor": "bad-jobs-cursor", "limit": 2})
    assert invalid_cursor_page.status_code == 200
    invalid_cursor_data = invalid_cursor_page.json()["data"]
    assert [item["job_id"] for item in invalid_cursor_data["items"]] == ["reindex_job_001", "reindex_job_002"]

    worker_filter = client.get("/api/v1/index/jobs", params={"worker_id": "worker-alpha"})
    assert worker_filter.status_code == 200
    assert [item["job_id"] for item in worker_filter.json()["data"]["items"]] == ["reindex_job_001", "verify_job_002"]

    stuck_filter = client.get("/api/v1/index/jobs", params={"stuck_only": "true"})
    assert stuck_filter.status_code == 200
    assert [item["job_id"] for item in stuck_filter.json()["data"]["items"]] == ["reindex_job_001", "verify_job_002"]


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
            VerifyJob(
                job_id="verify_job_wrong_scope",
                review_id="review_scene_pending",
                status="failed",
                object_type="style_observation",
                alias_scope="style_observation:scene:CH001_SC02",
                target_snapshot_version="snapshot__review_scene_pending_other_scope",
                target_embedding_version="embed__review_scene_pending_other_scope",
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
        params={
            "job_type": "verify",
            "status": "failed",
            "object_type": "style_observation",
            "review_id": "review_scene_pending",
            "alias_scope": "style_observation:global:global",
        },
    )

    assert [item["alias_scope"] for item in alias_response.json()["data"]["items"]] == ["style_observation:global:global"]
    assert [item["job_id"] for item in job_response.json()["data"]["items"]] == ["verify_job_match"]


def _seed_runtime_ledger_filter_data(session) -> None:
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


def _seed_paginated_runtime_ledger_data(session) -> None:
    session.add_all(
        [
            HumanReviewEvent(
                event_id="human_review_paginated_003",
                object_ref="approve-review-paginated-003",
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
                    "last_action_at": "2026-04-11T09:03:00+00:00",
                    "last_actor_ref": "ops.duwei",
                },
                default_action="inspect",
            ),
            HumanReviewEvent(
                event_id="human_review_paginated_002",
                object_ref="approve-review-paginated-002",
                event_source="idempotency_recovery",
                priority="high",
                status="needs_followup",
                allowed_actions_json=["inspect"],
                result_status_map_json={"inspect": "needs_followup"},
                details_json={
                    "linked_target_type": "review_item",
                    "linked_target_id": "review_scene_pending",
                    "linked_target_ref": "review_item:review_scene_pending",
                    "last_action": "inspect",
                    "last_action_at": "2026-04-11T09:02:00+00:00",
                    "last_actor_ref": "ops.duwei",
                },
                default_action="inspect",
            ),
            HumanReviewEvent(
                event_id="human_review_paginated_001",
                object_ref="approve-review-paginated-001",
                event_source="idempotency_recovery",
                priority="high",
                status="needs_followup",
                allowed_actions_json=["inspect"],
                result_status_map_json={"inspect": "needs_followup"},
                details_json={
                    "linked_target_type": "review_item",
                    "linked_target_id": "review_scene_pending",
                    "linked_target_ref": "review_item:review_scene_pending",
                    "last_action": "retry_request",
                    "last_action_at": "2026-04-11T09:01:00+00:00",
                    "last_actor_ref": "ops.duwei",
                },
                default_action="inspect",
            ),
            OperationLog(
                event_type="runtime_due_promotion",
                object_type="runtime_activity",
                object_ref="style_observation_row_003",
                payload_json={
                    "actor_ref": "system/due_promotion",
                    "summary": "promoted review_scene_pending newest",
                    "review_id": "review_scene_pending",
                },
                created_at="2026-04-11T09:23:00+00:00",
            ),
            OperationLog(
                event_type="runtime_due_promotion",
                object_type="runtime_activity",
                object_ref="style_observation_row_002",
                payload_json={
                    "actor_ref": "system/due_promotion",
                    "summary": "promoted review_scene_pending middle",
                    "review_id": "review_scene_pending",
                },
                created_at="2026-04-11T09:22:00+00:00",
            ),
            OperationLog(
                event_type="runtime_due_promotion",
                object_type="runtime_activity",
                object_ref="style_observation_row_001",
                payload_json={
                    "actor_ref": "system/due_promotion",
                    "summary": "promoted review_scene_pending oldest",
                    "review_id": "review_scene_pending",
                },
                created_at="2026-04-11T09:21:00+00:00",
            ),
            OperationLog(
                event_type="human_review_action",
                object_type="human_review_event",
                object_ref="human_review_paginated_003",
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
                created_at="2026-04-11T09:13:00+00:00",
            ),
            OperationLog(
                event_type="human_review_action",
                object_type="human_review_event",
                object_ref="human_review_paginated_002",
                payload_json={
                    "actor_ref": "ops.duwei",
                    "action": "retry_request",
                    "target_refs": [
                        {
                            "target_type": "review_item",
                            "target_id": "review_scene_pending",
                            "target_ref": "review_item:review_scene_pending",
                        }
                    ],
                },
                created_at="2026-04-11T09:12:00+00:00",
            ),
            OperationLog(
                event_type="operator_action",
                object_type="review_item",
                object_ref="review_scene_pending",
                payload_json={
                    "actor_ref": "ops.duwei",
                    "action": "inspect",
                    "target_refs": [
                        {
                            "target_type": "review_item",
                            "target_id": "review_scene_pending",
                            "target_ref": "review_item:review_scene_pending",
                        }
                    ],
                },
                created_at="2026-04-11T09:11:00+00:00",
            ),
            OperationLog(
                event_type="operator_action",
                object_type="review_item",
                object_ref="review_scene_pending",
                payload_json={
                    "actor_ref": "ops.duwei",
                    "action": "approve_review",
                    "target_refs": [
                        {
                            "target_type": "review_item",
                            "target_id": "review_scene_pending",
                            "target_ref": "review_item:review_scene_pending",
                        }
                    ],
                },
                created_at="2026-04-11T09:10:00+00:00",
            ),
        ]
    )
    session.commit()


def test_jobs_keep_job_id_ordering_when_filters_are_applied(client, session) -> None:
    session.add_all(
        [
            ReindexJob(
                job_id="reindex_job_alpha",
                review_id="review_sort_alpha",
                status="failed",
                object_type="style_observation",
                alias_scope="style_observation:global:global",
                target_snapshot_version="snapshot__review_sort_alpha",
                target_embedding_version="embed__review_sort_alpha",
                finished_at="2026-04-11T09:00:00+00:00",
            ),
            VerifyJob(
                job_id="verify_job_beta",
                review_id="review_sort_beta",
                status="failed",
                object_type="style_observation",
                alias_scope="style_observation:global:global",
                target_snapshot_version="snapshot__review_sort_beta",
                target_embedding_version="embed__review_sort_beta",
                finished_at="2026-04-11T10:00:00+00:00",
            ),
        ]
    )
    session.commit()

    response = client.get("/api/v1/index/jobs", params={"status": "failed", "object_type": "style_observation"})

    assert response.status_code == 200
    assert [item["job_id"] for item in response.json()["data"]["items"]] == ["reindex_job_alpha", "verify_job_beta"]


def test_jobs_reject_invalid_job_type_filter(client, session) -> None:
    session.add_all(
        [
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

    response = client.get("/api/v1/index/jobs", params={"job_type": "all"})

    assert response.status_code == 422


def test_runtime_ledger_filters_operator_action_source_and_rebuilds_groups(client, session) -> None:
    _seed_runtime_ledger_filter_data(session)

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


def test_runtime_ledger_filters_recovery_timeline_source_and_rebuilds_groups(client, session) -> None:
    _seed_runtime_ledger_filter_data(session)

    response = client.get(
        "/api/v1/index/runtime-ledger",
        params={
            "target_ref": "review_item:review_scene_pending",
            "source": "recovery_timeline",
            "actor_ref": "ops.duwei",
        },
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert [item["last_action"] for item in data["recovery_timeline_items"]] == ["retry_verify"]
    assert data["system_runtime_timeline_items"] == []
    assert data["operator_action_timeline_items"] == []
    assert [group["target"]["target_ref"] for group in data["target_activity_groups"]] == ["review_item:review_scene_pending"]
    assert data["target_activity_groups"][0]["sources"] == ["recovery_timeline"]
    assert data["latest_recovery_action_receipt"]["event_id"] == "human_review_runtime_match"


def test_runtime_ledger_filters_system_runtime_source_and_rebuilds_groups(client, session) -> None:
    _seed_runtime_ledger_filter_data(session)

    response = client.get(
        "/api/v1/index/runtime-ledger",
        params={
            "target_ref": "review_item:review_scene_pending",
            "source": "system_runtime",
            "actor_ref": "system/due_promotion",
        },
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert data["recovery_timeline_items"] == []
    assert [item["event_type"] for item in data["system_runtime_timeline_items"]] == ["runtime_due_promotion"]
    assert data["operator_action_timeline_items"] == []
    assert [group["target"]["target_ref"] for group in data["target_activity_groups"]] == ["review_item:review_scene_pending"]
    assert data["target_activity_groups"][0]["sources"] == ["system_runtime"]
    assert data["latest_recovery_action_receipt"] is None


def test_runtime_ledger_rejects_invalid_source_filter(client, session) -> None:
    _seed_runtime_ledger_filter_data(session)

    response = client.get("/api/v1/index/runtime-ledger", params={"source": "all"})

    assert response.status_code == 422


def test_activity_events_support_page_and_cursor_pagination(client, session) -> None:
    _seed_paginated_runtime_ledger_data(session)

    page_response = client.get(
        "/api/v1/activity-events",
        params={
            "stream": "operator_action",
            "target_ref": "review_item:review_scene_pending",
            "actor_ref": "ops.duwei",
            "page": 1,
            "page_size": 2,
        },
    )

    assert page_response.status_code == 200
    page_data = page_response.json()["data"]
    assert [item["action"] for item in page_data["items"]] == ["retry_verify", "retry_request"]
    assert page_data["pagination"]["mode"] == "page"
    assert page_data["pagination"]["returned"] == 2
    assert page_data["pagination"]["total"] == 4
    assert page_data["pagination"]["has_next"] is True

    cursor_response = client.get(
        "/api/v1/activity-events",
        params={
            "stream": "operator_action",
            "target_ref": "review_item:review_scene_pending",
            "actor_ref": "ops.duwei",
            "limit": 2,
        },
    )

    assert cursor_response.status_code == 200
    cursor_data = cursor_response.json()["data"]
    assert [item["action"] for item in cursor_data["items"]] == ["retry_verify", "retry_request"]
    assert cursor_data["pagination"]["mode"] == "cursor"
    assert cursor_data["pagination"]["has_next"] is True
    assert isinstance(cursor_data["pagination"]["next_cursor"], str)

    next_cursor_response = client.get(
        "/api/v1/activity-events",
        params={
            "stream": "operator_action",
            "target_ref": "review_item:review_scene_pending",
            "actor_ref": "ops.duwei",
            "cursor": cursor_data["pagination"]["next_cursor"],
            "limit": 2,
        },
    )

    assert next_cursor_response.status_code == 200
    next_cursor_data = next_cursor_response.json()["data"]
    assert [item["action"] for item in next_cursor_data["items"]] == ["inspect", "approve_review"]
    assert next_cursor_data["pagination"]["has_next"] is False


def test_target_activity_groups_return_paginated_summaries_and_items(client, session) -> None:
    _seed_paginated_runtime_ledger_data(session)

    summary_response = client.get(
        "/api/v1/target-activity-groups",
        params={
            "source": "operator_action",
            "actor_ref": "ops.duwei",
            "page": 1,
            "page_size": 1,
        },
    )

    assert summary_response.status_code == 200
    summary_data = summary_response.json()["data"]
    assert summary_data["pagination"]["mode"] == "page"
    assert summary_data["pagination"]["returned"] == 1
    assert summary_data["pagination"]["total"] == 1
    assert summary_data["items"] == [
        {
            "target": {
                "target_type": "review_item",
                "target_id": "review_scene_pending",
                "target_ref": "review_item:review_scene_pending",
            },
            "latest_at": "2026-04-11T09:13:00+00:00",
            "activity_count": 4,
            "sources": ["operator_action"],
            "latest_activity_key": summary_data["items"][0]["latest_activity_key"],
        }
    ]
    assert summary_data["items"][0]["latest_activity_key"].startswith("operator_action:")

    items_response = client.get(
        "/api/v1/target-activity-groups/review_item:review_scene_pending/items",
        params={
            "source": "operator_action",
            "actor_ref": "ops.duwei",
            "limit": 2,
        },
    )

    assert items_response.status_code == 200
    items_data = items_response.json()["data"]
    assert items_data["target"]["target_ref"] == "review_item:review_scene_pending"
    assert items_data["latest_activity_key"] == summary_data["items"][0]["latest_activity_key"]
    assert [item["label"] for item in items_data["items"]] == ["retry_verify", "retry_request"]
    assert items_data["pagination"]["has_next"] is True

    next_items_response = client.get(
        "/api/v1/target-activity-groups/review_item:review_scene_pending/items",
        params={
            "source": "operator_action",
            "actor_ref": "ops.duwei",
            "cursor": items_data["pagination"]["next_cursor"],
            "limit": 2,
        },
    )

    assert next_items_response.status_code == 200
    next_items_data = next_items_response.json()["data"]
    assert [item["label"] for item in next_items_data["items"]] == ["inspect", "approve_review"]
    assert next_items_data["pagination"]["has_next"] is False
