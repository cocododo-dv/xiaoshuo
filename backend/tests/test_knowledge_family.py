from __future__ import annotations

from typing import Any

from novel_system.db.models import HumanReviewEvent


def _seed_story(client) -> None:
    assert client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": "CH001",
            "planned_scene_count": 1,
            "chapter_goal": "close the reunion chapter with a traceable knowledge bundle",
            "main_plot_push": "the old letter clue becomes actionable",
            "emotional_target": "move from suspicion to guarded trust",
            "ending_effect": "leave a clean unresolved hook",
        },
        headers={"X-Idempotency-Key": "seed-chapter"},
    ).status_code == 200
    assert client.post(
        "/api/v1/scenes",
        json={
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
            "scene_seq": 1,
            "pov_character_id": "CHAR_A",
            "onstage_chars_json": ["CHAR_A", "CHAR_B"],
            "resolved_relation_id": "REL_CHAR_A_CHAR_B",
            "location": "Old city gate",
            "scene_goal": "reunite the two leads and surface the old letter clue",
            "beats_json": ["reunion", "probing", "hook"],
            "must_include_text": "an old letter clue",
            "target_length_band": "short",
            "scene_type": "reunion",
            "is_chapter_last": 1,
        },
        headers={"X-Idempotency-Key": "seed-scene"},
    ).status_code == 200


def _review_payload(
    review_id: str,
    item_type: str,
    *,
    candidate_text: str,
    candidate_payload_json: dict[str, Any],
    active_on_approve: int = 1,
) -> dict[str, Any]:
    return {
        "review_id": review_id,
        "scene_id": "CH001_SC01",
        "chapter_id": "CH001",
        "item_type": item_type,
        "candidate_text": candidate_text,
        "candidate_payload_json": candidate_payload_json,
        "active_on_approve": active_on_approve,
    }


def _create_review_item(client, payload: dict[str, Any], *, key: str) -> None:
    response = client.post(
        "/api/v1/review-items",
        json=payload,
        headers={"X-Idempotency-Key": key},
    )
    assert response.status_code == 200


def _approve_review(client, review_id: str, *, key: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/review-items/{review_id}/approve",
        headers={"X-Idempotency-Key": key},
    )
    assert response.status_code == 200
    return response.json()["data"]


def _verify_review_candidate(client, review_id: str, *, key: str) -> dict[str, Any]:
    jobs = client.get("/api/v1/index/jobs").json()["data"]["items"]
    verify_job_id = next(
        item["job_id"]
        for item in jobs
        if item["review_id"] == review_id and item["job_type"] == "verify"
    )
    response = client.post(
        f"/api/v1/index/verify/{verify_job_id}/retry",
        headers={"X-Idempotency-Key": key},
    )
    assert response.status_code == 200
    return response.json()["data"]


def _release_review(client, review_id: str, *, key: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/review-items/{review_id}/release",
        headers={"X-Idempotency-Key": key},
    )
    assert response.status_code == 200
    return response.json()["data"]


