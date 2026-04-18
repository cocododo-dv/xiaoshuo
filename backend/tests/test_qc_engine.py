from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from novel_system.api.routes.scenes import _serialize_generation_summary, _serialize_qc_summary
from novel_system.db.models import (
    AttemptTracker,
    ChapterGoal,
    ChapterState,
    FinalScene,
    HumanReviewEvent,
    LlmCall,
    QcReport,
    RelationProfile,
    SceneCard,
    SceneDraft,
    SceneMemory,
    SceneRunState,
    VoiceProfile,
)
from novel_system.services.human_review_manager import HumanReviewManager
from novel_system.services.llm_client import LLMRequest, LLMResponse
from novel_system.services.orchestrator import Orchestrator
from novel_system.services.qc_engine import HardQcEngine, SoftQcEngine
from novel_system.services.scene_generation import SceneGenerationService
from novel_system.services.qc_validator import QCValidationError, validate_qc_report


class FakeSceneClient:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            payload = {
                "scene_text": "Provider-generated neutral scene text.",
                "continuity_notes": ["kept the reunion tense"],
            }
            request_id = "resp_neutral_001"
            model = "fake-neutral-model"
            usage = {"input_tokens": 111, "output_tokens": 29, "total_tokens": 140}
        elif len(self.requests) == 2:
            payload = {
                "scene_text": "Provider-generated style scene text.",
                "style_notes": ["leaned harder into rhythm and inner tension"],
            }
            request_id = "resp_style_001"
            model = "fake-style-model"
            usage = {"input_tokens": 121, "output_tokens": 33, "total_tokens": 154}
        else:
            payload = {
                "scene_text": "Provider-generated patched scene text.",
                "style_notes": ["applied one controlled patch pass"],
            }
            request_id = "resp_patch_001"
            model = "fake-patch-model"
            usage = {"input_tokens": 131, "output_tokens": 37, "total_tokens": 168}

        return LLMResponse(
            request_id=request_id,
            provider="fake-provider",
            model=model,
            text=json.dumps(payload),
            structured_output=payload,
            response_format="json_object",
            raw_response={
                "id": request_id,
                "model": model,
                "usage": usage,
                "finish_reason": "stop",
            },
            usage=usage,
            finish_reason="stop",
        )


class FakeSoftQcClient:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.payloads:
            raise AssertionError("unexpected soft_qc request")
        self.requests.append(request)
        payload = self.payloads.pop(0)
        return LLMResponse(
            request_id=f"resp_soft_qc_{len(self.requests):03d}",
            provider="fake-provider",
            model="fake-soft-qc-model",
            text=json.dumps(payload),
            structured_output=payload,
            response_format="json_object",
            raw_response={
                "id": f"resp_soft_qc_{len(self.requests):03d}",
                "model": "fake-soft-qc-model",
                "usage": {"input_tokens": 60, "output_tokens": 18, "total_tokens": 78},
                "finish_reason": "stop",
            },
            usage={"input_tokens": 60, "output_tokens": 18, "total_tokens": 78},
            finish_reason="stop",
        )


class FakeQcClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            request_id="resp_hard_qc_001",
            provider="fake-provider",
            model="fake-hard-qc-model",
            text=json.dumps(self.payload),
            structured_output=self.payload,
            response_format="json_object",
            raw_response={
                "id": "resp_hard_qc_001",
                "model": "fake-hard-qc-model",
                "usage": {"input_tokens": 77, "output_tokens": 21, "total_tokens": 98},
                "finish_reason": "stop",
            },
            usage={"input_tokens": 77, "output_tokens": 21, "total_tokens": 98},
            finish_reason="stop",
        )


