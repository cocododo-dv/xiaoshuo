from __future__ import annotations

from novel_system.db.models import (
    AuthorDraft,
    ChapterGoal,
    ChapterMemory,
    FinalScene,
    ForeshadowTracker,
    LongformDiagnosticCard,
    LongformStructureGuidance,
    ReferenceBook,
    ReferenceBookSegment,
    ReferenceProfile,
    RelationProfile,
    ReviewItem,
    SceneCard,
    SceneRunState,
    VoiceProfile,
    WriterEvaluation,
)
from novel_system.services.bundle_builder import BundleBuilder


def _seed_longform_problem(session) -> None:
    session.add(
        ChapterGoal(
            chapter_id="LTE100",
            planned_scene_count=2,
            chapter_goal="The heroine must choose whether to expose the archive leak.",
            writer_brief_json={
                "chapter_promise": "The archive leak will force a public choice.",
                "ending_question": "Who benefits if the file disappears?",
                "theme_pressure": "private loyalty versus public duty",
            },
        )
    )
    session.add(
        SceneCard(
            scene_id="LTE100_SC01",
            chapter_id="LTE100",
            scene_seq=1,
            pov_character_id="CHAR_A",
            onstage_chars_json=["CHAR_A", "CHAR_B"],
            scene_goal="CHAR_A waits while CHAR_B explains the archive leak.",
            hook="The file vanishes before anyone acts.",
            writer_brief_json={
                "new_information": "The archive key was copied twice.",
                "image_anchor": "blue umbrella",
            },
        )
    )
    session.add(
        SceneCard(
            scene_id="LTE100_SC02",
            chapter_id="LTE100",
            scene_seq=2,
            pov_character_id="CHAR_A",
            onstage_chars_json=["CHAR_A"],
            scene_goal="CHAR_A follows the missing file.",
            is_chapter_last=1,
        )
    )
    session.add(
        SceneRunState(
            scene_id="LTE100_SC01",
            scene_status="archived",
            current_final_scene_row_id="final_LTE100_SC01",
        )
    )
    session.add(SceneRunState(scene_id="LTE100_SC02"))
    session.add(
        FinalScene(
            row_id="final_LTE100_SC01",
            scene_id="LTE100_SC01",
            chapter_id="LTE100",
            content='"Because the archive copied itself, as you know," CHAR_B said. CHAR_A understood everything.',
            source_bundle_id="bundle_LTE100_SC01",
            source_bundle_hash="hash-before",
        )
    )
    session.add(
        ChapterMemory(
            row_id="chapter_mem_LTE100_final",
            chapter_id="LTE100",
            aggregate_stage="final",
            content="Original final aggregate must not be changed.",
            active_flag=1,
            runtime_eligible=1,
        )
    )
    session.add(
        AuthorDraft(
            draft_id="author_draft_LTE100_SC01",
            object_type="scene",
            object_id="LTE100_SC01",
            source_text_ref="final_scene:final_LTE100_SC01",
            content='"Because the archive copied itself, as you know," CHAR_B said. CHAR_A finally realized everything changed forever.',
            revision_no=1,
            status="current",
        )
    )
    session.add(
        WriterEvaluation(
            evaluation_id="writer_eval_LTE100_SC01",
            object_type="scene",
            object_id="LTE100_SC01",
            chapter_id="LTE100",
            scene_id="LTE100_SC01",
            rubric_id="drama_effectiveness_v1",
            overall_score=0.41,
            scores_json={
                "character_agency": 0.33,
                "information_rhythm": 0.38,
                "reader_hook": 0.43,
                "ending_drive": 0.31,
            },
            findings_json=[
                {
                    "dimension": "character_agency",
                    "severity": "major",
                    "issue": "CHAR_A waits through the explanation.",
                    "evidence_excerpt": "CHAR_A waits",
                    "recommendation": "Force CHAR_A to choose what to lose.",
                }
            ],
            revision_brief_json=[],
            requires_human_review=1,
        )
    )
    session.add(
        VoiceProfile(
            row_id="voice_CHAR_A_lte",
            voice_profile_id="VOICE_CHAR_A",
            character_id="CHAR_A",
            content="direct, terse, morally pressed",
            active_flag=1,
            runtime_eligible=1,
        )
    )
    session.add(
        RelationProfile(
            row_id="relation_CHAR_A_CHAR_B_lte",
            relation_profile_id="REL_CHAR_A_CHAR_B",
            left_character_id="CHAR_A",
            right_character_id="CHAR_B",
            content="allies strained by an archive secret",
            active_flag=1,
            runtime_eligible=1,
        )
    )
    session.add(
        ForeshadowTracker(
            row_id="foreshadow_LTE100",
            foreshadow_id="FS-LTE100",
            chapter_id="LTE100",
            scene_id="LTE100_SC01",
            text="The copied archive key has no payoff yet.",
            tracker_status="open",
            active_flag=1,
            runtime_eligible=1,
        )
    )
    session.commit()


def test_longform_editor_diagnose_creates_cards_without_mutating_runtime_text(client, session) -> None:
    _seed_longform_problem(session)

    response = client.post("/api/v1/longform-editor/diagnose", json={})

    assert response.status_code == 200
    data = response.json()["data"]
    card_types = {card["card_type"] for card in data["cards"]}
    assert {
        "character_arc_gap",
        "foreshadow_debt",
        "promise_without_payoff",
        "information_congestion",
        "ending_drive_drop",
    } <= card_types
    assert data["summary"]["open_count"] >= 5
    assert session.get(FinalScene, "final_LTE100_SC01").content.startswith('"Because the archive')
    assert session.get(ChapterMemory, "chapter_mem_LTE100_final").content == "Original final aggregate must not be changed."

    overview = client.get("/api/v1/longform-editor/overview")
    assert overview.status_code == 200
    overview_data = overview.json()["data"]
    assert overview_data["dashboard"]["summary"]["chapter_count"] == 1
    assert overview_data["cards"]["summary"]["open_count"] >= 5


