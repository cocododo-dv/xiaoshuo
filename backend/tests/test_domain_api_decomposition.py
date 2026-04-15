from __future__ import annotations

from tests.test_index_query_filters import _seed_runtime_ledger_filter_data
from tests.test_knowledge_family import _create_review_item, _review_payload, _seed_story

from novel_system.db.models import ReindexJob, VectorAliasRegistry, VerifyJob


def test_knowledge_entries_merge_pending_review_candidates(client) -> None:
    _seed_story(client)
    _create_review_item(
        client,
        _review_payload(
            "review_pending_style_rule_domain",
            "style_rule_set",
            candidate_text="keep the reunion clipped and gesture-led",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STYLE_DOMAIN_PENDING",
                "text": "keep the reunion clipped and gesture-led",
            },
        ),
        key="create-pending-style-rule-domain",
    )

    response = client.get(
        "/api/v1/knowledge-entries",
        params={
            "object_type": "style_rule",
            "scope": "global",
            "scope_ref_id": "global",
            "status": "candidate",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert "style_rule" in data["supported_object_types"]
    assert data["items"] == [
        {
            "object_type": "style_rule",
            "lineage_key": "STYLE_DOMAIN_PENDING",
            "status": "candidate",
            "active_version": None,
            "candidate_version": {
                "review_id": "review_pending_style_rule_domain",
                "text": "keep the reunion clipped and gesture-led",
                "active_flag": False,
                "runtime_eligible": False,
                "review_status": "pending",
                "materialize_status": "pending",
                "target_collection": "style_rules",
                "scope": "global",
                "scope_ref_id": "global",
                "character_id": None,
                "left_character_id": None,
                "right_character_id": None,
                "chapter_id": "CH001",
                "scene_id": "CH001_SC01",
                "lineage_key": "STYLE_DOMAIN_PENDING",
            },
            "versions": [],
            "review_refs": ["review_pending_style_rule_domain"],
            "runtime_refs": {"mode": "pending_review"},
            "bundle_refs": [],
        }
    ]


def test_knowledge_workflow_endpoint_matches_compatibility_detail_workflow(client) -> None:
    _seed_story(client)
    _create_review_item(
        client,
        _review_payload(
            "review_pending_style_rule_workflow_domain",
            "style_rule_set",
            candidate_text="keep the reunion tight and gesture-led",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STYLE_DOMAIN_WORKFLOW",
                "text": "keep the reunion tight and gesture-led",
            },
        ),
        key="create-pending-style-rule-workflow-domain",
    )

    detail_response = client.get("/api/v1/knowledge/style_rule/STYLE_DOMAIN_WORKFLOW")
    workflow_response = client.get("/api/v1/knowledge-entries/style_rule/STYLE_DOMAIN_WORKFLOW/workflow")

    assert detail_response.status_code == 200
    assert workflow_response.status_code == 200
    assert workflow_response.json()["data"] == detail_response.json()["data"]["workflow"]


def test_shared_vector_jobs_and_activity_endpoints_support_filtered_reads(client, session) -> None:
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
                job_id="verify_job_domain_match",
                review_id="review_scene_pending",
                status="failed",
                object_type="style_observation",
                alias_scope="style_observation:global:global",
                target_snapshot_version="snapshot__review_scene_pending",
                target_embedding_version="embed__review_scene_pending",
            ),
            ReindexJob(
                job_id="reindex_job_domain_other",
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
    _seed_runtime_ledger_filter_data(session)

    alias_response = client.get(
        "/api/v1/vector-alias-scopes",
        params={
            "object_type": "style_observation",
            "scope": "global",
            "scope_ref_id": "global",
            "verify_status": "succeeded",
        },
    )
    jobs_response = client.get(
        "/api/v1/jobs",
        params={
            "job_type": "verify",
            "status": "failed",
            "object_type": "style_observation",
            "review_id": "review_scene_pending",
            "alias_scope": "style_observation:global:global",
        },
    )
    activity_response = client.get(
        "/api/v1/activity-events",
        params={
            "stream": "operator_action",
            "target_ref": "review_item:review_scene_pending",
            "actor_ref": "ops.duwei",
        },
    )
    group_response = client.get(
        "/api/v1/target-activity-groups",
        params={
            "target_ref": "review_item:review_scene_pending",
            "source": "operator_action",
            "actor_ref": "ops.duwei",
        },
    )

    assert alias_response.status_code == 200
    assert jobs_response.status_code == 200
    assert activity_response.status_code == 200
    assert group_response.status_code == 200
    assert [item["alias_scope"] for item in alias_response.json()["data"]["items"]] == ["style_observation:global:global"]
    assert [item["job_id"] for item in jobs_response.json()["data"]["items"]] == ["verify_job_domain_match"]
    assert [item["action"] for item in activity_response.json()["data"]["items"]] == ["retry_verify"]
    assert [group["target"]["target_ref"] for group in group_response.json()["data"]["items"]] == [
        "review_item:review_scene_pending"
    ]
    assert group_response.json()["data"]["items"][0]["sources"] == ["operator_action"]


def test_compatibility_index_wrappers_match_new_domain_reads(client, session) -> None:
    session.add(
        VerifyJob(
            job_id="verify_job_domain_compare",
            review_id="review_scene_pending",
            status="failed",
            object_type="style_observation",
            alias_scope="style_observation:global:global",
            target_snapshot_version="snapshot__review_scene_pending",
            target_embedding_version="embed__review_scene_pending",
        )
    )
    session.commit()
    _seed_runtime_ledger_filter_data(session)

    compat_jobs = client.get(
        "/api/v1/index/jobs",
        params={"job_type": "verify", "status": "failed", "review_id": "review_scene_pending"},
    )
    domain_jobs = client.get(
        "/api/v1/jobs",
        params={"job_type": "verify", "status": "failed", "review_id": "review_scene_pending"},
    )
    compat_ledger = client.get(
        "/api/v1/index/runtime-ledger",
        params={
            "target_ref": "review_item:review_scene_pending",
            "source": "operator_action",
            "actor_ref": "ops.duwei",
        },
    )
    domain_activity = client.get(
        "/api/v1/activity-events",
        params={
            "stream": "operator_action",
            "target_ref": "review_item:review_scene_pending",
            "actor_ref": "ops.duwei",
        },
    )
    domain_groups = client.get(
        "/api/v1/target-activity-groups",
        params={
            "target_ref": "review_item:review_scene_pending",
            "source": "operator_action",
            "actor_ref": "ops.duwei",
        },
    )
    domain_group_items = client.get(
        "/api/v1/target-activity-groups/review_item:review_scene_pending/items",
        params={
            "source": "operator_action",
            "actor_ref": "ops.duwei",
        },
    )

    assert compat_jobs.status_code == 200
    assert domain_jobs.status_code == 200
    assert compat_ledger.status_code == 200
    assert domain_activity.status_code == 200
    assert domain_groups.status_code == 200
    assert domain_group_items.status_code == 200
    assert compat_jobs.json()["data"]["items"] == domain_jobs.json()["data"]["items"]
    assert compat_ledger.json()["data"]["operator_action_timeline_items"] == domain_activity.json()["data"]["items"]
    compat_groups = compat_ledger.json()["data"]["target_activity_groups"]
    domain_group_summaries = domain_groups.json()["data"]["items"]
    assert [
        {
            "target": group["target"],
            "latest_at": group["latest_at"],
            "activity_count": group["activity_count"],
            "sources": group["sources"],
            "latest_activity_key": group["latest_activity_key"],
        }
        for group in compat_groups
    ] == domain_group_summaries
    assert domain_group_items.json()["data"]["items"] == compat_groups[0]["activity_items"]
