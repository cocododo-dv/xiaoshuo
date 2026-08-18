from __future__ import annotations

import logging
from types import SimpleNamespace

from novel_system.db.models import (
    ChapterGoal,
    FinalScene,
    SceneCard,
    SceneRunState,
    SnowflakeArtifact,
    StoryProject,
)
from novel_system.services.scene_execution import SceneExecutionContractService
from novel_system.services.catalog import CatalogService


PROJECT_ID = "CAUSAL_ORDER_PROJECT"
FIRST_CHAPTER_ID = "CAUSAL_ORDER_CH_A"
SECOND_CHAPTER_ID = "CAUSAL_ORDER_CH_B"
FIRST_SCENE_ID = "CAUSAL_ORDER_CH_A_SC01"
SECOND_SCENE_ID = "CAUSAL_ORDER_CH_B_SC01"


def _seed_cross_chapter_skeleton(session, *, anchor_mode: str = "none"):
    project = StoryProject(
        project_id=PROJECT_ID,
        title="Causal order",
        outline_text="A two-scene causal chain.",
    )
    first_chapter = ChapterGoal(
        chapter_id=FIRST_CHAPTER_ID,
        project_id=PROJECT_ID,
        display_order=1,
        planned_scene_count=1,
        chapter_goal="establish the premise",
    )
    second_chapter = ChapterGoal(
        chapter_id=SECOND_CHAPTER_ID,
        project_id=PROJECT_ID,
        display_order=2,
        planned_scene_count=1,
        chapter_goal="use the premise",
    )
    first_scene = SceneCard(
        scene_id=FIRST_SCENE_ID,
        chapter_id=FIRST_CHAPTER_ID,
        project_id=PROJECT_ID,
        scene_seq=1,
        scene_goal="cause",
    )
    second_scene = SceneCard(
        scene_id=SECOND_SCENE_ID,
        chapter_id=SECOND_CHAPTER_ID,
        project_id=PROJECT_ID,
        scene_seq=1,
        scene_goal="effect",
    )
    chain = [
        {
            "step_index": 0,
            "description": "unresolved cross-chapter premise",
            "why_necessary": "the later effect depends on it",
            "state_before": "unknown",
            "state_after": "premise established",
        },
        {
            "step_index": 1,
            "description": "later effect",
            "why_necessary": "complete the chain",
            "state_before": "premise established",
            "state_after": "effect credible",
            "depends_on_index": 0,
        },
    ]
    if anchor_mode == "complete":
        chain[0]["scene_id"] = FIRST_SCENE_ID
        chain[1]["scene_id"] = SECOND_SCENE_ID
    elif anchor_mode == "partial":
        chain[0]["scene_id"] = FIRST_SCENE_ID
    elif anchor_mode != "none":
        raise ValueError(f"unsupported anchor mode: {anchor_mode}")

    artifact = SnowflakeArtifact(
        artifact_id="CAUSAL_ORDER_ARTIFACT",
        project_id=PROJECT_ID,
        step_key="scene_details",
        version=1,
        status="approved",
        artifact_json={
            "causal_skeleton": {
                "controlling_idea": "effects require causes",
                "ending_state": "effect becomes credible",
                "chain": chain,
            }
        },
    )
    # The models intentionally do not declare ORM relationships, so SQLite FK
    # enforcement requires explicit parent-before-child flush boundaries.
    session.add(project)
    session.flush()
    session.add_all([first_chapter, second_chapter])
    session.flush()
    session.add_all([first_scene, second_scene, artifact])
    session.commit()
    return project, first_chapter, second_chapter, first_scene, second_scene


def _diagnostic_codes(contract) -> set[str]:
    return {
        diagnostic["code"]
        for diagnostic in contract.payload_json.get("causal_readiness_diagnostics", [])
    }


def _mark_scene_canonically_complete(
    session,
    *,
    row_id: str,
    scene_id: str,
    chapter_id: str,
    content: str,
) -> FinalScene:
    final = FinalScene(
        row_id=row_id,
        scene_id=scene_id,
        chapter_id=chapter_id,
        content=content,
        source_bundle_id=f"{row_id}_BUNDLE",
        source_bundle_hash=f"{row_id}_HASH",
    )
    session.add(final)
    session.flush()
    session.add(
        SceneRunState(
            scene_id=scene_id,
            current_final_scene_row_id=row_id,
        )
    )
    session.commit()
    return final


