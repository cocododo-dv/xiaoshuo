from __future__ import annotations

from novel_system.db.models import ChapterGoal, SceneBlueprint, SceneCard, SceneRunState
from novel_system.services.bundle_builder import BundleBuilder


CHAPTER_ID = "BP100"
SCENE_ID = "BP100_SC01"


def _seed_scene(session) -> None:
    session.add(
        ChapterGoal(
            chapter_id=CHAPTER_ID,
            planned_scene_count=1,
            chapter_goal="A quiet reunion must turn into a choice.",
            main_plot_push="move from suspicion to action",
            emotional_target="trust becomes costly",
            ending_effect="leave the reader asking what was hidden",
            writer_brief_json={
                "chapter_promise": "a reunion reveals a dangerous silence",
                "escalation_path": "warmth, evasion, decision",
                "ending_question": "why does the friend hide the name",
            },
        )
    )
    session.add(
        SceneCard(
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            scene_seq=1,
            scene_goal="The protagonist asks for the missing name and must decide whether to trust an old friend.",
            beats_json=["ask for the name", "old friend deflects", "protagonist chooses to investigate"],
            exit_change="The old friend becomes a suspect.",
            hook="The teacup stills when the name is spoken.",
            writer_brief_json={
                "character_desire": "get the truth",
                "obstacle": "the friend answers with charm instead of facts",
                "choice_under_pressure": "trust the friend or investigate alone",
                "power_shift": "the protagonist stops asking permission",
                "new_information": "the friend recognizes the missing name",
                "emotional_turn": "warmth becomes suspicion",
                "image_anchor": "the still teacup",
                "reader_aftertaste": "affection now feels dangerous",
            },
        )
    )
    session.add(SceneRunState(scene_id=SCENE_ID, scene_status="ready"))
    session.commit()


def test_literary_blueprint_endpoint_persists_latest_and_supersedes_previous(client, session) -> None:
    _seed_scene(session)

    first = client.post(
        f"/api/v1/scenes/{SCENE_ID}/literary-blueprint",
        headers={"X-Idempotency-Key": "blueprint-first"},
    )
    assert first.status_code == 200
    first_payload = first.json()["data"]

    assert first_payload["scene_id"] == SCENE_ID
    assert first_payload["status"] == "accepted"
    assert set(first_payload["blueprint_json"]) == {
        "visible_desire",
        "forced_choice",
        "price_paid",
        "information_release",
        "relationship_turn",
        "image_anchor",
        "ending_action",
        "next_scene_pull",
        "anti_summary_rule",
    }
    assert first_payload["blueprint_json"]["forced_choice"]
    assert first_payload["blueprint_json"]["ending_action"]

    second = client.post(
        f"/api/v1/scenes/{SCENE_ID}/literary-blueprint",
        headers={"X-Idempotency-Key": "blueprint-second"},
    )
    assert second.status_code == 200
    second_payload = second.json()["data"]

    assert second_payload["row_id"] != first_payload["row_id"]
    assert session.get(SceneBlueprint, first_payload["row_id"]).status == "superseded"
    assert session.get(SceneBlueprint, second_payload["row_id"]).status == "accepted"


def test_workbench_and_bundle_show_the_blueprint_used_for_generation(client, session) -> None:
    _seed_scene(session)
    blueprint = client.post(
        f"/api/v1/scenes/{SCENE_ID}/literary-blueprint",
        headers={"X-Idempotency-Key": "blueprint-workbench"},
    ).json()["data"]

    workbench = client.get(f"/api/v1/scenes/{SCENE_ID}/workbench").json()["data"]
    assert workbench["literary_blueprint"]["row_id"] == blueprint["row_id"]
    assert workbench["literary_blueprint"]["blueprint_json"]["image_anchor"] == "the still teacup"

    bundle = BundleBuilder(session).build(SCENE_ID)
    snapshot = bundle["snapshot"]
    assert snapshot["source_version_refs"]["scene_blueprint_row_id"] == blueprint["row_id"]
    assert "scene_blueprint" in snapshot["inline_digests"]
    assert "forced_choice" in snapshot["inline_digests"]["scene_blueprint"]


def test_legacy_v1_blueprint_rows_still_surface_in_workbench_and_bundle(client, session) -> None:
    _seed_scene(session)
    legacy = SceneBlueprint(
        row_id="scene_blueprint_legacy_v1",
        scene_id=SCENE_ID,
        chapter_id=CHAPTER_ID,
        source_bundle_id="legacy_bundle",
        source_bundle_hash="legacy_hash",
        blueprint_json={
            "choice_under_pressure": "trust the friend or investigate alone",
            "ending_reader_question": "why the name was hidden",
            "image_promise": "the still teacup",
        },
        status="accepted",
    )
    session.add(legacy)
    session.commit()

    workbench = client.get(f"/api/v1/scenes/{SCENE_ID}/workbench").json()["data"]
    assert workbench["literary_blueprint"]["row_id"] == legacy.row_id
    assert workbench["literary_blueprint"]["blueprint_json"]["choice_under_pressure"] == "trust the friend or investigate alone"

    snapshot = BundleBuilder(session).build(SCENE_ID)["snapshot"]
    assert snapshot["source_version_refs"]["scene_blueprint_row_id"] == legacy.row_id
    assert "choice_under_pressure" in snapshot["inline_digests"]["scene_blueprint"]