class FakeQcRuntimeFailureClient:
    def generate(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("qc transport timed out before a response was returned")


def _seed_scene(session) -> None:
    session.add(
        ChapterGoal(
            chapter_id="CH100",
            planned_scene_count=1,
            chapter_goal="A reunion turns dangerous.",
        )
    )
    session.add(ChapterState(chapter_id="CH100", current_phase="drafting"))
    session.add(
        SceneCard(
            scene_id="CH100_SC01",
            chapter_id="CH100",
            scene_seq=1,
            pov_character_id="CHAR_A",
            onstage_chars_json=["CHAR_A", "CHAR_B"],
            location="Clocktower Roof",
            scene_goal="Force both characters to reveal what they know.",
            beats_json=["arrival", "reveal", "standoff"],
            must_include_text="A red envelope changes hands.",
            target_length_band="short",
            scene_type="reunion",
            is_chapter_last=0,
        )
    )
    session.add(SceneRunState(scene_id="CH100_SC01", scene_status="ready"))
    session.add(
        VoiceProfile(
            row_id="voice_profile_VOICE_CHAR_A_v1",
            voice_profile_id="VOICE_CHAR_A",
            version=1,
            character_id="CHAR_A",
            content="tight internal narration",
            active_flag=1,
        )
    )
    session.add(
        RelationProfile(
            row_id="relation_profile_REL_CHAR_A_CHAR_B_v1",
            relation_profile_id="REL_CHAR_A_CHAR_B",
            left_character_id="CHAR_A",
            right_character_id="CHAR_B",
            version=1,
            content="they mistrust each other but still care",
            active_flag=1,
        )
    )
    session.commit()


def _make_orchestrator(
    session,
    *,
    hard_qc_payload: dict,
    soft_qc_payloads: list[dict] | None = None,
) -> Orchestrator:
    return Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=FakeSceneClient()),
        hard_qc_engine=HardQcEngine(session, llm_client=FakeQcClient(hard_qc_payload)),
        soft_qc_engine=SoftQcEngine(
            session,
            llm_client=FakeSoftQcClient(soft_qc_payloads or []),
        ),
    )


def _base_qc_payload(*, resolution_code: str, next_action: str, issues: list[dict] | None = None) -> dict:
    return {
        "resolution_code": resolution_code,
        "pass_flag": resolution_code == "hard_pass",
        "next_action": next_action,
        "issues": issues or [],
        "rewrite_brief": ["Repair the continuity issue before style generation."] if next_action != "pass" else [],
    }


def _base_soft_qc_payload(
    *,
    resolution_code: str,
    next_action: str,
    issues: list[dict] | None = None,
    rewrite_brief: list[str] | None = None,
    carry_forward_note: bool = False,
    note_scope: str | None = None,
    carry_note_text: str | None = None,
    style_score: float | None = None,
    style_dimensions: list[dict] | None = None,
    style_deviations: list[dict] | None = None,
) -> dict:
    payload = {
        "resolution_code": resolution_code,
        "pass_flag": resolution_code in {"soft_pass", "soft_waive"},
        "next_action": next_action,
        "issues": issues or [],
        "rewrite_brief": rewrite_brief or [],
        "carry_forward_note": carry_forward_note,
        "note_scope": note_scope,
        "carry_note_text": carry_note_text,
    }
    if style_score is not None:
        payload["style_score"] = style_score
    if style_dimensions is not None:
        payload["style_dimensions"] = style_dimensions
    if style_deviations is not None:
        payload["style_deviations"] = style_deviations
    return payload


def test_soft_qc_validator_accepts_patch_and_waive_payloads() -> None:
    patch = validate_qc_report(
        "soft_qc",
        _base_soft_qc_payload(
            resolution_code="soft_patch",
            next_action="patch",
            issues=[{"issue_key": "cadence_flat", "message": "The opening needs a stronger pulse."}],
            rewrite_brief=["Tighten the first paragraph.", "Shift the line breaks earlier."],
        ),
    )
    waive = validate_qc_report(
        "soft_qc",
        _base_soft_qc_payload(
            resolution_code="soft_waive",
            next_action="pass_with_notes",
            carry_forward_note=True,
            note_scope="chapter_memory",
            carry_note_text="Keep the envelope as a recurring tension motif.",
        ),
    )

    assert patch.resolution_code == "soft_patch"
    assert patch.next_action == "patch"
    assert patch.pass_flag is False
    assert patch.rewrite_brief == ["Tighten the first paragraph.", "Shift the line breaks earlier."]
    assert waive.resolution_code == "soft_waive"
    assert waive.next_action == "pass_with_notes"
    assert waive.pass_flag is True
    assert waive.carry_forward_note is True
    assert waive.note_scope == "chapter_memory"
    assert waive.carry_note_text == "Keep the envelope as a recurring tension motif."