def test_causal_readiness_maps_first_cross_chapter_scene_to_step_zero(session) -> None:
    project, _first_chapter, _second_chapter, _first_scene, second_scene = (
        _seed_cross_chapter_skeleton(session)
    )
    service = SceneExecutionContractService(session)

    initial_contract = service.generate(second_scene.scene_id)
    initial_warning = initial_contract.payload_json.get("causal_readiness_warning")
    assert initial_warning is not None
    assert "unresolved cross-chapter premise" in initial_warning
    assert _diagnostic_codes(initial_contract) == {
        "CAUSAL_READINESS_ORDINAL_FALLBACK"
    }

    _mark_scene_canonically_complete(
        session,
        row_id="CAUSAL_ORDER_FINAL_A",
        scene_id=FIRST_SCENE_ID,
        chapter_id=FIRST_CHAPTER_ID,
        content="The premise is now established.",
    )

    # The first canonical scene is ordinal 1 but skeleton step 0. Completing it
    # must satisfy the second scene's dependency even though both local seqs are 1.
    refreshed_contract = service.generate(second_scene.scene_id)
    assert refreshed_contract.contract_id != initial_contract.contract_id
    assert "causal_readiness_warning" not in refreshed_contract.payload_json
    assert _diagnostic_codes(refreshed_contract) == {
        "CAUSAL_READINESS_ORDINAL_FALLBACK"
    }


def test_causal_readiness_recomputes_after_chapter_reorder(session) -> None:
    project, first_chapter, second_chapter, first_scene, second_scene = (
        _seed_cross_chapter_skeleton(session)
    )
    service = SceneExecutionContractService(session)

    first_contract = service.generate(second_scene.scene_id)
    assert "causal_readiness_warning" in first_contract.payload_json
    assert _diagnostic_codes(first_contract) == {
        "CAUSAL_READINESS_ORDINAL_FALLBACK"
    }

    CatalogService(session).reorder_chapters(
        project.project_id,
        [second_chapter.chapter_id, first_chapter.chapter_id],
    )
    session.commit()

    reordered_contract = service.generate(second_scene.scene_id)
    assert reordered_contract.contract_id != first_contract.contract_id
    assert "causal_readiness_warning" not in reordered_contract.payload_json
    assert _diagnostic_codes(reordered_contract) == {
        "CAUSAL_READINESS_ORDINAL_FALLBACK"
    }
    session.commit()
    session.refresh(first_scene)
    session.refresh(second_scene)
    assert first_scene.scene_seq == second_scene.scene_seq == 1

    CatalogService(session).reorder_chapters(
        project.project_id,
        [first_chapter.chapter_id, second_chapter.chapter_id],
    )
    session.commit()

    restored_contract = service.generate(second_scene.scene_id)
    assert restored_contract.contract_id != reordered_contract.contract_id
    assert "causal_readiness_warning" in restored_contract.payload_json


def test_complete_scene_anchors_survive_catalog_reorder(session) -> None:
    project, first_chapter, second_chapter, _first_scene, second_scene = (
        _seed_cross_chapter_skeleton(session, anchor_mode="complete")
    )
    service = SceneExecutionContractService(session)

    initial_contract = service.generate(second_scene.scene_id)
    assert "causal_readiness_warning" in initial_contract.payload_json
    assert "causal_readiness_diagnostics" not in initial_contract.payload_json

    CatalogService(session).reorder_chapters(
        project.project_id,
        [second_chapter.chapter_id, first_chapter.chapter_id],
    )
    session.commit()

    reordered_contract = service.generate(second_scene.scene_id)
    assert reordered_contract.contract_id != initial_contract.contract_id
    assert "causal_readiness_warning" in reordered_contract.payload_json
    assert "causal_readiness_diagnostics" not in reordered_contract.payload_json

    _mark_scene_canonically_complete(
        session,
        row_id="CAUSAL_ANCHORED_FINAL_A",
        scene_id=FIRST_SCENE_ID,
        chapter_id=FIRST_CHAPTER_ID,
        content="The anchored prerequisite is complete.",
    )

    completed_contract = service.generate(second_scene.scene_id)
    assert completed_contract.contract_id != reordered_contract.contract_id
    assert "causal_readiness_warning" not in completed_contract.payload_json
    assert "causal_readiness_diagnostics" not in completed_contract.payload_json


