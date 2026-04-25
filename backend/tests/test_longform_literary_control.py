from __future__ import annotations

from novel_system.db.models import ChapterGoal, ForeshadowTracker, RelationProfile, SceneCard, WriterEvaluation


def test_longform_control_exposes_literary_signal_layers(client, session) -> None:
    session.add(
        ChapterGoal(
            chapter_id="LITCTRL100",
            planned_scene_count=1,
            chapter_goal="A promise becomes a debt.",
            writer_brief_json={
                "chapter_promise": "find out who betrayed the archive",
                "ending_question": "who moved the ledger",
                "payoff_target": "pay the ledger question by chapter three",
            },
        )
    )
    session.add(
        SceneCard(
            scene_id="LITCTRL100_SC01",
            chapter_id="LITCTRL100",
            scene_seq=1,
            pov_character_id="CHAR_A",
            onstage_chars_json=["CHAR_A", "CHAR_B"],
            scene_goal="CHAR_A discovers CHAR_B hid the ledger.",
            hook="The ledger is gone.",
            writer_brief_json={
                "choice_under_pressure": "accuse CHAR_B or keep watching",
                "power_shift": "CHAR_A gets leverage",
                "new_information": "CHAR_B knew the ledger was missing",
                "image_anchor": "wet ledger mark",
                "reader_aftertaste": "the ally may be the threat",
            },
        )
    )
    session.add(
        WriterEvaluation(
            evaluation_id="writer_eval_litctrl_scene",
            object_type="scene",
            object_id="LITCTRL100_SC01",
            chapter_id="LITCTRL100",
            scene_id="LITCTRL100_SC01",
            rubric_id="drama_effectiveness_v1",
            lens="aggregate",
            overall_score=0.48,
            scores_json={"character_agency": 0.42, "power_shift": 0.52, "information_rhythm": 0.44, "reader_hook": 0.46},
            findings_json=[
                {
                    "dimension": "reader_hook",
                    "severity": "major",
                    "issue": "The ledger hook is opened but not shaped as a debt.",
                    "recommendation": "Make the promised payoff visible.",
                    "evidence_excerpt": "The ledger is gone.",
                    "evidence_location": "scene hook",
                    "why_it_matters": "The reader needs to know what question to carry.",
                }
            ],
            revision_brief_json=[],
            requires_human_review=1,
        )
    )
    session.add(
        RelationProfile(
            row_id="relation_litctrl_a_b",
            relation_profile_id="relation_litctrl_a_b",
            left_character_id="CHAR_A",
            right_character_id="CHAR_B",
            content="allies with a secret over the missing ledger",
            active_flag=1,
        )
    )
    session.add(
        ForeshadowTracker(
            row_id="fs_litctrl_100",
            foreshadow_id="FS-LITCTRL100",
            chapter_id="LITCTRL100",
            scene_id="LITCTRL100_SC01",
            text="The ledger should pay off later",
            tracker_status="open",
            active_flag=1,
            runtime_eligible=1,
        )
    )
    session.commit()

    data = client.get("/api/v1/longform-control").json()["data"]

    assert data["promise_payoff"][0]["chapter_id"] == "LITCTRL100"
    assert data["promise_payoff"][0]["chapter_promise"] == "find out who betrayed the archive"
    assert data["character_arc_timeline"][0]["character_id"] == "CHAR_A"
    assert data["character_arc_timeline"][0]["low_agency"] is True
    assert data["relation_tension_matrix"][0]["pair"] == ["CHAR_A", "CHAR_B"]
    assert data["motif_tracking"][0]["image_anchor"] == "wet ledger mark"
    assert data["information_release_curve"][0]["release_type"] == "reveal"
    assert data["reader_hook_debts"][0]["debt_state"] == "open"