def test_soft_qc_validator_accepts_style_score_contract_and_rejects_out_of_range() -> None:
    report = validate_qc_report(
        "soft_qc",
        _base_soft_qc_payload(
            resolution_code="soft_patch",
            next_action="patch",
            issues=[{"issue_key": "style_profile_drift", "message": "Dialogue ratio is too high."}],
            rewrite_brief=["Reduce dialogue and restore interior pressure."],
            style_score=0.62,
            style_dimensions=[
                {
                    "name": "rhythm",
                    "score": 0.7,
                    "evidence": "Several paragraph endings carry pressure.",
                },
                {
                    "name": "dialogue_ratio",
                    "score": 0.45,
                    "evidence": "Dialogue crowds out the requested interior distance.",
                },
            ],
            style_deviations=[
                {
                    "dimension": "dialogue_ratio",
                    "severity": "medium",
                    "patch_brief": "Cut two spoken lines and move one beat into narration.",
                }
            ],
        ),
    )

    assert report.style_score == 0.62
    assert report.style_dimensions[0].name == "rhythm"
    assert report.style_dimensions[1].score == 0.45
    assert report.style_deviations[0].patch_brief == "Cut two spoken lines and move one beat into narration."

    with pytest.raises((QCValidationError, ValidationError)):
        validate_qc_report(
            "soft_qc",
            _base_soft_qc_payload(
                resolution_code="soft_pass",
                next_action="pass",
                style_score=1.2,
                style_dimensions=[{"name": "rhythm", "score": 1.3, "evidence": "too high"}],
            ),
        )


def test_soft_qc_validator_rejects_waive_without_note() -> None:
    with pytest.raises(QCValidationError):
        validate_qc_report(
            "soft_qc",
            _base_soft_qc_payload(
                resolution_code="soft_waive",
                next_action="pass_with_notes",
                carry_forward_note=False,
            ),
        )


def test_soft_qc_engine_persists_style_score_summary_and_api_serializers(session) -> None:
    _seed_scene(session)
    state = session.get(SceneRunState, "CH100_SC01")
    session.add(
        SceneDraft(
            row_id="draft_style_CH100_SC01",
            scene_id="CH100_SC01",
            chapter_id="CH100",
            stage="style_draft",
            content="Style draft under soft QC.",
            source_bundle_id="bundle_CH100_SC01",
            source_bundle_hash="bundle_hash_CH100_SC01",
            generation_llm_call_id="llm_call_style_CH100_SC01",
        )
    )
    session.add(
        LlmCall(
            llm_call_id="llm_call_style_CH100_SC01",
            provider="fake-provider",
            model="fake-style-model",
            prompt_hash="prompt_hash_style",
            step="style_draft",
            scene_id="CH100_SC01",
            chapter_id="CH100",
            prompt_tokens=12,
            completion_tokens=34,
            total_tokens=46,
            latency_ms=78,
            finish_reason="stop",
        )
    )
    session.add(
        FinalScene(
            row_id="final_scene_CH100_SC01",
            scene_id="CH100_SC01",
            chapter_id="CH100",
            content="Final scene.",
            source_bundle_id="bundle_CH100_SC01",
            source_bundle_hash="bundle_hash_CH100_SC01",
            generation_llm_call_id="llm_call_style_CH100_SC01",
        )
    )
    state.current_bundle_id = "bundle_CH100_SC01"
    state.current_bundle_hash = "bundle_hash_CH100_SC01"
    state.current_style_draft_row_id = "draft_style_CH100_SC01"
    state.current_final_scene_row_id = "final_scene_CH100_SC01"
    session.commit()

    engine = SoftQcEngine(
        session,
        llm_client=FakeSoftQcClient(
            [
                _base_soft_qc_payload(
                    resolution_code="soft_pass",
                    next_action="pass",
                    style_score=0.84,
                    style_dimensions=[
                        {"name": "rhythm", "score": 0.9, "evidence": "Pressure lands at paragraph ends."},
                        {"name": "imagery", "score": 0.78, "evidence": "The letter image stays tactile."},
                    ],
                    style_deviations=[
                        {
                            "dimension": "paragraph_density",
                            "severity": "low",
                            "patch_brief": "Break the longest paragraph before final archive.",
                        }
                    ],
                )
            ]
        ),
    )

    decision = engine.evaluate(
        scene_id="CH100_SC01",
        bundle={
            "bundle_id": "bundle_CH100_SC01",
            "bundle_snapshot_hash": "bundle_hash_CH100_SC01",
            "snapshot": {
                "scene_id": "CH100_SC01",
                "chapter_id": "CH100",
                "inline_digests": {"scene_card": "Force both characters to reveal what they know."},
            },
        },
        source_draft_row_id="draft_style_CH100_SC01",
        source_draft_content="Style draft under soft QC.",
    )
    session.commit()

    report = session.execute(select(QcReport).where(QcReport.qc_type == "soft_qc")).scalars().one()
    style_entry = next(entry for entry in report.rewrite_brief_json if entry.get("kind") == "style_score")
    qc_summary = _serialize_qc_summary(report)
    generation_summary = _serialize_generation_summary(session, "CH100_SC01", state)

    assert decision.branch == "continue"
    assert style_entry == {
        "kind": "style_score",
        "style_score": 0.84,
        "style_dimensions": [
            {"name": "rhythm", "score": 0.9, "evidence": "Pressure lands at paragraph ends."},
            {"name": "imagery", "score": 0.78, "evidence": "The letter image stays tactile."},
        ],
        "style_deviations": [
            {
                "dimension": "paragraph_density",
                "severity": "low",
                "patch_brief": "Break the longest paragraph before final archive.",
            }
        ],
    }
    assert qc_summary["style_score"] == 0.84
    assert qc_summary["style_dimensions"][0]["name"] == "rhythm"
    assert qc_summary["style_deviations"][0]["dimension"] == "paragraph_density"
    assert generation_summary["style_score_summary"]["style_score"] == 0.84


