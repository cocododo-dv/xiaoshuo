from __future__ import annotations

from sqlalchemy.orm import Session

from novel_system.db.models import HumanReviewEvent, LlmCall, QcReport, RelationProfile, SceneRunState, VoiceProfile


def create_chapter(client, chapter_id: str = "CH910") -> None:
    response = client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": chapter_id,
            "planned_scene_count": 1,
            "chapter_goal": f"goal for {chapter_id}",
            "main_plot_push": f"push for {chapter_id}",
            "emotional_target": f"emotion for {chapter_id}",
            "ending_effect": f"ending for {chapter_id}",
        },
        headers={"X-Idempotency-Key": f"chapter-{chapter_id}"},
    )
    assert response.status_code == 200


def create_scene(
    client,
    *,
    chapter_id: str = "CH910",
    scene_id: str = "CH910_SC01",
    pov_character_id: str = "CHAR_A",
    onstage_chars_json: list[str] | None = None,
    location: str = "Old city gate",
    scene_goal: str = "Reunion tension escalates",
    beats_json: list[str] | None = None,
    must_include_text: str = "Old letter clue",
) -> None:
    response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": scene_id,
            "chapter_id": chapter_id,
            "scene_seq": 1,
            "pov_character_id": pov_character_id,
            "onstage_chars_json": ["CHAR_A", "CHAR_B"] if onstage_chars_json is None else onstage_chars_json,
            "location": location,
            "scene_goal": scene_goal,
            "beats_json": ["beat-1", "beat-2"] if beats_json is None else beats_json,
            "must_include_text": must_include_text,
            "target_length_band": "short",
            "scene_type": "reunion",
            "is_chapter_last": 0,
        },
        headers={"X-Idempotency-Key": f"scene-{scene_id}"},
    )
    assert response.status_code == 200


def seed_voice_profile(session: Session, voice_profile_id: str = "VOICE_CHAR_A") -> None:
    session.add(
        VoiceProfile(
            row_id=f"voice_profile_{voice_profile_id}_v1",
            voice_profile_id=voice_profile_id,
            version=1,
            character_id=voice_profile_id.removeprefix("VOICE_"),
            content="short clipped lines; pressure makes the tone harder",
            active_flag=1,
            source_note="test baseline",
        )
    )
    session.commit()


def seed_relation_profile(
    session: Session,
    relation_profile_id: str = "REL_CHAR_A_CHAR_B",
    *,
    left_character_id: str = "CHAR_A",
    right_character_id: str = "CHAR_B",
) -> None:
    session.add(
        RelationProfile(
            row_id=f"relation_profile_{relation_profile_id}_v1",
            relation_profile_id=relation_profile_id,
            left_character_id=left_character_id,
            right_character_id=right_character_id,
            version=1,
            content="reunion tension; B knows slightly more than A",
            active_flag=1,
            source_note="test baseline",
        )
    )
    session.commit()


def test_workbench_preflight_is_ready_when_scene_has_required_sources_and_fields(client, session: Session) -> None:
    create_chapter(client)
    create_scene(client)
    seed_voice_profile(session)
    seed_relation_profile(session)

    response = client.get("/api/v1/scenes/CH910_SC01/workbench")

    assert response.status_code == 200
    payload = response.json()["data"]
    preflight = payload["run_preflight"]
    assert preflight == {
        "can_run": True,
        "overall_status": "ready",
        "blocking_items": [],
        "warning_items": [],
        "context_items": [],
    }
    assert payload["generation_summary"] is None
    assert payload["hard_qc_summary"] is None
    assert payload["soft_qc_summary"] is None
    assert payload["rewrite_counters"] == {
        "hard_partial_rewrite_count": 0,
        "hard_full_rewrite_count": 0,
        "soft_patch_count": 0,
        "repeat_issue_key": None,
        "repeat_issue_count": 0,
    }
    assert payload["human_review_summary"] is None


def test_workbench_payload_keeps_generation_and_qc_summaries_empty_before_any_run(client, session: Session) -> None:
    create_chapter(client, "CH915")
    create_scene(client, chapter_id="CH915", scene_id="CH915_SC01")
    seed_voice_profile(session)
    seed_relation_profile(session)

    response = client.get("/api/v1/scenes/CH915_SC01/workbench")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["generation_summary"] is None
    assert data["hard_qc_summary"] is None
    assert data["soft_qc_summary"] is None
    assert data["rewrite_counters"] == {
        "hard_partial_rewrite_count": 0,
        "hard_full_rewrite_count": 0,
        "soft_patch_count": 0,
        "repeat_issue_key": None,
        "repeat_issue_count": 0,
    }
    assert data["human_review_summary"] is None


