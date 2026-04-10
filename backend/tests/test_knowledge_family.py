from __future__ import annotations

from typing import Any


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