def test_create_review_item_supports_complete_knowledge_family_target_collections(client) -> None:
    _seed_story(client)

    payloads = [
        _review_payload(
            "review_style_rule_global",
            "style_rule_set",
            candidate_text="keep emotion in gesture and pause",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STYLE_GLOBAL_MAIN",
                "text": "keep emotion in gesture and pause",
            },
        ),
        _review_payload(
            "review_banned_cluster",
            "banned_rule_cluster",
            candidate_text="do not explain the whole backstory at reunion time",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "BAN_REUNION_V1",
                "text": "do not explain the whole backstory at reunion time",
            },
        ),
        _review_payload(
            "review_voice_card",
            "voice_card_candidate",
            candidate_text="short clipped lines; pressure makes the tone harder",
            candidate_payload_json={
                "lineage_key": "VOICE_CHAR_A",
                "character_id": "CHAR_A",
                "text": "short clipped lines; pressure makes the tone harder",
            },
        ),
        _review_payload(
            "review_relation_card",
            "relation_card_candidate",
            candidate_text="reunion tension; B knows slightly more than A",
            candidate_payload_json={
                "lineage_key": "REL_CHAR_A_CHAR_B",
                "left_character_id": "CHAR_A",
                "right_character_id": "CHAR_B",
                "text": "reunion tension; B knows slightly more than A",
            },
        ),
        _review_payload(
            "review_world_rule",
            "world_rule",
            candidate_text="public spellcasting inside the city is forbidden",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "WR_GLOBAL_014",
                "rule_tier": "hard",
                "text": "public spellcasting inside the city is forbidden",
            },
        ),
        _review_payload(
            "review_calibration_line",
            "calibration_candidate",
            candidate_text="the door closed like a sentence left unfinished",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "CAL_002",
                "text": "the door closed like a sentence left unfinished",
            },
        ),
        _review_payload(
            "review_foreshadow_open",
            "foreshadow_open",
            candidate_text="the old letter sender clue is now in play",
            candidate_payload_json={
                "lineage_key": "F014",
                "chapter_id": "CH001",
                "scene_id": "CH001_SC01",
                "text": "the old letter sender clue is now in play",
            },
        ),
        _review_payload(
            "review_foreshadow_touch",
            "foreshadow_touch",
            candidate_text="touch the old letter sender clue again",
            candidate_payload_json={
                "lineage_key": "F014",
                "chapter_id": "CH001",
                "scene_id": "CH001_SC01",
                "text": "touch the old letter sender clue again",
            },
        ),
        _review_payload(
            "review_foreshadow_resolve",
            "foreshadow_resolve",
            candidate_text="resolve the old letter sender clue",
            candidate_payload_json={
                "lineage_key": "F014",
                "chapter_id": "CH001",
                "scene_id": "CH001_SC01",
                "text": "resolve the old letter sender clue",
            },
        ),
        _review_payload(
            "review_scene_summary",
            "scene_summary",
            candidate_text="scene summary for the first reunion beat",
            candidate_payload_json={
                "lineage_key": "CH001_SC01",
                "scene_id": "CH001_SC01",
                "text": "scene summary for the first reunion beat",
            },
        ),
        _review_payload(
            "review_chapter_summary",
            "chapter_summary",
            candidate_text="chapter summary for the first reunion chapter",
            candidate_payload_json={
                "lineage_key": "CH001",
                "chapter_id": "CH001",
                "text": "chapter summary for the first reunion chapter",
            },
        ),
        _review_payload(
            "review_style_observation",
            "style_observation",
            candidate_text="end the scene on a half-finished breath",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STY_003",
                "text": "end the scene on a half-finished breath",
            },
        ),
    ]

    for index, payload in enumerate(payloads, start=1):
        _create_review_item(client, payload, key=f"create-review-item-{index}")

    listed = client.get("/api/v1/review-items")
    assert listed.status_code == 200
    items = {item["review_id"]: item for item in listed.json()["data"]["items"]}

    assert items["review_style_rule_global"]["target_collection"] == "style_rules"
    assert items["review_banned_cluster"]["target_collection"] == "banned_rule_clusters"
    assert items["review_voice_card"]["target_collection"] == "voice_cards"
    assert items["review_relation_card"]["target_collection"] == "relation_cards"
    assert items["review_world_rule"]["target_collection"] == "world_rules"
    assert items["review_calibration_line"]["target_collection"] == "calibration_lines"
    assert items["review_foreshadow_open"]["target_collection"] == "foreshadow_tracker"
    assert items["review_foreshadow_touch"]["target_collection"] == "foreshadow_tracker"
    assert items["review_foreshadow_resolve"]["target_collection"] == "foreshadow_tracker"
    assert items["review_scene_summary"]["target_collection"] == "scene_memories"
    assert items["review_chapter_summary"]["target_collection"] == "chapter_memories"
    assert items["review_style_observation"]["target_collection"] == "style_observations"