def test_run_scene_hard_qc_pass_persists_report_and_continues(session) -> None:
    _seed_scene(session)
    orchestrator = _make_orchestrator(
        session,
        hard_qc_payload=_base_qc_payload(resolution_code="hard_pass", next_action="pass"),
        soft_qc_payloads=[_base_soft_qc_payload(resolution_code="soft_pass", next_action="pass")],
    )

    result = orchestrator.run_scene("CH100_SC01")
    session.commit()

    state = session.get(SceneRunState, "CH100_SC01")
    reports = session.execute(select(QcReport).order_by(QcReport.created_at.asc(), QcReport.qc_report_id.asc())).scalars().all()
    hard_report = next(report for report in reports if report.qc_type == "hard_qc")
    soft_report = next(report for report in reports if report.qc_type == "soft_qc")
    style_draft = session.execute(
        select(SceneDraft).where(SceneDraft.stage == "style_draft")
    ).scalars().one()
    final_scene = session.execute(select(FinalScene)).scalars().one()
    attempts = session.execute(select(AttemptTracker).order_by(AttemptTracker.attempt_id.asc())).scalars().all()

    assert result["scene_status"] == "archived"
    assert result["hard_qc"]["branch"] == "continue"
    assert result["soft_qc"]["branch"] == "continue"
    assert hard_report.qc_type == "hard_qc"
    assert hard_report.source_draft_row_id == state.current_neutral_draft_row_id
    assert hard_report.source_bundle_id == state.current_bundle_id
    assert hard_report.resolution_code == "hard_pass"
    assert hard_report.pass_flag == 1
    assert hard_report.next_action == "pass"
    assert soft_report.qc_type == "soft_qc"
    assert soft_report.source_draft_row_id == style_draft.row_id
    assert soft_report.resolution_code == "soft_pass"
    assert soft_report.pass_flag == 1
    assert soft_report.next_action == "pass"
    assert state.current_qc_report_id == soft_report.qc_report_id
    assert state.current_human_review_event_id is None
    assert style_draft.content == "Provider-generated style scene text."
    assert final_scene.content == style_draft.content
    assert final_scene.generation_llm_call_id == style_draft.generation_llm_call_id
    assert state.current_style_draft_row_id == style_draft.row_id
    assert state.current_final_scene_row_id == final_scene.row_id
    assert [attempt.step for attempt in attempts if attempt.step in {"style_draft", "soft_qc", "finalize"}] == [
        "style_draft",
        "soft_qc",
        "finalize",
    ]
    finalize_attempt = next(attempt for attempt in attempts if attempt.step == "finalize")
    assert finalize_attempt.details_json["source_style_draft_row_id"] == style_draft.row_id
    assert finalize_attempt.details_json["source_qc_report_id"] == soft_report.qc_report_id


