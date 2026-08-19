from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from novel_system.db.models import (
    HumanReviewEvent,
    StyleReferenceBook,
    StyleReferenceProfile,
    StyleReferenceRun,
)
from novel_system.services.style_reference.style_feedback import (
    build_candidate_selection_feedback,
    build_candidate_style_snapshot,
    summarize_profile_candidate_feedback,
    validate_candidate_selection_feedback,
    validate_candidate_style_snapshot,
)


def _candidate(
    row_id: str, content: str, *, style: float, confidence: float, selected: bool
):
    rerank = {
        "scorer_version": "style_candidate_rerank_v1",
        "applied_mode": "shadow",
        "profile_ids": ["feedback_profile"],
        "target_hash": "a" * 64,
        "runtime_contract_version": "style_reference_runtime_contract_v1",
        "runtime_contract_hash": "b" * 64,
    }
    return SimpleNamespace(
        row_id=row_id,
        content=content,
        ranking_audit={
            "row_id": row_id,
            "quality_score": 0.8,
            "style_score": style,
            "style_confidence": confidence,
            "metric_count": 18,
            "style_eligible": True,
            "rank": 0 if selected else 1,
            "selected": selected,
            "selection_reason": "quality_order",
            "rerank": rerank,
        },
    )


def test_feedback_snapshot_never_persists_prose_and_detects_tampering() -> None:
    secret_a = "不应进入反馈快照的候选正文甲。"
    secret_b = "不应进入反馈快照的候选正文乙。"
    snapshot = build_candidate_style_snapshot(
        [
            _candidate("row_a", secret_a, style=0.9, confidence=0.8, selected=False),
            _candidate("row_b", secret_b, style=0.6, confidence=0.9, selected=True),
        ]
    )

    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert secret_a not in serialized
    assert secret_b not in serialized
    assert snapshot["machine_style_leader_row_id"] == "row_a"
    assert snapshot["machine_policy_selected_row_id"] == "row_b"
    assert validate_candidate_style_snapshot(snapshot) == snapshot

    tampered = json.loads(serialized)
    tampered["candidates"][0]["style_score"] = 0.1
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_candidate_style_snapshot(tampered)


def test_only_explicit_style_reason_becomes_style_calibration_observation() -> None:
    snapshot = build_candidate_style_snapshot(
        [
            _candidate("row_a", "甲", style=0.9, confidence=0.8, selected=False),
            _candidate("row_b", "乙", style=0.6, confidence=0.9, selected=True),
        ]
    )
    details = {"style_feedback_snapshot": snapshot}

    attributed = build_candidate_selection_feedback(
        details,
        scene_id="feedback_scene",
        selected_row_id="row_b",
        preference_tags=["style_match"],
        no_clear_difference=False,
        observed_at="2026-08-19T12:00:00Z",
    )
    overall = build_candidate_selection_feedback(
        details,
        scene_id="feedback_scene",
        selected_row_id="row_b",
        preference_tags=["overall_quality"],
        no_clear_difference=False,
        observed_at="2026-08-19T12:01:00Z",
    )

    assert attributed["style_attributed"] is True
    assert attributed["agrees_with_machine_style_leader"] is False
    assert attributed["observational_calibration_eligible"] is True
    assert attributed["policy_evidence_eligible"] is False
    assert validate_candidate_selection_feedback(attributed) == attributed
    assert overall["style_attributed"] is False
    assert overall["agrees_with_machine_style_leader"] is None
    assert overall["observational_calibration_eligible"] is False
    tampered = json.loads(json.dumps(attributed, ensure_ascii=False))
    tampered["agrees_with_machine_style_leader"] = True
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_candidate_selection_feedback(tampered)


def test_profile_feedback_summary_and_route_are_aggregate_only(client, session) -> None:
    session.add(
        StyleReferenceBook(
            book_id="feedback_book",
            title="反馈参考",
            source_kind="upload",
            cloud_policy="local_only",
            text_checksum="feedback-checksum",
            status="ready",
        )
    )
    session.add(
        StyleReferenceRun(
            run_id="feedback_run",
            book_id="feedback_book",
            status="completed",
        )
    )
    session.add(
        StyleReferenceProfile(
            profile_id="feedback_profile",
            book_id="feedback_book",
            run_id="feedback_run",
            title="反馈画像",
            status="active",
            profile_json={},
        )
    )
    snapshot = build_candidate_style_snapshot(
        [
            _candidate("row_a", "甲", style=0.9, confidence=0.8, selected=False),
            _candidate("row_b", "乙", style=0.6, confidence=0.9, selected=True),
        ]
    )
    feedback = build_candidate_selection_feedback(
        {"style_feedback_snapshot": snapshot},
        scene_id="feedback_scene",
        selected_row_id="row_a",
        preference_tags=["rhythm"],
        no_clear_difference=False,
        observed_at="2026-08-19T12:00:00Z",
    )
    tampered_feedback = json.loads(json.dumps(feedback, ensure_ascii=False))
    tampered_feedback["agrees_with_machine_style_leader"] = False
    session.add(
        HumanReviewEvent(
            event_id="feedback_event",
            scene_id=None,
            chapter_id=None,
            object_ref="candidate_selection:feedback_scene",
            event_source="candidate_selection",
            status="resolved",
            details_json={
                "gate_type": "style_candidate_selection",
                "style_feedback_history": [feedback, tampered_feedback],
            },
        )
    )
    session.commit()

    summary = summarize_profile_candidate_feedback(session, "feedback_profile")
    response = client.get(
        "/api/v2/style-reference/profiles/feedback_profile/candidate-feedback"
    )

    assert summary["total_observations"] == 1
    assert summary["invalid_observations"] == 1
    assert summary["machine_style_agreements"] == 1
    assert summary["machine_style_agreement_rate"] == pytest.approx(1.0)
    assert summary["policy_evidence_eligible"] is False
    assert response.status_code == 200
    data = response.json()["data"]["candidate_feedback"]
    assert data == summary
    assert "row_a" not in json.dumps(data, ensure_ascii=False)


def test_feedback_route_rejects_unknown_profile(client) -> None:
    response = client.get(
        "/api/v2/style-reference/profiles/missing-profile/candidate-feedback"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "STYLE_REFERENCE_PROFILE_NOT_FOUND"