def test_knowledge_directory_tracks_direct_vector_summary_and_foreshadow_objects(client) -> None:
    _seed_story(client)

    reviews = [
        _review_payload(
            "review_style_rule_global",
            "style_rule_set",
            candidate_text="keep emotion in gesture and pause",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STYLE_GLOBAL_MAIN",
                "text": "keep emotion in gesture and pause",
            },
        ),
        _review_payload(
            "review_voice_card",
            "voice_card_candidate",
            candidate_text="short clipped lines; pressure makes the tone harder",
            candidate_payload_json={
                "lineage_key": "VOICE_CHAR_A",
                "character_id": "CHAR_A",
                "text": "short clipped lines; pressure makes the tone harder",
            },
        ),
        _review_payload(
            "review_relation_card",
            "relation_card_candidate",
            candidate_text="reunion tension; B knows slightly more than A",
            candidate_payload_json={
                "lineage_key": "REL_CHAR_A_CHAR_B",
                "left_character_id": "CHAR_A",
                "right_character_id": "CHAR_B",
                "text": "reunion tension; B knows slightly more than A",
            },
        ),
        _review_payload(
            "review_world_rule",
            "world_rule",
            candidate_text="public spellcasting inside the city is forbidden",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "WR_GLOBAL_014",
                "rule_tier": "hard",
                "text": "public spellcasting inside the city is forbidden",
            },
        ),
        _review_payload(
            "review_calibration_line",
            "calibration_candidate",
            candidate_text="the door closed like a sentence left unfinished",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "CAL_002",
                "text": "the door closed like a sentence left unfinished",
            },
            active_on_approve=0,
        ),
        _review_payload(
            "review_foreshadow_open",
            "foreshadow_open",
            candidate_text="the old letter sender clue is now in play",
            candidate_payload_json={
                "lineage_key": "F014",
                "chapter_id": "CH001",
                "scene_id": "CH001_SC01",
                "text": "the old letter sender clue is now in play",
            },
        ),
        _review_payload(
            "review_scene_summary",
            "scene_summary",
            candidate_text="scene summary for the first reunion beat",
            candidate_payload_json={
                "lineage_key": "CH001_SC01",
                "scene_id": "CH001_SC01",
                "text": "scene summary for the first reunion beat",
            },
        ),
        _review_payload(
            "review_chapter_summary",
            "chapter_summary",
            candidate_text="chapter summary for the first reunion chapter",
            candidate_payload_json={
                "lineage_key": "CH001",
                "chapter_id": "CH001",
                "text": "chapter summary for the first reunion chapter",
            },
        ),
    ]

    for index, payload in enumerate(reviews, start=1):
        _create_review_item(client, payload, key=f"create-knowledge-family-{index}")
        _approve_review(client, payload["review_id"], key=f"approve-knowledge-family-{index}")

    _verify_review_candidate(client, "review_calibration_line", key="verify-calibration")
    _release_review(client, "review_calibration_line", key="release-calibration")

    listed = client.get("/api/v1/knowledge")
    assert listed.status_code == 200
    items = {
        (item["object_type"], item["lineage_key"]): item
        for item in listed.json()["data"]["items"]
    }

    assert items[("style_rule", "STYLE_GLOBAL_MAIN")]["active_version"]["version"] == 1
    assert items[("voice_card", "VOICE_CHAR_A")]["active_version"]["runtime_eligible"] is True
    assert items[("relation_card", "REL_CHAR_A_CHAR_B")]["active_version"]["runtime_eligible"] is True
    assert items[("world_rule", "WR_GLOBAL_014")]["active_version"]["version"] == 1
    assert items[("calibration_line", "CAL_002")]["runtime_refs"]["alias_scope"] == "calibration_line:global:global"
    assert items[("foreshadow", "F014")]["active_version"]["status"] == "open"
    assert items[("scene_summary", "CH001_SC01")]["active_version"]["row_id"].startswith("scene_memory_")
    assert items[("chapter_summary", "CH001")]["active_version"]["row_id"].startswith("chapter_memory_")

    detail = client.get("/api/v1/knowledge/calibration_line/CAL_002")
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["lineage_key"] == "CAL_002"
    assert detail_data["versions"][0]["version"] == 1
    assert detail_data["runtime_refs"]["alias_scope"] == "calibration_line:global:global"


