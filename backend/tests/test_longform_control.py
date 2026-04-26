from __future__ import annotations

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    FinalScene,
    ForeshadowTracker,
    LlmCall,
    QcReport,
    RelationProfile,
    RevisionCandidate,
    SceneCard,
    SceneRunState,
    VoiceProfile,
    WriterEvaluation,
)


def test_longform_control_dashboard_aggregates_read_only_signals(client, session) -> None:
    session.add(
        ChapterGoal(
            chapter_id="LFC100",
            planned_scene_count=2,
            chapter_goal="Keep the investigation moving",
            main_plot_push="open a new suspect",
            emotional_target="trust starts to fracture",
            ending_effect="leave a hard question",
        )
    )
    session.add(ChapterState(chapter_id="LFC100", current_phase="drafting", chapter_passed_scene_count=1))
    session.add(
        SceneCard(
            scene_id="LFC100_SC01",
            chapter_id="LFC100",
            scene_seq=1,
            pov_character_id="CHAR_A",
            onstage_chars_json=["CHAR_A", "CHAR_B"],
            scene_goal="CHAR_A presses CHAR_B for the missing name",
            beats_json=["press", "deflect"],
            hook="CHAR_B lies badly",
            writer_brief_json={
                "image_anchor": "blue umbrella",
                "power_shift": "CHAR_B keeps leverage",
                "reader_aftertaste": "affection feels dangerous",
            },
        )
    )
    session.add(
        SceneCard(
            scene_id="LFC100_SC02",
            chapter_id="LFC100",
            scene_seq=2,
            pov_character_id="CHAR_A",
            onstage_chars_json=["CHAR_A"],
            scene_goal="CHAR_A acts on the lie",
            beats_json=[],
            is_chapter_last=1,
            writer_brief_json={
                "image_anchor": "blue umbrella",
                "power_shift": "CHAR_A takes leverage",
                "reader_aftertaste": "the umbrella becomes evidence",
            },
        )
    )
    session.add(
        SceneRunState(
            scene_id="LFC100_SC01",
            scene_status="archived",
            current_final_scene_row_id="final_LFC100_SC01",
            current_qc_report_id="qc_LFC100_SC01",
        )
    )
    session.add(SceneRunState(scene_id="LFC100_SC02", scene_status="ready"))
    session.add(
        FinalScene(
            row_id="final_LFC100_SC01",
            scene_id="LFC100_SC01",
            chapter_id="LFC100",
            content="CHAR_A asks. CHAR_B smiles too quickly.",
            source_bundle_id="bundle_LFC100_SC01",
            source_bundle_hash="hash_LFC100_SC01",
        )
    )
    session.add(
        WriterEvaluation(
            evaluation_id="writer_eval_LFC100_SC01",
            object_type="scene",
            object_id="LFC100_SC01",
            chapter_id="LFC100",
            scene_id="LFC100_SC01",
            rubric_id="drama_effectiveness_v1",
            overall_score=0.42,
            scores_json={"character_agency": 0.41, "power_shift": 0.39, "ending_drive": 0.58},
            findings_json=[
                {
                    "dimension": "character_agency",
                    "severity": "major",
                    "issue": "CHAR_A mostly waits",
                    "recommendation": "give CHAR_A a visible choice",
                    "evidence_excerpt": "asks",
                    "evidence_location": "scene 1",
                    "why_it_matters": "the protagonist arc needs action",
                }
            ],
            revision_brief_json=[],
            requires_human_review=1,
        )
    )
    session.add(
        RevisionCandidate(
            revision_id="revision_LFC100_SC01",
            evaluation_id="writer_eval_LFC100_SC01",
            object_type="scene",
            object_id="LFC100_SC01",
            chapter_id="LFC100",
            scene_id="LFC100_SC01",
            revision_type="scene_revision",
            source_text_ref="final_scene:final_LFC100_SC01",
            proposed_text="candidate",
            diff_summary_json={"changed_dimensions": ["character_agency"], "candidate_kind": "full_scene_rewrite"},
            status="candidate",
        )
    )
    session.add(
        ForeshadowTracker(
            row_id="foreshadow_row_LFC100",
            foreshadow_id="FS-LFC100",
            chapter_id="LFC100",
            scene_id="LFC100_SC01",
            text="CHAR_B knows the missing name",
            tracker_status="open",
            active_flag=1,
            runtime_eligible=1,
        )
    )
    session.add(
        VoiceProfile(
            row_id="voice_CHAR_A_v1",
            voice_profile_id="voice_CHAR_A",
            character_id="CHAR_A",
            content="direct, clipped",
            active_flag=1,
        )
    )
    session.add(
        RelationProfile(
            row_id="relation_A_B_v1",
            relation_profile_id="relation_A_B",
            left_character_id="CHAR_A",
            right_character_id="CHAR_B",
            content="old allies under pressure",
            active_flag=1,
        )
    )
    session.add(
        QcReport(
            qc_report_id="qc_LFC100_SC01",
            scene_id="LFC100_SC01",
            chapter_id="LFC100",
            qc_type="soft",
            pass_flag=0,
            next_action="human_review",
            issues_json=[{"severity": "blocker", "issue": "continuity gap"}],
        )
    )
    session.add(
        LlmCall(
            llm_call_id="llm_LFC100_error",
            node_id="writer_scene_diagnosis",
            chapter_id="LFC100",
            scene_id="LFC100_SC01",
            error_code="SCHEMA_ERROR",
        )
    )
    session.commit()

    response = client.get("/api/v1/longform-control")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["summary"]["chapter_count"] == 1
    assert data["summary"]["open_revision_candidate_count"] == 1
    assert data["summary"]["open_foreshadow_count"] == 1
    assert data["chapters"][0]["chapter_id"] == "LFC100"
    assert data["chapters"][0]["completion_status"] == "partial"
    assert data["chapters"][0]["generated_scene_count"] == 1
    assert data["chapters"][0]["missing_scene_ids"] == ["LFC100_SC02"]
    assert data["rhythm_map"][0]["qc_blocker_count"] == 1
    assert data["character_arcs"][0]["character_id"] == "CHAR_A"
    assert data["character_arcs"][0]["pov_scene_count"] == 2
    assert data["character_arcs"][0]["low_agency_finding_count"] == 1
    assert data["foreshadow_debts"][0]["debt_state"] == "open"
    assert data["foreshadow_debts"][0]["text"] == "CHAR_B knows the missing name"
    assert {alert["alert_type"] for alert in data["continuity_alerts"]} >= {
        "aggregate_missing",
        "missing_final_scene",
        "writer_human_review",
        "llm_error",
    }
    assert data["revision_pressure"][0]["chapter_id"] == "LFC100"
    assert data["revision_pressure"][0]["open_candidate_count"] == 1
    assert data["revision_pressure"][0]["top_low_dimensions"][0]["dimension"] == "power_shift"
    assert data["motif_tracking"][0]["motif"] == "blue umbrella"
    assert data["motif_tracking"][0]["repeat_risk"] is False
    assert data["motif_tracking"][0]["transformation_status"] == "transformed"
    assert "CHAR_A takes leverage" in data["motif_tracking"][0]["transformation_note"]