def test_historical_final_without_current_authority_pointer_does_not_satisfy_dependency(
    session,
) -> None:
    _project, _first_chapter, _second_chapter, _first_scene, second_scene = (
        _seed_cross_chapter_skeleton(session, anchor_mode="complete")
    )
    service = SceneExecutionContractService(session)
    historical = FinalScene(
        row_id="CAUSAL_HISTORICAL_FINAL_A",
        scene_id=FIRST_SCENE_ID,
        chapter_id=FIRST_CHAPTER_ID,
        content="A historical row that is not the current authority.",
        source_bundle_id="CAUSAL_HISTORICAL_BUNDLE_A",
        source_bundle_hash="CAUSAL_HISTORICAL_HASH_A",
        superseded_by_final_scene_row_id="CAUSAL_NEWER_FINAL_A",
    )
    session.add(historical)
    session.commit()

    contract = service.generate(second_scene.scene_id)

    assert "causal_readiness_warning" in contract.payload_json
    assert "unresolved cross-chapter premise" in contract.payload_json[
        "causal_readiness_warning"
    ]


def test_partial_scene_anchors_are_diagnosed_without_ordinal_mixing(session) -> None:
    _project, _first_chapter, _second_chapter, _first_scene, second_scene = (
        _seed_cross_chapter_skeleton(session, anchor_mode="partial")
    )
    service = SceneExecutionContractService(session)

    contract = service.generate(second_scene.scene_id)

    assert "causal_readiness_warning" not in contract.payload_json
    assert _diagnostic_codes(contract) == {"CAUSAL_ANCHORS_PARTIAL"}
    assert "CAUSAL_READINESS_ORDINAL_FALLBACK" not in _diagnostic_codes(contract)
    assert "causal_readiness_diagnostic(advisory)" in contract.missing_fields_json


def test_causal_readiness_internal_error_is_logged_and_diagnosed(
    session,
    monkeypatch,
    caplog,
) -> None:
    _project, _first_chapter, _second_chapter, _first_scene, second_scene = (
        _seed_cross_chapter_skeleton(session, anchor_mode="complete")
    )
    service = SceneExecutionContractService(session)

    import novel_system.services.reverse_causal_skeleton as causal_module

    def _raise_internal_error(*_args, **_kwargs):
        raise RuntimeError("forced readiness failure")

    monkeypatch.setattr(
        causal_module,
        "validate_scene_causal_readiness",
        _raise_internal_error,
    )

    with caplog.at_level(logging.ERROR, logger="novel_system.services.scene_execution"):
        contract = service.generate(second_scene.scene_id)

    assert "causal_readiness_warning" not in contract.payload_json
    assert _diagnostic_codes(contract) == {
        "CAUSAL_READINESS_INTERNAL_ERROR"
    }
    assert "causal_readiness_diagnostic(advisory)" in contract.missing_fields_json
    record = next(
        record
        for record in caplog.records
        if getattr(record, "event_code", None) == "CAUSAL_READINESS_INTERNAL_ERROR"
    )
    assert record.project_id == PROJECT_ID
    assert record.scene_id == SECOND_SCENE_ID
    assert record.error_type == "RuntimeError"


def test_builder_preserves_complete_scene_anchors() -> None:
    from novel_system.services.reverse_causal_skeleton import (
        build_reverse_skeleton,
        format_skeleton_for_prompt,
    )

    skeleton = build_reverse_skeleton(
        "effects require causes",
        "ending",
        [
            {"description": "earlier", "scene_id": "SCENE_A"},
            {"description": "later", "scene_id": "SCENE_B"},
        ],
        ending_scene_id="SCENE_C",
        turning_points_order="opening_to_ending",
    )

    assert skeleton.scene_anchor_mode == "scene_id"
    assert [link.description for link in skeleton.chain] == [
        "earlier",
        "later",
        "ending",
    ]
    assert {link.scene_id for link in skeleton.chain} == {
        "SCENE_A",
        "SCENE_B",
        "SCENE_C",
    }
    assert "execution order opening → ending" in format_skeleton_for_prompt(skeleton)

    # The builder's documented legacy default remains reverse input, so callers
    # that already provide ending-to-opening points keep the same result.
    legacy = build_reverse_skeleton(
        "effects require causes",
        "ending",
        [
            {"description": "later"},
            {"description": "earlier"},
        ],
    )
    assert [link.description for link in legacy.chain] == [
        "earlier",
        "later",
        "ending",
    ]


