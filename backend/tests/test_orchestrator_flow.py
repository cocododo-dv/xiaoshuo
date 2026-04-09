from __future__ import annotations

from sqlalchemy.orm import Session

from novel_system.db.models import RelationProfile, VoiceProfile


def seed_story(client, session: Session | None = None) -> None:
    client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": "CH001",
            "planned_scene_count": 3,
            "chapter_goal": "重逢与试探成立",
            "main_plot_push": "旧信线索被正式打开",
            "emotional_target": "由迟疑转为警觉",
            "ending_effect": "留有余波",
        },
        headers={"X-Idempotency-Key": "chapter-seed"},
    )
    client.post(
        "/api/v1/scenes",
        json={
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
        headers={"X-Idempotency-Key": "scene-seed-1"},
    )
    if session is not None:
        seed_traceable_bundle_sources(session)


def seed_traceable_bundle_sources(session) -> None:
    session.add(
        VoiceProfile(
            row_id="voice_profile_VOICE_CHAR_A_v1",
            voice_profile_id="VOICE_CHAR_A",
            version=1,
            character_id="CHAR_A",
            content="short clipped lines; pressure makes the tone harder",
            active_flag=1,
            source_note="test baseline",
        )
    )
    session.add(
        RelationProfile(
            row_id="relation_profile_REL_CHAR_A_CHAR_B_v1",
            relation_profile_id="REL_CHAR_A_CHAR_B",
            left_character_id="CHAR_A",
            right_character_id="CHAR_B",
            version=1,
            content="reunion tension; B knows slightly more than A",
            active_flag=1,
            source_note="test baseline",
        )
    )
    session.commit()


def test_run_full_scene_records_voice_and_relation_bundle_provenance(client, session) -> None:
    seed_story(client, session=session)

    response = client.post(
        "/api/v1/scenes/CH001_SC01/run/full",
        headers={"X-Idempotency-Key": "scene-run-provenance"},
    )

    assert response.status_code == 200
    bundle_id = response.json()["data"]["current_bundle_id"]
    worksheet = client.get(f"/api/v1/interop/export/bundle-worksheet/{bundle_id}")
    assert worksheet.status_code == 200

    snapshot = worksheet.json()["data"]["snapshot"]
    source_refs = snapshot["source_version_refs"]
    assert source_refs["voice_profile_id"] == "VOICE_CHAR_A"
    assert source_refs["voice_profile_row_id"] == "voice_profile_VOICE_CHAR_A_v1"
    assert source_refs["voice_profile_version"] == 1
    assert source_refs["relation_profile_id"] == "REL_CHAR_A_CHAR_B"
    assert source_refs["relation_profile_row_id"] == "relation_profile_REL_CHAR_A_CHAR_B_v1"
    assert source_refs["relation_profile_version"] == 1
    assert snapshot["inline_digests"]["voice_card"] == "short clipped lines; pressure makes the tone harder"
    assert snapshot["inline_digests"]["relation_card"] == "reunion tension; B knows slightly more than A"


def test_run_full_scene_fails_when_traceable_bundle_sources_missing(client) -> None:
    seed_story(client)

    response = client.post(
        "/api/v1/scenes/CH001_SC01/run/full",
        headers={"X-Idempotency-Key": "scene-run-missing-bundle-sources"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BUNDLE_SOURCE_MISSING"


def test_run_full_scene_archives_memory_and_updates_status(client, session) -> None:
    seed_story(client, session=session)

    response = client.post(
        "/api/v1/scenes/CH001_SC01/run/full",
        headers={"X-Idempotency-Key": "scene-run-1"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["scene_status"] == "archived"
    assert data["current_bundle_id"]
    assert data["current_final_scene_row_id"]

    workbench = client.get("/api/v1/scenes/CH001_SC01/workbench")
    assert workbench.status_code == 200
    assert workbench.json()["data"]["scene_memory"]
