from __future__ import annotations

from novel_system.db.models import (
    AuthorDraft,
    AuthorDraftEvent,
    AuthorDraftProposal,
    ChapterGoal,
    FinalScene,
    LongformDiagnosticCard,
    SceneCard,
    SceneRunState,
    WriterEvaluation,
)


def _create_chapter(session, chapter_id: str) -> None:
    session.add(
        ChapterGoal(
            chapter_id=chapter_id,
            planned_scene_count=1,
            chapter_goal="林岑必须决定是否公开录音。",
            main_plot_push="让证据浮出水面。",
            emotional_target="从冷静旁观转为承担风险。",
            ending_effect="留下下一场追问。",
        )
    )
    session.commit()


def _create_scene(session, scene_id: str, chapter_id: str) -> None:
    session.add(
        SceneCard(
            scene_id=scene_id,
            chapter_id=chapter_id,
            scene_seq=1,
            pov_character_id="CHAR_LINCEN",
            onstage_chars_json=["CHAR_LINCEN", "CHAR_XUWANG"],
            location="旧监听站",
            scene_goal="林岑在旧监听站确认录音中藏着幸存者编号。",
            beats_json=["修复磁带", "听见编号", "决定是否公开"],
            must_include_text="三声盐钟",
            forbidden_text="不要解释全部前史",
            exit_change="她决定暂时保护幸存者。",
            hook="无灯船坞被提到。",
            writer_brief_json={
                "character_desire": "确认失踪案真相。",
                "obstacle": "公开证据会暴露幸存者。",
                "stakes": "她可能被指控隐瞒真相。",
                "reader_question": "她会把证据交给谁？",
            },
            target_length_band="medium",
            scene_type="revelation",
            is_chapter_last=1,
        )
    )
    session.add(
        SceneRunState(
            scene_id=scene_id,
            scene_status="ready",
        )
    )
    session.commit()


def _finalize_scene(session, scene_id: str, chapter_id: str, content: str) -> str:
    row_id = f"final_scene_{scene_id}_v1"
    state = session.get(SceneRunState, scene_id)
    state.scene_status = "archived"
    state.current_final_scene_row_id = row_id
    session.add(
        FinalScene(
            row_id=row_id,
            scene_id=scene_id,
            chapter_id=chapter_id,
            content=content,
            status="approved",
            source_bundle_id=f"bundle_{scene_id}_v1",
            source_bundle_hash=f"hash_{scene_id}",
        )
    )
    session.commit()
    return row_id


def _ensure_scene_fixture(session) -> tuple[str, str]:
    chapter_id = "WR100"
    scene_id = "WR100_SC01"
    _create_chapter(session, chapter_id)
    _create_scene(session, scene_id, chapter_id)
    _finalize_scene(session, scene_id, chapter_id, "她解释了全部前史。门外无人说话。")
    return chapter_id, scene_id