def test_run_scene_soft_qc_waive_preserves_carry_note_details_and_finalizes(session) -> None:
    _seed_scene(session)
    orchestrator = _make_orchestrator(
        session,
        hard_qc_payload=_base_qc_payload(resolution_code="hard_pass", next_action="pass"),
        soft_qc_payloads=[
            _base_soft_qc_payload(
                resolution_code="soft_waive",
                next_action="pass_with_notes",
                carry_forward_note=True,
                note_scope="chapter_memory",
                carry_note_text="Keep the envelope motif in future callbacks.",
            )
        ],
    )

    result = orchestrator.run_scene("CH100_SC01")
    session.commit()

    style_draft = session.execute(select(SceneDraft).where(SceneDraft.stage == "style_draft")).scalars().one()
    final_scene = session.execute(select(FinalScene)).scalars().one()
    report = session.execute(select(QcReport).where(QcReport.qc_type == "soft_qc")).scalars().one()
    scene_memory = session.execute(select(SceneMemory).where(SceneMemory.scene_id == "CH100_SC01")).scalars().one()

    assert result["soft_qc"]["branch"] == "waive"
    assert report.resolution_code == "soft_waive"
    assert report.next_action == "pass_with_notes"
    assert report.pass_flag == 1
    assert report.rewrite_brief_json == [
        {
            "kind": "carry_forward_note",
            "note_scope": "chapter_memory",
            "carry_note_text": "Keep the envelope motif in future callbacks.",
        }
    ]
    assert scene_memory.carry_notes_json == [
        {
            "kind": "carry_forward_note",
            "note_scope": "chapter_memory",
            "carry_note_text": "Keep the envelope motif in future callbacks.",
        }
    ]
    assert final_scene.content == style_draft.content
    assert final_scene.generation_llm_call_id == style_draft.generation_llm_call_id


def test_run_scene_soft_qc_patch_rechecks_before_finalize(session) -> None:
    _seed_scene(session)
    orchestrator = _make_orchestrator(
        session,
        hard_qc_payload=_base_qc_payload(resolution_code="hard_pass", next_action="pass"),
        soft_qc_payloads=[
            _base_soft_qc_payload(
                resolution_code="soft_patch",
                next_action="patch",
                issues=[{"issue_key": "opening_flat", "message": "The opening needs more immediacy."}],
                rewrite_brief=["Tighten the first paragraph.", "Move the red envelope beat earlier."],
            ),
            _base_soft_qc_payload(
                resolution_code="soft_pass",
                next_action="pass",
            ),
        ],
    )

    result = orchestrator.run_scene("CH100_SC01")
    session.commit()

    drafts = session.execute(select(SceneDraft).order_by(SceneDraft.created_at.asc(), SceneDraft.row_id.asc())).scalars().all()
    style_draft = next(draft for draft in drafts if draft.stage == "style_draft")
    patch_draft = next(draft for draft in drafts if draft.stage == "style_patch")
    final_scene = session.execute(select(FinalScene)).scalars().one()
    reports = session.execute(select(QcReport).where(QcReport.qc_type == "soft_qc").order_by(QcReport.created_at.asc(), QcReport.qc_report_id.asc())).scalars().all()
    attempts = session.execute(select(AttemptTracker).order_by(AttemptTracker.attempt_id.asc())).scalars().all()
    state = session.get(SceneRunState, "CH100_SC01")

    assert result["soft_qc"]["branch"] == "continue"
    assert len(reports) == 2
    assert reports[0].next_action == "patch"
    assert reports[1].next_action == "pass"
    assert patch_draft.content == "Provider-generated patched scene text."
    assert patch_draft.content != style_draft.content
    assert final_scene.content == patch_draft.content
    assert final_scene.generation_llm_call_id == patch_draft.generation_llm_call_id
    assert state.current_style_draft_row_id == patch_draft.row_id
    assert state.current_final_scene_row_id == final_scene.row_id
    assert state.soft_patch_count == 1
    assert [attempt.step for attempt in attempts if attempt.step in {"style_draft", "soft_qc", "soft_patch", "finalize"}] == [
        "style_draft",
        "soft_qc",
        "soft_patch",
        "soft_qc",
        "finalize",
    ]
    patch_attempt = next(attempt for attempt in attempts if attempt.step == "soft_patch")
    assert patch_attempt.details_json["source_qc_report_id"] == reports[0].qc_report_id
    assert patch_attempt.details_json["source_style_draft_row_id"] == style_draft.row_id