def test_snowflake_skeleton_round_trip_preserves_chronology_for_scene_execution(
    session,
) -> None:
    from novel_system.services.snowflake_planner import (
        _build_causal_skeleton_from_synopsis,
    )

    project_id = "CAUSAL_SNOWFLAKE_ROUND_TRIP"
    chapter_id = "CAUSAL_SNOWFLAKE_CHAPTER"
    project = StoryProject(
        project_id=project_id,
        title="Chronological causal round trip",
        outline_text="Consequences require established causes.",
    )
    chapter = ChapterGoal(
        chapter_id=chapter_id,
        project_id=project_id,
        display_order=1,
        planned_scene_count=3,
        chapter_goal="execute a three-step causal chain",
    )
    scenes = [
        SceneCard(
            scene_id=f"CAUSAL_SNOWFLAKE_SCENE_{ordinal}",
            chapter_id=chapter_id,
            project_id=project_id,
            scene_seq=ordinal,
            scene_goal=f"causal step {ordinal}",
        )
        for ordinal in range(1, 4)
    ]
    synopsis = SimpleNamespace(artifact_json={
        "paragraphs": [
            "Opening context before the causal turning points.",
            {
                "text": "The earliest cause is established.",
                "character_state_before": "unaware",
                "character_state_after": "clue known",
            },
            {
                "text": "The later consequence becomes possible.",
                "state_before": "clue known",
                "state_after": "decision made",
            },
            "The ending proves the controlling idea.",
        ]
    })
    skeleton_payload = _build_causal_skeleton_from_synopsis(
        project,
        synopsis,
        zh=False,
    )

    assert skeleton_payload is not None
    assert skeleton_payload["chain_order"] == "opening_to_ending"
    assert skeleton_payload["ending_state"] == (
        "The ending proves the controlling idea."
    )
    assert [link["description"] for link in skeleton_payload["chain"]] == [
        "The earliest cause is established.",
        "The later consequence becomes possible.",
        "The ending proves the controlling idea.",
    ]
    assert skeleton_payload["chain"][0]["character_state_before"] == "unaware"
    assert skeleton_payload["chain"][0]["character_state_after"] == "clue known"
    assert skeleton_payload["chain"][1]["character_state_before"] == "clue known"
    assert skeleton_payload["chain"][1]["character_state_after"] == "decision made"
    assert skeleton_payload["integrity_evaluated"] is True
    assert skeleton_payload["integrity_valid"] is True

    artifact = SnowflakeArtifact(
        artifact_id="CAUSAL_SNOWFLAKE_ARTIFACT",
        project_id=project_id,
        step_key="long_synopsis",
        version=1,
        status="approved",
        artifact_json={"causal_skeleton": skeleton_payload},
    )
    session.add(project)
    session.flush()
    session.add(chapter)
    session.flush()
    session.add_all([*scenes, artifact])
    session.commit()

    # The second catalog scene consumes skeleton step 1. Its only unresolved
    # prerequisite must be the earliest cause (step 0), not the later point
    # that the old accidental reversal placed at step 0.
    contract = SceneExecutionContractService(session).generate(scenes[1].scene_id)
    warning = contract.payload_json.get("causal_readiness_warning") or ""
    assert "The earliest cause is established." in warning
    assert "The later consequence becomes possible." not in warning
    assert _diagnostic_codes(contract) == {
        "CAUSAL_READINESS_ORDINAL_FALLBACK"
    }
    assert "causal_prerequisite(advisory)" in contract.missing_fields_json


def test_skeleton_deserializer_accepts_legacy_aliases_and_missing_ending() -> None:
    from novel_system.services.reverse_causal_skeleton import deserialize_skeleton

    skeleton = deserialize_skeleton({
        "controlling_idea": "legacy remains readable",
        "chain": [
            {
                "step_index": 0,
                "description": "legacy ending",
                "state_before": "before",
                "state_after": "after",
            }
        ],
    })

    assert skeleton.ending_state == "legacy ending"
    assert skeleton.chain[0].character_state_before == "before"
    assert skeleton.chain[0].character_state_after == "after"

    explicitly_reversed = deserialize_skeleton({
        "chain_order": "ending_to_opening",
        "ending_state": "ending",
        "chain": [
            {
                "step_index": 0,
                "description": "ending",
                "depends_on_index": 1,
            },
            {
                "step_index": 1,
                "description": "cause",
            },
        ],
    })
    assert [link.description for link in explicitly_reversed.chain] == [
        "cause",
        "ending",
    ]
    assert [link.step_index for link in explicitly_reversed.chain] == [0, 1]
    assert explicitly_reversed.chain[1].depends_on_index == 0