def test_bundle_builder_includes_new_knowledge_sources_in_snapshot(client) -> None:
    _seed_story(client)

    reviews = [
        _review_payload(
            "review_style_rule_global",
            "style_rule_set",
            candidate_text="keep emotion in gesture and pause",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STYLE_GLOBAL_MAIN",
                "text": "keep emotion in gesture and pause",
            },
        ),
        _review_payload(
            "review_banned_cluster",
            "banned_rule_cluster",
            candidate_text="do not explain the whole backstory at reunion time",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "BAN_REUNION_V1",
                "text": "do not explain the whole backstory at reunion time",
            },
        ),
        _review_payload(
            "review_voice_card",
            "voice_card_candidate",
            candidate_text="short clipped lines; pressure makes the tone harder",
            candidate_payload_json={
                "lineage_key": "VOICE_CHAR_A",
                "character_id": "CHAR_A",
                "text": "short clipped lines; pressure makes the tone harder",
            },
        ),
        _review_payload(
            "review_relation_card",
            "relation_card_candidate",
            candidate_text="reunion tension; B knows slightly more than A",
            candidate_payload_json={
                "lineage_key": "REL_CHAR_A_CHAR_B",
                "left_character_id": "CHAR_A",
                "right_character_id": "CHAR_B",
                "text": "reunion tension; B knows slightly more than A",
            },
        ),
        _review_payload(
            "review_world_rule",
            "world_rule",
            candidate_text="public spellcasting inside the city is forbidden",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "WR_GLOBAL_014",
                "rule_tier": "hard",
                "text": "public spellcasting inside the city is forbidden",
            },
        ),
        _review_payload(
            "review_calibration_line",
            "calibration_candidate",
            candidate_text="the door closed like a sentence left unfinished",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "CAL_002",
                "text": "the door closed like a sentence left unfinished",
            },
            active_on_approve=0,
        ),
        _review_payload(
            "review_foreshadow_open",
            "foreshadow_open",
            candidate_text="the old letter sender clue is now in play",
            candidate_payload_json={
                "lineage_key": "F014",
                "chapter_id": "CH001",
                "scene_id": "CH001_SC01",
                "text": "the old letter sender clue is now in play",
            },
        ),
    ]

    for index, payload in enumerate(reviews, start=1):
        _create_review_item(client, payload, key=f"create-bundle-knowledge-{index}")
        _approve_review(client, payload["review_id"], key=f"approve-bundle-knowledge-{index}")

    _verify_review_candidate(client, "review_calibration_line", key="verify-bundle-calibration")
    _release_review(client, "review_calibration_line", key="release-bundle-calibration")

    scene_run = client.post(
        "/api/v1/scenes/CH001_SC01/run/full",
        headers={"X-Idempotency-Key": "run-scene-knowledge-bundle"},
    )
    assert scene_run.status_code == 200

    bundle_id = scene_run.json()["data"]["current_bundle_id"]
    worksheet = client.get(f"/api/v1/interop/export/bundle-worksheet/{bundle_id}")
    assert worksheet.status_code == 200

    snapshot = worksheet.json()["data"]["snapshot"]
    assert snapshot["source_version_refs"]["style_rule_set_id"] == "STYLE_GLOBAL_MAIN"
    assert snapshot["source_version_refs"]["banned_cluster_id"] == "BAN_REUNION_V1"
    assert snapshot["source_version_refs"]["calibration_line_ids"] == ["CAL_002"]
    assert snapshot["resolved_ref_ids"]["world_rule_ids"] == ["WR_GLOBAL_014"]
    assert snapshot["resolved_ref_ids"]["open_foreshadow_ids"] == ["F014"]

    injection_digest_keys = [item["digest_key"] for item in snapshot["ordered_injections"]]
    assert "voice_card" in injection_digest_keys
    assert "relation_card" in injection_digest_keys
    assert "style_rule" in injection_digest_keys
    assert "banned_rule" in injection_digest_keys
    assert "calibration_line" in injection_digest_keys
    assert "world_rule" in injection_digest_keys
    assert "foreshadow" in injection_digest_keys

    assert snapshot["inline_digests"]["voice_card"] == "short clipped lines; pressure makes the tone harder"
    assert snapshot["inline_digests"]["relation_card"] == "reunion tension; B knows slightly more than A"
    assert snapshot["inline_digests"]["style_rule"] == "keep emotion in gesture and pause"
    assert snapshot["inline_digests"]["banned_rule"] == "do not explain the whole backstory at reunion time"
    assert snapshot["inline_digests"]["calibration_line"] == "the door closed like a sentence left unfinished"
    assert snapshot["inline_digests"]["world_rule"] == "public spellcasting inside the city is forbidden"
    assert snapshot["inline_digests"]["foreshadow"] == "the old letter sender clue is now in play"