def test_workbench_preflight_blocks_when_voice_profile_is_missing(client, session: Session) -> None:
    create_chapter(client, "CH911")
    create_scene(client, chapter_id="CH911", scene_id="CH911_SC01")
    seed_relation_profile(session)

    response = client.get("/api/v1/scenes/CH911_SC01/workbench")

    assert response.status_code == 200
    preflight = response.json()["data"]["run_preflight"]
    assert preflight["can_run"] is False
    assert preflight["overall_status"] == "blocked"
    assert preflight["blocking_items"] == [
        {
            "code": "VOICE_PROFILE_MISSING",
            "title": "缺少 POV 声线档案，当前不宜运行场景",
            "detail": "请先补齐当前 POV 角色的可用声线档案，再执行完整场景运行。",
            "technical_hint": "expected active voice profile: VOICE_CHAR_A",
        }
    ]


def test_workbench_preflight_blocks_when_relation_profile_is_missing(client, session: Session) -> None:
    create_chapter(client, "CH912")
    create_scene(client, chapter_id="CH912", scene_id="CH912_SC01")
    seed_voice_profile(session)

    response = client.get("/api/v1/scenes/CH912_SC01/workbench")

    assert response.status_code == 200
    preflight = response.json()["data"]["run_preflight"]
    assert preflight["can_run"] is False
    assert preflight["overall_status"] == "blocked"
    assert preflight["blocking_items"] == [
        {
            "code": "RELATION_PROFILE_MISSING",
            "title": "缺少同场角色关系档案，当前不宜运行场景",
            "detail": "请先补齐当前同场角色组合的可用关系档案，再执行完整场景运行。",
            "technical_hint": "expected active relation profile: REL_CHAR_A_CHAR_B",
        }
    ]


def test_workbench_preflight_surfaces_authoring_warnings_without_blocking_run(client) -> None:
    create_chapter(client, "CH913")
    create_scene(
        client,
        chapter_id="CH913",
        scene_id="CH913_SC01",
        pov_character_id="",
        onstage_chars_json=[],
        location="",
        scene_goal="",
        beats_json=[],
        must_include_text="",
    )

    response = client.get("/api/v1/scenes/CH913_SC01/workbench")

    assert response.status_code == 200
    preflight = response.json()["data"]["run_preflight"]
    assert preflight["can_run"] is True
    assert preflight["overall_status"] == "warning"
    assert preflight["blocking_items"] == []
    assert [item["code"] for item in preflight["warning_items"]] == [
        "SCENE_GOAL_MISSING",
        "SCENE_LOCATION_MISSING",
        "SCENE_POV_MISSING",
        "SCENE_ONSTAGE_CHARACTERS_MISSING",
        "SCENE_BEATS_MISSING",
    ]


def test_workbench_preflight_keeps_manual_hold_and_backfill_as_context_only(client, session: Session) -> None:
    create_chapter(client, "CH914")
    create_scene(
        client,
        chapter_id="CH914",
        scene_id="CH914_SC01",
        must_include_text='{{backfill id=F914 text="旧信寄件人线索"}}',
    )
    seed_voice_profile(session)
    seed_relation_profile(session)

    hold_response = client.post(
        "/api/v1/chapters/CH914/runtime/manual-hold",
        json={"reason": "Wait for chapter-level operator review"},
        headers={"X-Idempotency-Key": "chapter-hold-CH914"},
    )
    assert hold_response.status_code == 200

    response = client.get("/api/v1/scenes/CH914_SC01/workbench")

    assert response.status_code == 200
    preflight = response.json()["data"]["run_preflight"]
    assert preflight["can_run"] is True
    assert preflight["overall_status"] == "warning"
    assert preflight["blocking_items"] == []
    assert preflight["warning_items"] == []
    assert preflight["context_items"] == [
        {
            "code": "CHAPTER_MANUAL_HOLD_ACTIVE",
            "title": "本章已设置人工挂起",
            "detail": "这不会阻止当前场景运行，但会继续阻止章节级 final aggregate。",
            "technical_hint": "manual hold reason: Wait for chapter-level operator review",
        },
        {
            "code": "CHAPTER_BACKFILL_PENDING",
            "title": "本章仍有待处理的 staged backfill",
            "detail": "这不会阻止当前场景运行，但会继续阻止章节级 final aggregate。",
            "technical_hint": "pending staged backfill count: 1",
        },
    ]