def test_run_scene_soft_qc_patch_repeat_escalates_to_human_review(session) -> None:
    _seed_scene(session)
    orchestrator = _make_orchestrator(
        session,
        hard_qc_payload=_base_qc_payload(resolution_code="hard_pass", next_action="pass"),
        soft_qc_payloads=[
            _base_soft_qc_payload(
                resolution_code="soft_patch",
                next_action="patch",
                issues=[{"issue_key": "opening_flat", "message": "The opening needs more immediacy."}],
                rewrite_brief=["Tighten the first paragraph."],
            ),
            _base_soft_qc_payload(
                resolution_code="soft_patch",
                next_action="patch",
                issues=[{"issue_key": "opening_flat", "message": "The opening still feels flat."}],
                rewrite_brief=["Add sharper contrast in the first beats."],
            ),
        ],
    )

    result = orchestrator.run_scene("CH100_SC01")
    session.commit()

    state = session.get(SceneRunState, "CH100_SC01")
    final_scene = session.execute(select(FinalScene)).scalars().all()
    event = session.execute(select(HumanReviewEvent)).scalars().one()
    attempts = session.execute(select(AttemptTracker).order_by(AttemptTracker.attempt_id.asc())).scalars().all()

    assert result["scene_status"] == "human_review_required"
    assert result["soft_qc"]["branch"] == "human_review_required"
    assert state.current_style_draft_row_id is None
    assert state.current_final_scene_row_id is None
    assert final_scene == []
    assert state.current_human_review_event_id == event.event_id
    assert event.event_source == "scene_generation"
    assert event.details_json["trigger_reason"] == "soft_qc_patch_cycle_limit"
    assert [attempt.step for attempt in attempts if attempt.step in {"style_draft", "soft_qc", "soft_patch"}] == [
        "style_draft",
        "soft_qc",
        "soft_patch",
        "soft_qc",
    ]


def test_run_scene_hard_qc_rewrite_branch_updates_counters_and_stops_before_style_generation(session) -> None:
    _seed_scene(session)
    orchestrator = _make_orchestrator(
        session,
        hard_qc_payload=_base_qc_payload(
            resolution_code="hard_fail_partial",
            next_action="partial_rewrite",
            issues=[{"issue_key": "missing_red_envelope", "message": "The required handoff is absent."}],
        ),
    )

    result = orchestrator.run_scene("CH100_SC01")
    session.commit()

    state = session.get(SceneRunState, "CH100_SC01")
    report = session.execute(select(QcReport)).scalars().one()

    assert result["scene_status"] == "hard_qc_partial_rewrite_required"
    assert result["hard_qc"]["branch"] == "rewrite_partial"
    assert report.resolution_code == "hard_fail_partial"
    assert state.hard_partial_rewrite_count == 1
    assert state.hard_full_rewrite_count == 0
    assert state.repeat_issue_key == "missing_red_envelope"
    assert state.repeat_issue_count == 1
    assert state.current_final_scene_row_id is None
    assert session.execute(select(SceneDraft).where(SceneDraft.stage == "style_draft")).scalars().all() == []
    assert session.execute(select(FinalScene)).scalars().all() == []


def test_hard_qc_engine_escalates_repeated_issue_key_to_human_review(session) -> None:
    _seed_scene(session)
    state = session.get(SceneRunState, "CH100_SC01")
    state.repeat_issue_key = "same_issue"
    state.repeat_issue_count = 1
    session.add(
        SceneDraft(
            row_id="draft_neutral_CH100_SC01",
            scene_id="CH100_SC01",
            chapter_id="CH100",
            stage="neutral_draft",
            content="Neutral draft under review.",
            source_bundle_id="bundle_CH100_SC01",
            source_bundle_hash="bundle_hash_CH100_SC01",
        )
    )
    session.commit()

    engine = HardQcEngine(
        session,
        llm_client=FakeQcClient(
            _base_qc_payload(
                resolution_code="hard_fail_partial",
                next_action="partial_rewrite",
                issues=[{"issue_key": "same_issue", "message": "The same blocker appeared again."}],
            )
        ),
    )

    decision = engine.evaluate(
        scene_id="CH100_SC01",
        bundle={
            "bundle_id": "bundle_CH100_SC01",
            "bundle_snapshot_hash": "bundle_hash_CH100_SC01",
            "snapshot": {"scene_id": "CH100_SC01", "chapter_id": "CH100", "inline_digests": {"scene_card": "Goal"}},
        },
        neutral_draft_row_id="draft_neutral_CH100_SC01",
        neutral_content="Neutral draft under review.",
    )
    session.commit()

    state = session.get(SceneRunState, "CH100_SC01")
    event = session.execute(select(HumanReviewEvent)).scalars().one()

    assert decision.branch == "human_review_required"
    assert state.repeat_issue_key == "same_issue"
    assert state.repeat_issue_count == 2
    assert state.current_human_review_event_id == event.event_id
    assert event.event_source == "scene_generation"
    assert event.status == "needs_followup"
    assert event.details_json["trigger_reason"] == "repeat_issue_key_limit"
    assert event.details_json["recommended_action"] == "human_review_required"