def test_writer_room_returns_text_first_payload_with_navigation_diagnosis_candidates_and_pressure(client, session) -> None:
    chapter_id, scene_id = _ensure_scene_fixture(session)
    draft = client.post(f"/api/v1/author-drafts/scene/{scene_id}/ensure").json()["data"]["draft"]
    session.add(
        WriterEvaluation(
            evaluation_id="writer_eval_wr100",
            object_type="scene",
            object_id=scene_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            rubric_id="literary_revision_v1",
            source_text_ref=f"author_draft:{draft['draft_id']}",
            overall_score=0.61,
            scores_json={"choice_pressure": 0.4},
            findings_json=[
                {
                    "dimension": "choice_pressure",
                    "severity": "revision",
                    "issue": "选择代价还不够具体。",
                    "recommendation": "让她用隐瞒换取幸存者安全。",
                }
            ],
            revision_brief_json=[{"action": "补足可见代价"}],
        )
    )
    session.add(
        AuthorDraftProposal(
            proposal_id="proposal_wr100_local",
            draft_id=draft["draft_id"],
            object_type="scene",
            object_id=scene_id,
            proposal_type="passage_candidate",
            proposal_source="writer_room",
            content="她没有解释，只把证据袋推到桌沿。门外无人说话。",
            replacement_text="她没有解释，只把证据袋推到桌沿。",
            proposal_kind="local_patch",
            target_range_json={"unit": "text", "source_excerpt": "她解释了全部前史。"},
            before_text_hash="outdated",
            source_evaluation_id="writer_eval_wr100",
        )
    )
    session.add(
        LongformDiagnosticCard(
            card_id="lf_wr100_arc",
            card_type="character_arc_gap",
            severity="major",
            status="open",
            object_type="scene",
            object_id=scene_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            source_refs_json=[f"author_draft:{draft['draft_id']}"],
            evidence_json={"issue": "人物承担风险不够可见。"},
            recommendation_json={"summary": "让她付出一个眼前代价。"},
            source_snapshot_hash="hash_wr100_lf",
        )
    )
    session.commit()

    response = client.get(f"/api/v1/writer-room/scene/{scene_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["target"]["object_type"] == "scene"
    assert data["draft"]["draft_id"] == draft["draft_id"]
    assert data["primary_text"]["source"] == "author_draft"
    assert data["primary_text"]["content"] == "她解释了全部前史。门外无人说话。"
    assert data["scene_card"]["scene_id"] == scene_id
    assert data["navigation"]["chapters"][0]["chapter_id"] == chapter_id
    assert data["navigation"]["scenes"][0]["scene_id"] == scene_id
    assert data["diagnosis"]["top_issue"]["dimension"] == "choice_pressure"
    assert data["diagnosis"]["score_visible"] is False
    assert data["proposals"][0]["proposal_id"] == "proposal_wr100_local"
    assert data["proposals"][0]["proposal_kind"] == "local_patch"
    assert data["context_pressure"][0]["card_id"] == "lf_wr100_arc"
    assert data["next_actions"][0]["action"] == "write"
    assert "bundle" not in data
    assert "hash" not in data["primary_text"]


def test_writer_room_v2_exposes_author_priority_cards_without_advanced_noise(client, session) -> None:
    chapter_id, scene_id = _ensure_scene_fixture(session)
    draft = client.post(f"/api/v1/author-drafts/scene/{scene_id}/ensure").json()["data"]["draft"]
    session.add(
        WriterEvaluation(
            evaluation_id="writer_eval_wr100_v2",
            object_type="scene",
            object_id=scene_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            rubric_id="literary_revision_v1",
            source_text_ref=f"author_draft:{draft['draft_id']}",
            lens="aggregate",
            overall_score=0.51,
            scores_json={"choice_pressure": 0.42, "dialogue_subtext": 0.58},
            findings_json=[
                {
                    "lens": "character",
                    "dimension": "choice_pressure",
                    "severity": "blocking",
                    "issue": "她没有被逼到必须付出代价的位置。",
                    "recommendation": "让她公开一半证据，同时失去幸存者的信任。",
                    "evidence_excerpt": "她解释了全部前史。",
                    "why_it_matters": "读者需要看见选择造成伤害。",
                },
                {
                    "lens": "prose",
                    "dimension": "dialogue_subtext",
                    "severity": "taste",
                    "issue": "对白可以更短。",
                    "recommendation": "保留作者现在的克制也可以成立。",
                },
            ],
            revision_brief_json=[
                {"dimension": "choice_pressure", "action": "补一个不可撤回的公开动作", "priority": "high"},
                {"dimension": "dialogue_subtext", "action": "压短解释性对白", "priority": "medium"},
            ],
            requires_human_review=1,
            status="completed",
        )
    )
    session.add(
        AuthorDraftProposal(
            proposal_id="proposal_wr100_dialogue",
            draft_id=draft["draft_id"],
            object_type="scene",
            object_id=scene_id,
            proposal_type="dialogue_pass",
            proposal_source="writer_room",
            content="【对白深改】许望问：你怕真相，还是怕我知道？",
            proposal_kind="dialogue_pass",
            before_text_hash="outdated",
            source_evaluation_id="writer_eval_wr100_v2",
            rationale="把解释改成关系压力。",
        )
    )
    for index, (card_type, severity) in enumerate(
        [
            ("information_congestion", "minor"),
            ("promise_without_payoff", "critical"),
            ("foreshadow_debt", "major"),
            ("character_arc_gap", "critical"),
        ]
    ):
        session.add(
            LongformDiagnosticCard(
                card_id=f"lf_wr100_v2_{index}",
                card_type=card_type,
                severity=severity,
                status="open",
                object_type="chapter" if card_type == "promise_without_payoff" else "scene",
                object_id=chapter_id if card_type == "promise_without_payoff" else scene_id,
                chapter_id=chapter_id,
                scene_id=None if card_type == "promise_without_payoff" else scene_id,
                source_refs_json=[f"author_draft:{draft['draft_id']}"],
                evidence_json={"issue": f"{card_type} evidence"},
                recommendation_json={"summary": f"处理 {card_type}"},
                source_snapshot_hash=f"hash_wr100_v2_{index}",
            )
        )
    session.commit()

    response = client.get(f"/api/v1/writer-room/scene/{scene_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["top_issue"]["dimension"] == "choice_pressure"
    assert data["top_issue"]["display_priority"] == "先改这个"
    assert data["keep_advice"].startswith("这属于审美取舍")
    assert data["scene_form"] == "revelation"
    assert data["diagnosis"]["author_visible_summary"]["label"] == "需人工判断"
    assert data["diagnosis"]["advanced_evidence"]["overall_score"] == 0.51
    assert data["diagnosis"]["advanced_evidence"]["scores"]["choice_pressure"] == 0.42
    assert [card["card_type"] for card in data["longform_cards"]] == [
        "promise_without_payoff",
        "character_arc_gap",
        "foreshadow_debt",
    ]
    assert all("source_snapshot_hash" not in card for card in data["longform_cards"])
    assert data["proposal_cards"][0]["proposal_kind"] == "dialogue_pass"
    assert data["proposal_cards"][0]["display_kind"] == "对白深改"
    assert data["next_actions"][0]["action"] == "write"


def test_author_draft_diff_and_apply_proposal_use_draft_scope_and_conflict_hash(client, session) -> None:
    _chapter_id, scene_id = _ensure_scene_fixture(session)
    draft = client.post(f"/api/v1/author-drafts/scene/{scene_id}/ensure").json()["data"]["draft"]

    proposal_response = client.post(
        f"/api/v1/author-drafts/{draft['draft_id']}/proposals/generate",
        json={
            "proposal_type": "passage_candidate",
            "proposal_kind": "local_patch",
            "target_range": {"unit": "text", "source_excerpt": "她解释了全部前史。"},
            "replacement_text": "她没有解释，只把证据袋推到桌沿。",
            "source_evaluation_id": "writer_eval_missing_ok",
        },
    )
    assert proposal_response.status_code == 200
    proposal = proposal_response.json()["data"]["proposal"]

    diff_response = client.get(
        f"/api/v1/author-drafts/{draft['draft_id']}/proposals/{proposal['proposal_id']}/diff"
    )

    assert diff_response.status_code == 200
    diff = diff_response.json()["data"]
    assert diff["draft_id"] == draft["draft_id"]
    assert diff["proposal_id"] == proposal["proposal_id"]
    assert diff["merge_status"] == "clean"
    assert diff["before_text"] == "她解释了全部前史。门外无人说话。"
    assert diff["after_text"] == "她没有解释，只把证据袋推到桌沿。门外无人说话。"
    assert diff["source_evaluation_id"] == "writer_eval_missing_ok"

    stale_save = client.patch(
        f"/api/v1/author-drafts/{draft['draft_id']}",
        json={"content": "她已经手工改过这一段。", "base_revision_no": draft["revision_no"]},
    )
    assert stale_save.status_code == 200

    conflict_response = client.post(
        f"/api/v1/author-drafts/{draft['draft_id']}/apply-proposal",
        json={"proposal_id": proposal["proposal_id"], "apply_mode": "local_patch"},
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json()["error"]["code"] == "AUTHOR_DRAFT_PROPOSAL_CONFLICT"

    fresh = client.post(
        f"/api/v1/author-drafts/{draft['draft_id']}/proposals/generate",
        json={
            "proposal_type": "passage_candidate",
            "proposal_kind": "append",
            "replacement_text": "她把第二份录音交给许望保管。",
        },
    ).json()["data"]["proposal"]

    apply_response = client.post(
        f"/api/v1/author-drafts/{draft['draft_id']}/apply-proposal",
        json={"proposal_id": fresh["proposal_id"], "apply_mode": "append", "note": "作为下一拍保留。"},
    )

    assert apply_response.status_code == 200
    applied = apply_response.json()["data"]
    assert applied["draft"]["revision_no"] == 3
    assert applied["draft"]["content"].endswith("她把第二份录音交给许望保管。")
    assert applied["proposal"]["status"] == "accepted"
    assert applied["proposal"]["merge_status"] == "applied"
    session.expire_all()
    events = session.query(AuthorDraftEvent).filter_by(draft_id=draft["draft_id"]).order_by(AuthorDraftEvent.created_at.asc()).all()
    assert [event.event_type for event in events] == ["created", "edited", "proposal_applied"]
    assert session.get(AuthorDraft, draft["draft_id"]).content.endswith("她把第二份录音交给许望保管。")


def test_author_draft_generate_set_accepts_mode_and_creates_three_separate_writer_proposals(client, session) -> None:
    _chapter_id, scene_id = _ensure_scene_fixture(session)
    draft = client.post(f"/api/v1/author-drafts/scene/{scene_id}/ensure").json()["data"]["draft"]

    response = client.post(
        f"/api/v1/author-drafts/{draft['draft_id']}/proposals/generate-set",
        json={
            "mode": "near_final",
            "instruction": "保留盐钟意象，但去掉解释性对白。",
            "target_range": {"unit": "text", "source_excerpt": "她解释了全部前史。"},
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    proposals = payload["proposals"]
    assert payload["mode"] == "near_final"
    assert [proposal["proposal_kind"] for proposal in proposals] == [
        "near_final_rewrite",
        "language_pass",
        "dialogue_pass",
    ]
    assert len({proposal["proposal_id"] for proposal in proposals}) == 3
    assert all(proposal["status"] == "candidate" for proposal in proposals)
    assert all(proposal["before_text_hash"] for proposal in proposals)
    assert all(proposal["target_range"]["source_excerpt"] == "她解释了全部前史。" for proposal in proposals)
    assert "保留盐钟意象" in proposals[0]["rationale"]
    assert session.get(FinalScene, f"final_scene_{scene_id}_v1").content == "她解释了全部前史。门外无人说话。"