def test_voice_card_materialization_preserves_character_contract_metadata(client) -> None:
    _seed_story(client)
    payload = _review_payload(
        "review_voice_contract_metadata",
        "voice_card_candidate",
        candidate_text="冷静、短句，压力落在动作里。",
        candidate_payload_json={
            "lineage_key": "VOICE_CHAR_A",
            "character_id": "CHAR_A",
            "text": "冷静、短句，压力落在动作里。",
            "display_name": "林岑",
            "pronouns": ["她"],
            "role": "档案修复师",
            "aliases": ["小林"],
        },
    )

    _create_review_item(client, payload, key="create-voice-contract-metadata")
    _approve_review(client, payload["review_id"], key="approve-voice-contract-metadata")

    detail = client.get("/api/v1/knowledge-entries/voice_card/VOICE_CHAR_A")
    assert detail.status_code == 200
    active_text = detail.json()["data"]["active_version"]["text"]
    assert "角色名：林岑" in active_text
    assert "代词：她" in active_text
    assert "角色职责：档案修复师" in active_text
    assert "别名：小林" in active_text


def test_knowledge_detail_workflow_includes_pending_review_and_recommended_approve(client) -> None:
    _seed_story(client)
    _create_review_item(
        client,
        _review_payload(
            "review_pending_style_rule_workflow",
            "style_rule_set",
            candidate_text="keep the reunion tight and gesture-led",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STYLE_WORKFLOW_PENDING",
                "text": "keep the reunion tight and gesture-led",
            },
        ),
        key="create-pending-style-rule-workflow",
    )

    response = client.get("/api/v1/knowledge/style_rule/STYLE_WORKFLOW_PENDING")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["lineage_key"] == "STYLE_WORKFLOW_PENDING"
    assert data["workflow"]["review_items"] == [
        {
            "review_id": "review_pending_style_rule_workflow",
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
            "item_type": "style_rule_set",
            "target_collection": "style_rules",
            "status": "pending",
            "candidate_text": "keep the reunion tight and gesture-led",
            "candidate_payload_json": {
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STYLE_WORKFLOW_PENDING",
                "text": "keep the reunion tight and gesture-led",
            },
            "active_on_approve": 1,
            "materialize_status": "pending",
            "approved_item_row_id": None,
        }
    ]
    assert data["workflow"]["jobs"] == []
    assert data["workflow"]["human_review_events"] == []
    assert data["workflow"]["target_activity_groups"] == []
    assert data["workflow"]["recommended_primary_action"] == {
        "kind": "review",
        "action": "approve_review",
        "review_id": "review_pending_style_rule_workflow",
        "label": "Approve",
        "target_ref": "review_item:review_pending_style_rule_workflow",
    }


