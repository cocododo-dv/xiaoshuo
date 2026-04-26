from __future__ import annotations

from novel_system.db.models import (
    AuthorDraft,
    AuthorPreferenceProfile,
    ChapterGoal,
    ChapterMemory,
    ChapterState,
    FinalScene,
    LongformDiagnosticCard,
    PassagePatchCandidate,
    SceneCard,
    SceneRunState,
    WorkProfile,
    WriterEvaluation,
)


def _seed_author_desk_target(session) -> None:
    session.add(
        ChapterGoal(
            chapter_id="DESK100",
            planned_scene_count=2,
            chapter_goal="林岑必须决定是否公开潮汐档案。",
            writer_brief_json={"chapter_promise": "证据会迫使她牺牲一种安全。"},
        )
    )
    session.add(ChapterState(chapter_id="DESK100", current_phase="drafting"))
    session.add(
        SceneCard(
            scene_id="DESK100_SC01",
            chapter_id="DESK100",
            scene_seq=1,
            scene_goal="林岑在档案室藏起证据。",
            beats_json=["发现录音", "许望追问", "她关上门"],
            hook="第二段心跳声浮出。",
        )
    )
    session.add(
        SceneRunState(
            scene_id="DESK100_SC01",
            scene_status="archived",
            current_final_scene_row_id="final_scene_DESK100_SC01_v1",
            current_bundle_id="bundle_DESK100_SC01_v1",
            current_bundle_hash="hash_DESK100_SC01_v1",
        )
    )
    session.add(
        FinalScene(
            row_id="final_scene_DESK100_SC01_v1",
            scene_id="DESK100_SC01",
            chapter_id="DESK100",
            content="运行终稿：她公开录音前先关上门。",
            status="approved",
            source_bundle_id="bundle_DESK100_SC01_v1",
            source_bundle_hash="hash_DESK100_SC01_v1",
        )
    )
    session.add(
        ChapterMemory(
            row_id="chapter_memory_final_DESK100_v1",
            chapter_id="DESK100",
            aggregate_stage="final",
            content="最终聚合稿：档案室的录音改变了林岑和许望的关系。",
            active_flag=1,
            runtime_eligible=1,
            runtime_eligibility_basis="direct_read",
        )
    )
    session.flush()
    session.get(ChapterState, "DESK100").last_final_memory_row_id = "chapter_memory_final_DESK100_v1"
    session.add(
        AuthorDraft(
            draft_id="author_draft_scene_DESK100_SC01",
            object_type="scene",
            object_id="DESK100_SC01",
            source_text_ref="final_scene:final_scene_DESK100_SC01_v1",
            content="作者稿：林岑把录音塞进袖口，许望问她为什么先关门。",
            revision_no=2,
            status="current",
        )
    )
    session.add(
        WriterEvaluation(
            evaluation_id="writer_deep_eval_DESK100_SC01",
            object_type="scene",
            object_id="DESK100_SC01",
            chapter_id="DESK100",
            scene_id="DESK100_SC01",
            rubric_id="literary_revision_v1",
            source_text_ref="author_draft:author_draft_scene_DESK100_SC01",
            lens="aggregate",
            overall_score=0.61,
            scores_json={"choice_pressure": 0.52, "dialogue_subtext": 0.67},
            findings_json=[
                {
                    "lens": "character",
                    "dimension": "choice_pressure",
                    "severity": "revision",
                    "issue": "选择有方向，但代价还没有落到行动上。",
                    "recommendation": "让她失去一个具体筹码。",
                    "evidence_excerpt": "把录音塞进袖口",
                    "why_it_matters": "读者需要看见她付出了什么。",
                }
            ],
            revision_brief_json=[{"dimension": "choice_pressure", "action": "补一个可见代价", "priority": "high"}],
            requires_human_review=0,
            status="completed",
        )
    )
    session.add(
        PassagePatchCandidate(
            patch_id="patch_DESK100_SC01_choice",
            object_type="scene",
            object_id="DESK100_SC01",
            chapter_id="DESK100",
            scene_id="DESK100_SC01",
            source_text_ref="author_draft:author_draft_scene_DESK100_SC01",
            target_text_ref="author_draft:author_draft_scene_DESK100_SC01",
            source_draft_id="author_draft_scene_DESK100_SC01",
            source_excerpt="许望问她为什么先关门。",
            issue_dimension="dialogue_subtext",
            replacement_options_json=[
                {"option_id": "subtle", "label": "更含蓄", "replacement_text": "许望只看着门缝，没有再问。"},
                {"option_id": "sharp", "label": "更锋利", "replacement_text": "许望说：你怕录音，还是怕我听见？"},
            ],
            status="candidate",
        )
    )
    for index, card_type in enumerate(
        ["character_arc_gap", "foreshadow_debt", "promise_without_payoff", "information_congestion"]
    ):
        session.add(
            LongformDiagnosticCard(
                card_id=f"lf_DESK100_{index}",
                card_type=card_type,
                severity="critical" if index == 0 else "major",
                object_type="scene" if index != 2 else "chapter",
                object_id="DESK100_SC01" if index != 2 else "DESK100",
                chapter_id="DESK100",
                scene_id="DESK100_SC01" if index != 2 else None,
                source_refs_json=["scene_card:DESK100_SC01"],
                evidence_json={"issue": card_type},
                recommendation_json={"summary": f"处理 {card_type}"},
                source_snapshot_hash=f"hash_{index}",
                status="open",
            )
        )
    session.add(
        AuthorPreferenceProfile(
            profile_id="author_pref_global_global",
            scope_type="global",
            scope_ref_id="global",
            status="draft",
            runtime_eligible=0,
            summary_json={"preferred_moves": ["更含蓄"], "rejected_ai_traces": ["解释性对白"]},
            source_patch_ids_json=["patch_DESK100_SC01_choice"],
        )
    )
    session.commit()