def test_longform_editor_refresh_resolves_missing_cards_and_preserves_dismissed_until_source_changes(client, session) -> None:
    _seed_longform_problem(session)
    first = client.post("/api/v1/longform-editor/diagnose", json={}).json()["data"]
    foreshadow_card = next(card for card in first["cards"] if card["card_type"] == "foreshadow_debt")

    dismiss = client.post(
        f"/api/v1/longform-editor/cards/{foreshadow_card['card_id']}/actions",
        json={"action": "dismiss", "note": "intentional slow burn"},
    )
    assert dismiss.status_code == 200
    assert dismiss.json()["data"]["card"]["status"] == "dismissed"

    tracker = session.get(ForeshadowTracker, "foreshadow_LTE100")
    tracker.tracker_status = "resolved"
    session.commit()

    second = client.post("/api/v1/longform-editor/diagnose", json={}).json()["data"]
    refreshed = session.get(LongformDiagnosticCard, foreshadow_card["card_id"])
    assert refreshed.status == "dismissed"
    assert "foreshadow_debt" not in {
        card["card_type"] for card in second["cards"] if card["status"] == "open"
    }
    resolved_cards = client.get("/api/v1/longform-editor/cards?status=resolved").json()["data"]["items"]
    assert any(card["card_type"] == "foreshadow_debt" for card in resolved_cards) is False


def test_published_longform_guidance_is_reviewed_before_entering_bundle(client, session) -> None:
    _seed_longform_problem(session)
    data = client.post("/api/v1/longform-editor/diagnose", json={}).json()["data"]
    arc_card = next(card for card in data["cards"] if card["card_type"] == "character_arc_gap")

    published = client.post(
        f"/api/v1/longform-editor/cards/{arc_card['card_id']}/publish-guidance",
        json={
            "scope_type": "scene",
            "scope_ref_id": "LTE100_SC01",
            "content": "Force CHAR_A to trade the archive key for public exposure before the scene ends.",
        },
    )
    assert published.status_code == 200
    review_id = published.json()["data"]["review"]["review_id"]
    review = session.get(ReviewItem, review_id)
    assert review.item_type == "longform_structure_guidance"
    assert review.target_collection == "longform_structure_guidance"

    assert session.query(LongformStructureGuidance).count() == 0
    bundle_before = BundleBuilder(session).build("LTE100_SC01")["snapshot"]
    assert "longform_structure_guidance_ids" not in bundle_before["source_version_refs"]
    session.rollback()

    approve = client.post(
        f"/api/v1/review-items/{review_id}/approve",
        json={},
        headers={"X-Idempotency-Key": "approve-longform-structure-guidance"},
    )
    assert approve.status_code == 200
    guidance = session.query(LongformStructureGuidance).one()
    assert guidance.status == "approved"
    assert guidance.runtime_eligible == 1

    session.get(SceneRunState, "LTE100_SC01").bundle_build_count = 0
    bundle_after = BundleBuilder(session).build("LTE100_SC01", force_rebuild=True)["snapshot"]
    assert bundle_after["source_version_refs"]["longform_structure_guidance_ids"] == [guidance.guidance_id]
    assert "Force CHAR_A" in bundle_after["inline_digests"]["longform_structure_guidance"]


def test_reference_safety_extracts_profile_and_scans_exact_and_fuzzy_leakage(client, session) -> None:
    session.add(
        ReferenceBook(
            book_id="refbook_safety",
            title="Archive School",
            author_label="reference",
            source_kind="path",
            source_path="reference.md",
            file_name="reference.md",
            cloud_policy="local_only",
            analysis_focus="style_structure",
            text_checksum="checksum",
            status="completed",
            total_chars=120,
            total_segments=2,
            stats_json={},
        )
    )
    session.add(
        ReferenceBookSegment(
            segment_id="refseg_safety_001",
            book_id="refbook_safety",
            segment_index=1,
            chapter_hint="opening",
            segment_kind="opening",
            start_offset=0,
            end_offset=80,
            text="Professor Meridian carried the glass compass through the rain gate and erased the witness oath.",
        )
    )
    session.add(
        ReferenceProfile(
            profile_id="refprofile_safety",
            book_id="refbook_safety",
            run_id="run_safety",
            title="Archive School profile",
            status="ready",
            profile_json={"narrative_patterns": ["Delay the explanation until the witness oath changes hands."]},
            coverage_json={},
            source_finding_ids_json=[],
        )
    )
    session.commit()

    extracted = client.post("/api/v1/reference-books/refbook_safety/safety-profile/extract", json={})
    assert extracted.status_code == 200
    source_safety = extracted.json()["data"]["profile"]["profile_json"]["source_safety"]
    assert "Professor Meridian" in source_safety["protected_terms"]
    assert source_safety["scene_bridges"]

    scan = client.post(
        "/api/v1/source-safety/scan",
        json={
            "text": "Professor Meridian crossed the rain gate with a glass compass while the witness oath vanished.",
            "source_profile_ids": ["refprofile_safety"],
        },
    )
    assert scan.status_code == 200
    scan_data = scan.json()["data"]
    assert scan_data["safe"] is False
    assert scan_data["risk_count"] >= 2
    assert {"exact_term", "fuzzy_bridge"} <= {risk["risk_type"] for risk in scan_data["risks"]}