def test_knowledge_detail_workflow_includes_verify_release_followup_and_target_activity(client, session) -> None:
    _seed_story(client)
    _create_review_item(
        client,
        _review_payload(
            "review_workflow_calibration",
            "calibration_candidate",
            candidate_text="the gate sighed shut on the unfinished question",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "CAL_WORKFLOW",
                "text": "the gate sighed shut on the unfinished question",
            },
            active_on_approve=0,
        ),
        key="create-workflow-calibration",
    )
    _approve_review(client, "review_workflow_calibration", key="approve-workflow-calibration")

    verify_jobs = [
        item
        for item in client.get("/api/v1/index/jobs").json()["data"]["items"]
        if item["review_id"] == "review_workflow_calibration"
    ]
    verify_job = next(item for item in verify_jobs if item["job_type"] == "verify")
    reindex_job = next(item for item in verify_jobs if item["job_type"] == "reindex")

    _verify_review_candidate(client, "review_workflow_calibration", key="verify-workflow-calibration")

    session.add(
        HumanReviewEvent(
            event_id="human_review_workflow_calibration_release",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            object_ref="review_workflow_calibration",
            event_source="idempotency_recovery",
            priority="high",
            status="needs_followup",
            allowed_actions_json=["inspect", "release_review"],
            result_status_map_json={"inspect": "needs_followup", "release_review": "resolved"},
            details_json={
                "linked_target_ref": "review_item:review_workflow_calibration",
                "followup_action": "release_review",
                "followup_target_ref": "review_item:review_workflow_calibration",
                "last_action": "retry_verify",
                "last_action_at": "2026-04-11T13:20:00+00:00",
                "last_actor_ref": "ops.workflow",
                "last_replay_result": {
                    "job_id": verify_job["job_id"],
                    "job_type": "verify",
                    "status": "succeeded",
                },
                "resolution_reason": "verify succeeded but review still awaits manual release",
            },
            default_action="release_review",
        )
    )
    session.commit()

    response = client.get("/api/v1/knowledge/calibration_line/CAL_WORKFLOW")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["runtime_refs"]["alias_scope"] == "calibration_line:global:global"
    assert {item["review_id"] for item in data["workflow"]["review_items"]} == {"review_workflow_calibration"}
    assert {(item["job_id"], item["job_type"]) for item in data["workflow"]["jobs"]} == {
        (verify_job["job_id"], "verify"),
        (reindex_job["job_id"], "reindex"),
    }
    assert [item["event_id"] for item in data["workflow"]["human_review_events"]] == [
        "human_review_workflow_calibration_release"
    ]
    assert {group["target"]["target_ref"] for group in data["workflow"]["target_activity_groups"]} >= {
        "review_item:review_workflow_calibration",
        f"verify_job:{verify_job['job_id']}",
    }
    assert data["workflow"]["recommended_primary_action"] == {
        "kind": "human_review_event",
        "action": "release_review",
        "event_id": "human_review_workflow_calibration_release",
        "label": "Release",
        "target_ref": "human_review_event:human_review_workflow_calibration_release",
    }


def test_knowledge_detail_workflow_recommends_release_after_verify_before_activation(client) -> None:
    _seed_story(client)
    _create_review_item(
        client,
        _review_payload(
            "review_workflow_release_ready",
            "calibration_candidate",
            candidate_text="the gate sighed shut on the unfinished question",
            candidate_payload_json={
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "CAL_RELEASE_READY",
                "text": "the gate sighed shut on the unfinished question",
            },
            active_on_approve=0,
        ),
        key="create-workflow-release-ready",
    )
    _approve_review(client, "review_workflow_release_ready", key="approve-workflow-release-ready")
    _verify_review_candidate(client, "review_workflow_release_ready", key="verify-workflow-release-ready")

    response = client.get("/api/v1/knowledge/calibration_line/CAL_RELEASE_READY")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["active_version"] is None
    assert data["candidate_version"]["review_id"] == "review_workflow_release_ready"
    assert data["workflow"]["recommended_primary_action"] == {
        "kind": "review",
        "action": "release_review",
        "review_id": "review_workflow_release_ready",
        "label": "Release",
        "target_ref": "review_item:review_workflow_release_ready",
    }
