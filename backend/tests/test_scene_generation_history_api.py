from __future__ import annotations

from novel_system.db.models import AttemptTracker, FinalScene, HumanReviewEvent, LlmCall, QcReport, SceneDraft


def _create_chapter(client, chapter_id: str = "CH920") -> None:
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


def _create_scene(client, *, chapter_id: str = "CH920", scene_id: str = "CH920_SC01") -> None:
    response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": scene_id,
            "chapter_id": chapter_id,
            "scene_seq": 1,
            "pov_character_id": "CHAR_A",
            "onstage_chars_json": ["CHAR_A", "CHAR_B"],
            "location": "East gate",
            "scene_goal": "Trace the generation history API",
            "beats_json": ["beat-1", "beat-2"],
            "must_include_text": "red envelope clue",
            "target_length_band": "short",
            "scene_type": "reunion",
            "is_chapter_last": 0,
        },
        headers={"X-Idempotency-Key": f"scene-{scene_id}"},
    )
    assert response.status_code == 200


def test_scene_generation_history_returns_attempt_timeline_with_resolved_references_and_keeps_attempts_compatibility(
    client,
    session,
) -> None:
    _create_chapter(client)
    _create_scene(client)

    session.add_all(
        [
            LlmCall(
                llm_call_id="llm_call_neutral_CH920_SC01",
                provider="fake-provider",
                model="fake-neutral-model",
                prompt_hash="prompt_hash_neutral_CH920_SC01",
                step="neutral_draft",
                scene_id="CH920_SC01",
                chapter_id="CH920",
                request_payload_summary={"messages": 2},
                response_payload_summary={"request_id": "resp_neutral_001"},
                prompt_tokens=101,
                completion_tokens=29,
                total_tokens=130,
                latency_ms=850,
                finish_reason="stop",
                error_code=None,
                created_at="2026-04-15T00:00:01+00:00",
            ),
            LlmCall(
                llm_call_id="llm_call_style_patch_CH920_SC01",
                provider="fake-provider",
                model="fake-patch-model",
                prompt_hash="prompt_hash_patch_CH920_SC01",
                step="soft_patch",
                scene_id="CH920_SC01",
                chapter_id="CH920",
                request_payload_summary={"messages": 2, "source_draft_row_id": "draft_style_CH920_SC01"},
                response_payload_summary={"request_id": "resp_patch_001"},
                prompt_tokens=121,
                completion_tokens=31,
                total_tokens=152,
                latency_ms=910,
                finish_reason="stop",
                error_code=None,
                created_at="2026-04-15T00:00:05+00:00",
            ),
            SceneDraft(
                row_id="draft_neutral_CH920_SC01",
                scene_id="CH920_SC01",
                chapter_id="CH920",
                stage="neutral_draft",
                content="neutral draft text",
                source_bundle_id="bundle_CH920_run_01",
                source_bundle_hash="bundle_hash_CH920_run_01",
                generation_llm_call_id="llm_call_neutral_CH920_SC01",
                created_at="2026-04-15T00:00:02+00:00",
            ),
            SceneDraft(
                row_id="draft_style_CH920_SC01",
                scene_id="CH920_SC01",
                chapter_id="CH920",
                stage="style_draft",
                content="style draft text",
                source_bundle_id="bundle_CH920_run_02",
                source_bundle_hash="bundle_hash_CH920_run_02",
                generation_llm_call_id=None,
                created_at="2026-04-15T00:00:03+00:00",
            ),
            SceneDraft(
                row_id="draft_style_patch_CH920_SC01",
                scene_id="CH920_SC01",
                chapter_id="CH920",
                stage="style_patch",
                content="patched draft text",
                source_bundle_id="bundle_CH920_run_02",
                source_bundle_hash="bundle_hash_CH920_run_02",
                generation_llm_call_id="llm_call_style_patch_CH920_SC01",
                created_at="2026-04-15T00:00:06+00:00",
            ),
            QcReport(
                qc_report_id="qc_report_hard_CH920_SC01",
                scene_id="CH920_SC01",
                chapter_id="CH920",
                qc_type="hard_qc",
                source_draft_row_id="draft_neutral_CH920_SC01",
                source_bundle_id="bundle_CH920_run_01",
                resolution_code="hard_block_human",
                pass_flag=0,
                next_action="human_review_required",
                issues_json=[{"issue_key": "repeat_issue", "message": "Needs human review."}],
                rewrite_brief_json=[],
                created_at="2026-04-15T00:00:03+00:00",
            ),
            QcReport(
                qc_report_id="qc_report_soft_CH920_SC01",
                scene_id="CH920_SC01",
                chapter_id="CH920",
                qc_type="soft_qc",
                source_draft_row_id="draft_style_CH920_SC01",
                source_bundle_id="bundle_CH920_run_02",
                resolution_code="soft_patch",
                pass_flag=0,
                next_action="patch",
                issues_json=[{"issue_key": "cadence_flat", "message": "Opening lacks pressure."}],
                rewrite_brief_json=[{"instruction": "Tighten cadence."}],
                created_at="2026-04-15T00:00:04+00:00",
            ),
            HumanReviewEvent(
                event_id="human_review_hard_CH920_SC01",
                scene_id="CH920_SC01",
                chapter_id="CH920",
                object_ref="scene_draft:draft_neutral_CH920_SC01",
                event_source="scene_generation",
                priority="high",
                owner="ops.duwei",
                status="needs_followup",
                allowed_actions_json=["retry", "waive"],
                result_status_map_json={"retry": "open", "waive": "resolved"},
                details_json={
                    "trigger_reason": "repeat_issue_key_limit",
                    "failure_reason": "hard_qc surfaced the same issue twice",
                    "recommended_action": "human_review_required",
                    "linked_target_ref": "scene_draft:draft_neutral_CH920_SC01",
                },
                default_action="retry",
                created_at="2026-04-15T00:00:03+00:30",
                updated_at="2026-04-15T00:00:03+00:30",
            ),
            FinalScene(
                row_id="final_scene_CH920_SC01",
                scene_id="CH920_SC01",
                chapter_id="CH920",
                content="final archived scene text",
                status="approved",
                source_bundle_id="bundle_CH920_run_02",
                source_bundle_hash="bundle_hash_CH920_run_02",
                generation_llm_call_id="llm_call_style_patch_CH920_SC01",
                created_at="2026-04-15T00:00:07+00:00",
            ),
            AttemptTracker(
                scene_id="CH920_SC01",
                chapter_id="CH920",
                step="neutral_draft",
                status="completed",
                source_bundle_id="bundle_CH920_run_01",
                details_json={"row_id": "draft_neutral_CH920_SC01"},
                created_at="2026-04-15T00:00:02+00:00",
            ),
            AttemptTracker(
                scene_id="CH920_SC01",
                chapter_id="CH920",
                step="hard_qc",
                status="human_review_required",
                source_bundle_id="bundle_CH920_run_01",
                details_json={
                    "qc_report_id": "qc_report_hard_CH920_SC01",
                    "resolution_code": "hard_block_human",
                    "next_action": "human_review_required",
                    "human_review_event_id": "human_review_hard_CH920_SC01",
                },
                created_at="2026-04-15T00:00:04+00:00",
            ),
            AttemptTracker(
                scene_id="CH920_SC01",
                chapter_id="CH920",
                step="soft_patch",
                status="completed",
                source_bundle_id="bundle_CH920_run_02",
                details_json={
                    "row_id": "draft_style_patch_CH920_SC01",
                    "llm_call_id": "llm_call_style_patch_CH920_SC01",
                    "source_draft_row_id": "draft_style_CH920_SC01",
                    "source_style_draft_row_id": "draft_style_CH920_SC01",
                    "source_qc_report_id": "qc_report_soft_CH920_SC01",
                    "rewrite_brief": ["Tighten cadence."],
                },
                created_at="2026-04-15T00:00:06+00:00",
            ),
            AttemptTracker(
                scene_id="CH920_SC01",
                chapter_id="CH920",
                step="finalize",
                status="completed",
                source_bundle_id="bundle_CH920_run_02",
                details_json={
                    "source_style_draft_row_id": "draft_style_patch_CH920_SC01",
                    "source_qc_report_id": "qc_report_soft_CH920_SC01",
                    "final_generation_llm_call_id": "llm_call_style_patch_CH920_SC01",
                },
                created_at="2026-04-15T00:00:07+00:00",
            ),
            AttemptTracker(
                scene_id="CH920_SC01",
                chapter_id="CH920",
                step="archive",
                status="completed",
                source_bundle_id="bundle_CH920_run_02",
                details_json={
                    "final_scene_row_id": "final_scene_CH920_SC01",
                    "qc_report_id": "qc_report_soft_CH920_SC01",
                },
                created_at="2026-04-15T00:00:08+00:00",
            ),
        ]
    )
    session.commit()

    response = client.get("/api/v1/scenes/CH920_SC01/generation-history")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["scene_id"] == "CH920_SC01"
    assert [item["attempt"]["step"] for item in payload["items"]] == [
        "neutral_draft",
        "hard_qc",
        "soft_patch",
        "finalize",
        "archive",
    ]
    assert [item["attempt_order"] for item in payload["items"]] == [1, 2, 3, 4, 5]

    neutral_item = payload["items"][0]
    assert neutral_item["reference_ids"] == {
        "source_bundle_id": "bundle_CH920_run_01",
        "row_id": "draft_neutral_CH920_SC01",
        "source_draft_row_id": None,
        "source_style_draft_row_id": None,
        "final_scene_row_id": None,
        "llm_call_id": "llm_call_neutral_CH920_SC01",
        "qc_report_id": None,
        "source_qc_report_id": None,
        "human_review_event_id": None,
        "final_generation_llm_call_id": None,
    }
    assert neutral_item["llm_call"] == {
        "llm_call_id": "llm_call_neutral_CH920_SC01",
        "step": "neutral_draft",
        "raw_step": "neutral_draft",
        "provider": "fake-provider",
        "model": "fake-neutral-model",
        "prompt_hash": "prompt_hash_neutral_CH920_SC01",
        "request_payload_summary": {"messages": 2},
        "response_payload_summary": {"request_id": "resp_neutral_001"},
        "prompt_tokens": 101,
        "completion_tokens": 29,
        "total_tokens": 130,
        "latency_ms": 850,
        "finish_reason": "stop",
        "error_code": None,
        "created_at": "2026-04-15T00:00:01+00:00",
    }
    assert neutral_item["qc_report"] is None
    assert neutral_item["human_review_event"] is None

    hard_qc_item = payload["items"][1]
    assert hard_qc_item["reference_ids"]["qc_report_id"] == "qc_report_hard_CH920_SC01"
    assert hard_qc_item["reference_ids"]["human_review_event_id"] == "human_review_hard_CH920_SC01"
    assert hard_qc_item["llm_call"] is None
    assert hard_qc_item["qc_report"] == {
        "qc_report_id": "qc_report_hard_CH920_SC01",
        "qc_type": "hard_qc",
        "source_draft_row_id": "draft_neutral_CH920_SC01",
        "source_bundle_id": "bundle_CH920_run_01",
        "pass_flag": False,
        "resolution_code": "hard_block_human",
        "next_action": "human_review_required",
        "issues_json": [{"issue_key": "repeat_issue", "message": "Needs human review."}],
        "rewrite_brief_json": [],
        "issue_keys": ["repeat_issue"],
        "rewrite_brief": [],
        "created_at": "2026-04-15T00:00:03+00:00",
    }
    assert hard_qc_item["human_review_event"] == {
        "event_id": "human_review_hard_CH920_SC01",
        "status": "needs_followup",
        "event_source": "scene_generation",
        "priority": "high",
        "owner": "ops.duwei",
        "object_ref": "scene_draft:draft_neutral_CH920_SC01",
        "allowed_actions_json": ["retry", "waive"],
        "result_status_map_json": {"retry": "open", "waive": "resolved"},
        "default_action": "retry",
        "details_json": {
            "trigger_reason": "repeat_issue_key_limit",
            "failure_reason": "hard_qc surfaced the same issue twice",
            "recommended_action": "human_review_required",
            "linked_target_ref": "scene_draft:draft_neutral_CH920_SC01",
        },
        "created_at": "2026-04-15T00:00:03+00:30",
        "updated_at": "2026-04-15T00:00:03+00:30",
    }

    patch_item = payload["items"][2]
    assert patch_item["reference_ids"] == {
        "source_bundle_id": "bundle_CH920_run_02",
        "row_id": "draft_style_patch_CH920_SC01",
        "source_draft_row_id": "draft_style_CH920_SC01",
        "source_style_draft_row_id": "draft_style_CH920_SC01",
        "final_scene_row_id": None,
        "llm_call_id": "llm_call_style_patch_CH920_SC01",
        "qc_report_id": "qc_report_soft_CH920_SC01",
        "source_qc_report_id": "qc_report_soft_CH920_SC01",
        "human_review_event_id": None,
        "final_generation_llm_call_id": None,
    }
    assert patch_item["llm_call"]["raw_step"] == "soft_patch"
    assert patch_item["llm_call"]["step"] == "style_patch"
    assert patch_item["qc_report"]["qc_report_id"] == "qc_report_soft_CH920_SC01"
    assert patch_item["qc_report"]["issue_keys"] == ["cadence_flat"]
    assert patch_item["human_review_event"] is None

    finalize_item = payload["items"][3]
    assert finalize_item["reference_ids"]["llm_call_id"] == "llm_call_style_patch_CH920_SC01"
    assert finalize_item["reference_ids"]["qc_report_id"] == "qc_report_soft_CH920_SC01"
    assert finalize_item["reference_ids"]["final_generation_llm_call_id"] == "llm_call_style_patch_CH920_SC01"
    assert finalize_item["llm_call"]["llm_call_id"] == "llm_call_style_patch_CH920_SC01"
    assert finalize_item["qc_report"]["qc_report_id"] == "qc_report_soft_CH920_SC01"

    archive_item = payload["items"][4]
    assert archive_item["reference_ids"]["final_scene_row_id"] == "final_scene_CH920_SC01"
    assert archive_item["reference_ids"]["qc_report_id"] == "qc_report_soft_CH920_SC01"
    assert archive_item["llm_call"]["llm_call_id"] == "llm_call_style_patch_CH920_SC01"
    assert archive_item["qc_report"]["qc_report_id"] == "qc_report_soft_CH920_SC01"

    attempts_response = client.get("/api/v1/scenes/CH920_SC01/attempts")

    assert attempts_response.status_code == 200
    attempts_payload = attempts_response.json()["data"]
    assert [item["step"] for item in attempts_payload["items"]] == [
        "archive",
        "finalize",
        "soft_patch",
        "hard_qc",
        "neutral_draft",
    ]
    assert set(attempts_payload["items"][0].keys()) == {
        "attempt_id",
        "step",
        "status",
        "source_bundle_id",
        "details_json",
        "created_at",
    }
    assert attempts_payload["items"][0]["details_json"] == {
        "final_scene_row_id": "final_scene_CH920_SC01",
        "qc_report_id": "qc_report_soft_CH920_SC01",
    }