def test_hard_qc_engine_turns_malformed_payload_into_human_review_required(session) -> None:
    _seed_scene(session)
    session.add(
        SceneDraft(
            row_id="draft_neutral_CH100_SC01",
            scene_id="CH100_SC01",
            chapter_id="CH100",
            stage="neutral_draft",
            content="Neutral draft under review.",
            source_bundle_id="bundle_CH100_SC01",
            source_bundle_hash="bundle_hash_CH100_SC01",
        )
    )
    session.commit()

    engine = HardQcEngine(
        session,
        llm_client=FakeQcClient({"passed": False, "issues": [{"severity": "hard", "message": "bad shape"}]}),
    )

    decision = engine.evaluate(
        scene_id="CH100_SC01",
        bundle={
            "bundle_id": "bundle_CH100_SC01",
            "bundle_snapshot_hash": "bundle_hash_CH100_SC01",
            "snapshot": {"scene_id": "CH100_SC01", "chapter_id": "CH100", "inline_digests": {"scene_card": "Goal"}},
        },
        neutral_draft_row_id="draft_neutral_CH100_SC01",
        neutral_content="Neutral draft under review.",
    )
    session.commit()

    report = session.execute(select(QcReport)).scalars().one()
    event = session.execute(select(HumanReviewEvent)).scalars().one()

    assert decision.branch == "human_review_required"
    assert report.resolution_code == "hard_block_human"
    assert report.next_action == "human_review_required"
    assert report.pass_flag == 0
    assert event.details_json["trigger_reason"] == "invalid_hard_qc_payload"
    assert "validation" in event.details_json["failure_reason"]


def test_generation_originated_human_review_event_matches_existing_inbox_shape(client, session) -> None:
    _seed_scene(session)
    event = HumanReviewManager(session).create_generation_blocker_event(
        scene_id="CH100_SC01",
        chapter_id="CH100",
        object_ref="draft_neutral_CH100_SC01",
        target_type="scene_draft",
        target_id="draft_neutral_CH100_SC01",
        target_ref="scene_draft:draft_neutral_CH100_SC01",
        failure_reason="Hard QC rejected the neutral draft twice for the same issue.",
        trigger_reason="repeat_issue_key_limit",
        recommended_action="human_review_required",
        replay_context={
            "scene_id": "CH100_SC01",
            "chapter_id": "CH100",
            "source_bundle_id": "bundle_CH100_SC01",
            "neutral_draft_row_id": "draft_neutral_CH100_SC01",
        },
    )
    session.commit()

    response = client.get("/api/v1/human-review-events", params={"event_source": "scene_generation"})

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["event_id"] == event.event_id
    assert item["event_source"] == "scene_generation"
    assert item["object_ref"] == "draft_neutral_CH100_SC01"
    assert item["linked_target"] == {
        "target_type": "scene_draft",
        "target_id": "draft_neutral_CH100_SC01",
        "target_ref": "scene_draft:draft_neutral_CH100_SC01",
    }
    assert item["details_json"]["trigger_reason"] == "repeat_issue_key_limit"
    assert item["details_json"]["recommended_action"] == "human_review_required"
    assert item["details_json"]["replay_context"]["source_bundle_id"] == "bundle_CH100_SC01"


def test_run_scene_clears_stale_pointers_across_blocked_and_successful_reruns(session) -> None:
    _seed_scene(session)
    state = session.get(SceneRunState, "CH100_SC01")
    state.current_style_draft_row_id = "draft_style_old"
    state.current_final_scene_row_id = "final_scene_old"
    state.current_human_review_event_id = "human_review_old"
    session.commit()

    blocked = _make_orchestrator(
        session,
        hard_qc_payload=_base_qc_payload(
            resolution_code="hard_fail_partial",
            next_action="partial_rewrite",
            issues=[{"issue_key": "missing_red_envelope", "message": "The required handoff is absent."}],
        ),
    )

    blocked_result = blocked.run_scene("CH100_SC01")
    session.commit()

    state = session.get(SceneRunState, "CH100_SC01")
    blocked_event_id = state.current_human_review_event_id
    assert blocked_result["current_final_scene_row_id"] is None
    assert state.current_style_draft_row_id is None
    assert state.current_final_scene_row_id is None
    assert blocked_event_id is None

    state.current_human_review_event_id = "human_review_stale_from_previous_block"
    session.commit()

    rerun = _make_orchestrator(
        session,
        hard_qc_payload=_base_qc_payload(resolution_code="hard_pass", next_action="pass"),
        soft_qc_payloads=[_base_soft_qc_payload(resolution_code="soft_pass", next_action="pass")],
    )

    rerun_result = rerun.run_scene("CH100_SC01")
    session.commit()

    state = session.get(SceneRunState, "CH100_SC01")
    assert rerun_result["scene_status"] == "archived"
    assert rerun_result["current_final_scene_row_id"] == state.current_final_scene_row_id
    assert rerun_result["current_human_review_event_id"] is None
    assert state.current_style_draft_row_id.startswith("draft_style_CH100_SC01_v")
    assert state.current_final_scene_row_id.startswith("final_scene_CH100_SC01_v")
    assert state.current_human_review_event_id is None