def test_workbench_does_not_resurrect_stale_human_review_event_when_current_pointer_is_cleared(
    client,
    session: Session,
) -> None:
    create_chapter(client, "CH915")
    create_scene(client, chapter_id="CH915", scene_id="CH915_SC01")
    seed_voice_profile(session)
    seed_relation_profile(session)

    state = session.get(SceneRunState, "CH915_SC01")
    state.current_human_review_event_id = None
    session.add(
        HumanReviewEvent(
            event_id="human_review_stale_CH915_SC01",
            scene_id="CH915_SC01",
            chapter_id="CH915",
            object_ref="scene_draft:draft_style_old_CH915_SC01",
            event_source="scene_generation",
            priority="high",
            status="open",
            details_json={
                "trigger_reason": "soft_qc_patch_cycle_limit",
                "failure_reason": "stale blocker from a previous run",
                "recommended_action": "human_review_required",
                "linked_target_ref": "scene_draft:draft_style_old_CH915_SC01",
            },
            created_at="2026-04-15T00:00:00+00:00",
        )
    )
    session.commit()

    response = client.get("/api/v1/scenes/CH915_SC01/workbench")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["human_review_summary"] is None


def test_workbench_soft_qc_summary_only_uses_reports_from_the_active_run(client, session: Session) -> None:
    create_chapter(client, "CH916")
    create_scene(client, chapter_id="CH916", scene_id="CH916_SC01")
    seed_voice_profile(session)
    seed_relation_profile(session)

    state = session.get(SceneRunState, "CH916_SC01")
    state.current_bundle_id = "bundle_current_CH916_SC01"
    state.current_bundle_hash = "hash_current_CH916_SC01"
    state.current_qc_report_id = "qc_report_current_hard_CH916_SC01"
    session.add_all(
        [
            QcReport(
                qc_report_id="qc_report_old_soft_CH916_SC01",
                scene_id="CH916_SC01",
                chapter_id="CH916",
                qc_type="soft_qc",
                source_draft_row_id="draft_style_old_CH916_SC01",
                source_bundle_id="bundle_previous_CH916_SC01",
                resolution_code="soft_pass",
                pass_flag=1,
                next_action="pass",
                issues_json=[],
                rewrite_brief_json=[],
                created_at="2026-04-15T00:20:00+00:00",
            ),
            QcReport(
                qc_report_id="qc_report_current_hard_CH916_SC01",
                scene_id="CH916_SC01",
                chapter_id="CH916",
                qc_type="hard_qc",
                source_draft_row_id="draft_neutral_current_CH916_SC01",
                source_bundle_id="bundle_current_CH916_SC01",
                resolution_code="hard_pass",
                pass_flag=1,
                next_action="pass",
                issues_json=[],
                rewrite_brief_json=[],
                created_at="2026-04-15T00:10:00+00:00",
            ),
        ]
    )
    session.commit()

    response = client.get("/api/v1/scenes/CH916_SC01/workbench")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["hard_qc_summary"]["qc_report_id"] == "qc_report_current_hard_CH916_SC01"
    assert payload["soft_qc_summary"] is None


def test_workbench_generation_summary_stays_empty_when_current_run_has_no_generation_pointer(
    client,
    session: Session,
) -> None:
    create_chapter(client, "CH917")
    create_scene(client, chapter_id="CH917", scene_id="CH917_SC01")
    seed_voice_profile(session)
    seed_relation_profile(session)

    session.add(
        LlmCall(
            llm_call_id="llm_call_stale_CH917_SC01",
            provider="offline_deterministic",
            model="gpt-4.1-mini",
            prompt_hash="prompt_hash_stale_CH917_SC01",
            step="style_draft",
            scene_id="CH917_SC01",
            chapter_id="CH917",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=12,
            finish_reason="offline_fallback",
            error_code=None,
            created_at="2026-04-15T00:30:00+00:00",
        )
    )
    session.commit()

    response = client.get("/api/v1/scenes/CH917_SC01/workbench")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["generation_summary"] is None