def test_scene_generation_history_nulls_missing_or_foreign_qc_and_review_references(client, session) -> None:
    _create_chapter(client, "CH921")
    _create_scene(client, chapter_id="CH921", scene_id="CH921_SC01")
    _create_chapter(client, "CH922")
    _create_scene(client, chapter_id="CH922", scene_id="CH922_SC01")

    session.add_all(
        [
            QcReport(
                qc_report_id="qc_report_foreign_CH922_SC01",
                scene_id="CH922_SC01",
                chapter_id="CH922",
                qc_type="hard_qc",
                source_draft_row_id="draft_foreign_CH922_SC01",
                source_bundle_id="bundle_CH922_run_01",
                resolution_code="hard_pass",
                pass_flag=1,
                next_action="pass",
                issues_json=[],
                rewrite_brief_json=[],
                created_at="2026-04-15T00:10:00+00:00",
            ),
            HumanReviewEvent(
                event_id="human_review_foreign_CH922_SC01",
                scene_id="CH922_SC01",
                chapter_id="CH922",
                object_ref="scene_draft:draft_foreign_CH922_SC01",
                event_source="scene_generation",
                priority="normal",
                owner="ops.duwei",
                status="open",
                allowed_actions_json=["retry"],
                result_status_map_json={"retry": "open"},
                details_json={"trigger_reason": "foreign_scene"},
                default_action="retry",
                created_at="2026-04-15T00:10:01+00:00",
                updated_at="2026-04-15T00:10:01+00:00",
            ),
            AttemptTracker(
                scene_id="CH921_SC01",
                chapter_id="CH921",
                step="hard_qc",
                status="failed",
                source_bundle_id="bundle_CH921_run_01",
                details_json={
                    "qc_report_id": "qc_report_missing_CH921_SC01",
                    "human_review_event_id": "human_review_missing_CH921_SC01",
                },
                created_at="2026-04-15T00:10:02+00:00",
            ),
            AttemptTracker(
                scene_id="CH921_SC01",
                chapter_id="CH921",
                step="soft_qc",
                status="human_review_required",
                source_bundle_id="bundle_CH921_run_01",
                details_json={
                    "qc_report_id": "qc_report_foreign_CH922_SC01",
                    "source_qc_report_id": "qc_report_foreign_CH922_SC01",
                    "human_review_event_id": "human_review_foreign_CH922_SC01",
                },
                created_at="2026-04-15T00:10:03+00:00",
            ),
        ]
    )
    session.commit()

    response = client.get("/api/v1/scenes/CH921_SC01/generation-history")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [item["attempt"]["step"] for item in items] == ["hard_qc", "soft_qc"]

    missing_item = items[0]
    assert missing_item["reference_ids"]["qc_report_id"] is None
    assert missing_item["reference_ids"]["source_qc_report_id"] is None
    assert missing_item["reference_ids"]["human_review_event_id"] is None
    assert missing_item["qc_report"] is None
    assert missing_item["human_review_event"] is None

    foreign_item = items[1]
    assert foreign_item["reference_ids"]["qc_report_id"] is None
    assert foreign_item["reference_ids"]["source_qc_report_id"] is None
    assert foreign_item["reference_ids"]["human_review_event_id"] is None
    assert foreign_item["qc_report"] is None
    assert foreign_item["human_review_event"] is None