def test_run_scene_resets_soft_patch_state_between_reruns(session) -> None:
    _seed_scene(session)
    first = _make_orchestrator(
        session,
        hard_qc_payload=_base_qc_payload(resolution_code="hard_pass", next_action="pass"),
        soft_qc_payloads=[
            _base_soft_qc_payload(
                resolution_code="soft_patch",
                next_action="patch",
                issues=[{"issue_key": "opening_flat", "message": "The opening needs more immediacy."}],
                rewrite_brief=["Tighten the first paragraph.", "Move the red envelope beat earlier."],
            ),
            _base_soft_qc_payload(
                resolution_code="soft_pass",
                next_action="pass",
            ),
        ],
    )

    first_result = first.run_scene("CH100_SC01")
    session.commit()

    state = session.get(SceneRunState, "CH100_SC01")
    first_neutral_row_id = state.current_neutral_draft_row_id
    first_qc_report_id = state.current_qc_report_id

    rerun = _make_orchestrator(
        session,
        hard_qc_payload=_base_qc_payload(resolution_code="hard_pass", next_action="pass"),
        soft_qc_payloads=[
            _base_soft_qc_payload(
                resolution_code="soft_patch",
                next_action="patch",
                issues=[{"issue_key": "opening_flat", "message": "The opening still needs work."}],
                rewrite_brief=["Tighten the first paragraph again."],
            ),
            _base_soft_qc_payload(
                resolution_code="soft_pass",
                next_action="pass",
            ),
        ],
    )

    rerun_result = rerun.run_scene("CH100_SC01")
    session.commit()

    state = session.get(SceneRunState, "CH100_SC01")
    attempts = session.execute(select(AttemptTracker).order_by(AttemptTracker.attempt_id.asc())).scalars().all()
    human_reviews = session.execute(select(HumanReviewEvent)).scalars().all()

    assert first_result["scene_status"] == "archived"
    assert rerun_result["scene_status"] == "archived"
    assert state.soft_patch_count == 1
    assert state.current_neutral_draft_row_id != first_neutral_row_id
    assert session.get(SceneDraft, first_neutral_row_id) is not None
    assert session.get(SceneDraft, state.current_neutral_draft_row_id) is not None
    assert state.current_qc_report_id != first_qc_report_id
    assert state.current_human_review_event_id is None
    assert len([attempt for attempt in attempts if attempt.step == "neutral_draft"]) == 2
    assert len([attempt for attempt in attempts if attempt.step == "soft_patch"]) == 2
    assert len([attempt for attempt in attempts if attempt.step == "finalize"]) == 2
    assert human_reviews == []


def test_hard_qc_engine_turns_runtime_failure_into_human_review_with_distinct_reason(session) -> None:
    _seed_scene(session)
    session.add(
        SceneDraft(
            row_id="draft_neutral_CH100_SC01",
            scene_id="CH100_SC01",
            chapter_id="CH100",
            stage="neutral_draft",
            content="Neutral draft under review.",
            source_bundle_id="bundle_CH100_SC01",
            source_bundle_hash="bundle_hash_CH100_SC01",
        )
    )
    session.commit()

    engine = HardQcEngine(session, llm_client=FakeQcRuntimeFailureClient())

    decision = engine.evaluate(
        scene_id="CH100_SC01",
        bundle={
            "bundle_id": "bundle_CH100_SC01",
            "bundle_snapshot_hash": "bundle_hash_CH100_SC01",
            "snapshot": {"scene_id": "CH100_SC01", "chapter_id": "CH100", "inline_digests": {"scene_card": "Goal"}},
        },
        neutral_draft_row_id="draft_neutral_CH100_SC01",
        neutral_content="Neutral draft under review.",
    )
    session.commit()

    report = session.execute(select(QcReport)).scalars().one()
    event = session.execute(select(HumanReviewEvent)).scalars().one()

    assert decision.branch == "human_review_required"
    assert report.resolution_code == "hard_block_human"
    assert event.details_json["trigger_reason"] == "hard_qc_execution_failed"
    assert "execution failed" in event.details_json["failure_reason"]
    assert "timed out" in event.details_json["failure_reason"]