def test_author_desk_snapshot_aggregates_author_runtime_candidates_and_top_longform_pressure(client, session) -> None:
    _seed_author_desk_target(session)

    response = client.get("/api/v1/author-desk/scene/DESK100_SC01/snapshot")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["target"] == {"object_type": "scene", "object_id": "DESK100_SC01", "chapter_id": "DESK100", "scene_id": "DESK100_SC01"}
    assert data["author_draft"]["draft_id"] == "author_draft_scene_DESK100_SC01"
    assert data["author_draft"]["content"].startswith("作者稿")
    assert data["runtime_text"]["source_ref"] == "final_scene:final_scene_DESK100_SC01_v1"
    assert data["runtime_text"]["content"].startswith("运行终稿")
    assert data["aggregate_text"]["source_ref"] == "chapter_memory:chapter_memory_final_DESK100_v1"
    assert data["deep_review_summary"]["overall_score"] == 0.61
    assert data["deep_review_summary"]["top_findings"][0]["dimension"] == "choice_pressure"
    assert data["open_candidates"][0]["patch_id"] == "patch_DESK100_SC01_choice"
    assert data["open_candidates"][0]["replacement_options"][0]["label"] == "更含蓄"
    assert [item["card_type"] for item in data["longform_pressure"]] == [
        "character_arc_gap",
        "foreshadow_debt",
        "promise_without_payoff",
    ]
    assert data["author_preference_summary"]["preferred_moves"] == ["更含蓄"]


def test_author_desk_snapshot_can_read_chapter_level_author_draft_and_limits_pressure_to_three(client, session) -> None:
    _seed_author_desk_target(session)
    session.add(
        AuthorDraft(
            draft_id="author_draft_chapter_DESK100",
            object_type="chapter",
            object_id="DESK100",
            source_text_ref="chapter_memory:chapter_memory_final_DESK100_v1",
            content="章稿：林岑必须决定真相公开的次序。",
            revision_no=1,
            status="current",
        )
    )
    session.commit()

    response = client.get("/api/v1/author-desk/chapter/DESK100/snapshot")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["target"]["object_type"] == "chapter"
    assert data["target"]["chapter_id"] == "DESK100"
    assert data["author_draft"]["draft_id"] == "author_draft_chapter_DESK100"
    assert data["aggregate_text"]["content"].startswith("最终聚合稿")
    assert len(data["longform_pressure"]) == 3


def test_author_desk_snapshot_exposes_work_profile_judgment_layers_and_daily_focus(client, session) -> None:
    _seed_author_desk_target(session)
    session.add(
        WorkProfile(
            profile_id="work_profile_DESK100",
            scope_type="chapter",
            scope_ref_id="DESK100",
            profile_key="quiet_literary",
            display_name="文学慢热",
            description="允许低情节推进，强调余韵和人物内在压力。",
            profile_json={
                "ending_drive_policy": "soft",
                "choice_pressure_policy": "suggest",
                "diagnosis_tone": "editorial",
            },
            created_by="test",
        )
    )
    evaluation = session.get(WriterEvaluation, "writer_deep_eval_DESK100_SC01")
    evaluation.findings_json = [
        {
            "dimension": "continuity",
            "severity": "blocking",
            "issue": "人物称谓和前文冲突。",
            "recommendation": "先修正事实。",
        },
        {
            "dimension": "choice_pressure",
            "severity": "revision",
            "issue": "选择代价偏轻。",
            "recommendation": "补一个可见代价。",
        },
        {
            "dimension": "ending_drive",
            "severity": "profile_mismatch",
            "issue": "结尾没有强钩子。",
            "recommendation": "在文学慢热档案下仅提示，不阻断。",
        },
        {
            "dimension": "image_necessity",
            "severity": "taste",
            "issue": "意象略满。",
            "recommendation": "作者可按口味保留。",
        },
    ]
    session.commit()

    response = client.get("/api/v1/author-desk/scene/DESK100_SC01/snapshot")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["work_profile"]["profile_key"] == "quiet_literary"
    assert data["work_profile"]["display_name"] == "文学慢热"
    layers = data["deep_review_summary"]["judgment_layers"]
    assert [item["dimension"] for item in layers["blocking"]] == ["continuity"]
    assert [item["dimension"] for item in layers["revision"]] == ["choice_pressure"]
    assert [item["dimension"] for item in layers["profile_mismatch"]] == ["ending_drive"]
    assert [item["dimension"] for item in layers["taste"]] == ["image_necessity"]
    assert data["deep_review_summary"]["non_blocking_count"] == 3
    assert data["daily_focus"][0]["source"] == "deep_review"
    assert data["daily_focus"][0]["severity"] == "blocking"
    assert data["daily_focus"][0]["target_view"] == "deepdesk"
    assert len(data["daily_focus"]) <= 5
