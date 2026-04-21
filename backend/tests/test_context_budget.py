from __future__ import annotations

from sqlalchemy import select

from novel_system.db.models import AttemptTracker, ChapterGoal, HumanReviewEvent, LlmCall, QcReport, SceneCard, SceneDraft, SceneRunState
from novel_system.services.context_budget import (
    CONTINUITY_DROP_ORDER,
    apply_context_budget,
    collect_prompt_sections,
    finalize_request_budget,
)
from novel_system.services.llm_client import LLMRequest
from novel_system.services.prompt_builder import PromptBuilder
from novel_system.services.qc_engine import HardQcEngine, SoftQcEngine


def _bundle_snapshot() -> dict:
    return {
        "contract_version": "BSHASH_v1",
        "stage_allowlist_name": "bundle_build_allowlist_v1",
        "scene_id": "CH001_SC01",
        "chapter_id": "CH001",
        "inline_digests": {
            "chapter_goal": " ".join(["Goal pressure"] * 80),
            "scene_card": " ".join(["Scene pressure"] * 80),
            "voice_card": "Short clipped lines; pressure makes the tone harder.",
            "style_rule": "Keep emotion in gesture and pause.",
            "banned_rule": "Do not explain the whole backstory at reunion time.",
            "style_observation": (
                "Gesture before explanation. Let silence carry accusation. "
                "End paragraphs on pressure, not exposition. Keep the emotional turn tactile."
            ),
            "calibration_line": "The door closed like a sentence left unfinished.",
            "relation_card": "Reunion tension; B knows slightly more than A.",
            "world_rule": "Public spellcasting inside the city is forbidden.",
            "foreshadow": "The old letter sender clue is now in play.",
            "scene_memory": "Previous scene memory digest about the hidden sender.",
            "scene_summary": "Current scene summary digest about the reunion beat.",
            "chapter_summary": "Chapter summary digest about guarded trust replacing suspicion.",
            "similar_scene": (
                "Similar-scene reference: another gate reunion leaned too heavily on explanation "
                "and lost pressure halfway through."
            ),
        },
    }


def _seed_scene(session) -> None:
    session.add(
        ChapterGoal(
            chapter_id="CH100",
            planned_scene_count=1,
            chapter_goal="A reunion turns dangerous.",
        )
    )
    session.add(
        SceneCard(
            scene_id="CH100_SC01",
            chapter_id="CH100",
            scene_seq=1,
            scene_goal="Force both characters to reveal what they know.",
        )
    )
    session.add(SceneRunState(scene_id="CH100_SC01", scene_status="ready"))
    session.commit()


class TrackingClient:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest):  # pragma: no cover - should never be called in these tests
        self.requests.append(request)
        raise AssertionError("LLM should not be called when continuity warning requires scene splitting")


def test_apply_context_budget_uses_expected_compaction_order_and_warning_shape() -> None:
    snapshot = _bundle_snapshot()
    sections = collect_prompt_sections(snapshot)

    result = apply_context_budget(
        system_prompt="System prompt.",
        task_prompt="Task prompt.",
        bundle_snapshot=snapshot,
        sections=sections,
        max_input_tokens=120,
    )
    budget = result["budget"]
    warning = result["continuity_warning"]

    assert budget["section_status"]["similar_scene_context"]["status"] == "omitted"
    assert budget["section_status"]["style_observations"]["status"] == "compressed"
    assert budget["section_status"]["calibration_lines"]["status"] == "included"
    assert [budget["section_status"][name]["status"] for name in CONTINUITY_DROP_ORDER] == [
        "included",
        "included",
        "included",
    ]
    assert warning == {
        "code": "continuity_budget_exceeded",
        "message": "Prompt still exceeds the safe input budget after deterministic continuity compaction.",
        "recommended_action": "split_scene",
        "requires_scene_split": True,
        "compressed_sections": ["style_observations"],
        "omitted_sections": ["similar_scene_context"],
        "estimated_input_tokens": budget["estimated_input_tokens"],
        "target_input_tokens": 120,
    }


def test_prompt_builder_surfaces_continuity_warning_into_token_budget() -> None:
    payload = PromptBuilder().build(_bundle_snapshot(), "neutral_draft", max_input_tokens=120)

    assert payload["continuity_warning"] == payload["token_budget"]["continuity_warning"]
    assert payload["continuity_warning"]["code"] == "continuity_budget_exceeded"
    assert payload["continuity_warning"]["recommended_action"] == "split_scene"
    assert payload["token_budget"]["split_scene_recommended"] is True
    assert payload["token_budget"]["stop_reason"] == "split_scene_recommended"


def test_finalize_request_budget_marks_actual_final_prompt_overflow() -> None:
    base_budget = {
        "target_input_tokens": 80,
        "estimated_input_tokens": 40,
        "remaining_input_tokens": 40,
        "included_sections": ["scene_card"],
        "compressed_sections": [],
        "omitted_sections": [],
        "section_status": {"scene_card": {"label": "Scene Card", "status": "included", "estimated_tokens": 20}},
        "continuity_policy": [],
        "split_scene_recommended": False,
        "stop_reason": None,
        "continuity_warning": None,
    }

    result = finalize_request_budget(
        system_prompt="system prompt",
        user_prompt=" ".join(["expanded final prompt"] * 60),
        base_budget=base_budget,
    )

    assert result["budget"]["estimated_input_tokens"] > 80
    assert result["budget"]["split_scene_recommended"] is True
    assert result["continuity_warning"]["requires_scene_split"] is True
    assert result["continuity_warning"]["code"] == "continuity_budget_exceeded"


def test_apply_context_budget_compresses_calibration_and_digest_context_before_split() -> None:
    snapshot = _bundle_snapshot()
    snapshot["inline_digests"]["chapter_goal"] = " ".join(["Goal pressure"] * 80)
    snapshot["inline_digests"]["scene_card"] = " ".join(["Scene pressure"] * 80)
    snapshot["inline_digests"]["calibration_line"] = "First calibration line.\n\nSecond calibration line."
    snapshot["inline_digests"]["relation_card"] = " ".join(["relation digest"] * 20)
    snapshot["inline_digests"]["world_rule"] = " ".join(["world rule digest"] * 20)
    snapshot["inline_digests"]["scene_memory"] = " ".join(["scene memory digest"] * 20)

    result = apply_context_budget(
        system_prompt="System prompt.",
        task_prompt="Task prompt.",
        bundle_snapshot=snapshot,
        sections=collect_prompt_sections(snapshot),
        max_input_tokens=120,
    )
    budget = result["budget"]

    assert budget["section_status"]["calibration_lines"]["status"] == "compressed"
    assert budget["section_status"]["relation_digest"]["status"] == "compressed"
    assert budget["section_status"]["world_rules"]["status"] == "compressed"
    assert budget["section_status"]["scene_memory_digest"]["status"] == "compressed"
    assert "## Calibration Lines (compressed)" in result["user_prompt"]
    assert "Second calibration line." not in result["user_prompt"]


def test_hard_qc_engine_escalates_continuity_warning_before_llm_call(session) -> None:
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

    client = TrackingClient()
    engine = HardQcEngine(session, llm_client=client)
    continuity_warning = {
        "code": "continuity_budget_exceeded",
        "message": "Prompt still exceeds the safe input budget after deterministic continuity compaction.",
        "recommended_action": "split_scene",
        "requires_scene_split": True,
    }
    engine.prompt_builder.build = lambda *_args, **_kwargs: {
        "system_prompt": "system",
        "user_prompt": "user",
        "structured_schema": {},
        "token_budget": {
            "target_input_tokens": 60,
            "estimated_input_tokens": 80,
            "remaining_input_tokens": -20,
            "included_sections": [],
            "compressed_sections": [],
            "omitted_sections": [],
            "section_status": {},
            "continuity_policy": [],
            "split_scene_recommended": True,
            "stop_reason": "split_scene_recommended",
            "continuity_warning": continuity_warning,
        },
        "continuity_warning": continuity_warning,
    }

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
    attempt = session.execute(select(AttemptTracker).where(AttemptTracker.step == "hard_qc")).scalars().one()
    llm_call = session.execute(select(LlmCall).where(LlmCall.step == "hard_qc")).scalars().one()

    assert client.requests == []
    assert decision.branch == "human_review_required"
    assert decision.stop_reason == "hard_qc_continuity_budget_exceeded"
    assert attempt.details_json["llm_call_id"] == llm_call.llm_call_id
    assert attempt.details_json["continuity_warning"]["requires_scene_split"] is True
    assert llm_call.error_code == "CONTINUITY_BUDGET_EXCEEDED"
    assert report.next_action == "human_review_required"
    assert report.issues_json[0]["issue_key"] == "continuity_budget_exceeded"
    assert report.issues_json[0]["message"] == continuity_warning["message"]
    assert report.issues_json[0]["continuity_warning"]["code"] == continuity_warning["code"]
    assert report.issues_json[0]["continuity_warning"]["recommended_action"] == "split_scene"
    assert report.issues_json[0]["continuity_warning"]["requires_scene_split"] is True
    assert report.issues_json[0]["continuity_warning"]["target_input_tokens"] == 60
    assert isinstance(report.issues_json[0]["continuity_warning"]["estimated_input_tokens"], int)
    assert report.rewrite_brief_json == [{"instruction": "Split the scene and retry QC with a smaller continuity scope."}]
    assert event.details_json["trigger_reason"] == "hard_qc_continuity_budget_exceeded"
    assert event.details_json["replay_context"]["continuity_warning"] == report.issues_json[0]["continuity_warning"]


def test_hard_qc_engine_recomputes_budget_for_final_prompt_before_llm_call(session) -> None:
    _seed_scene(session)
    client = TrackingClient()
    engine = HardQcEngine(session, llm_client=client)
    engine.prompt_builder.build = lambda *_args, **_kwargs: {
        "system_prompt": "system",
        "user_prompt": "user",
        "structured_schema": {},
        "token_budget": {
            "target_input_tokens": 60,
            "estimated_input_tokens": 10,
            "remaining_input_tokens": 50,
            "included_sections": [],
            "compressed_sections": [],
            "omitted_sections": [],
            "section_status": {},
            "continuity_policy": [],
            "split_scene_recommended": False,
            "stop_reason": None,
            "continuity_warning": None,
        },
        "continuity_warning": None,
    }

    decision = engine.evaluate(
        scene_id="CH100_SC01",
        bundle={
            "bundle_id": "bundle_CH100_SC01",
            "bundle_snapshot_hash": "bundle_hash_CH100_SC01",
            "snapshot": {"scene_id": "CH100_SC01", "chapter_id": "CH100", "inline_digests": {"scene_card": "Goal"}},
        },
        neutral_draft_row_id="draft_neutral_CH100_SC01",
        neutral_content=" ".join(["oversized neutral draft"] * 80),
    )
    session.commit()

    report = session.execute(select(QcReport)).scalars().one()

    assert client.requests == []
    assert decision.branch == "human_review_required"
    assert report.issues_json[0]["issue_key"] == "continuity_budget_exceeded"


def test_soft_qc_engine_escalates_continuity_warning_before_llm_call(session) -> None:
    _seed_scene(session)
    session.add(
        SceneDraft(
            row_id="draft_style_CH100_SC01",
            scene_id="CH100_SC01",
            chapter_id="CH100",
            stage="style_draft",
            content="Styled draft under review.",
            source_bundle_id="bundle_CH100_SC01",
            source_bundle_hash="bundle_hash_CH100_SC01",
        )
    )
    session.commit()

    client = TrackingClient()
    engine = SoftQcEngine(session, llm_client=client)
    continuity_warning = {
        "code": "continuity_budget_exceeded",
        "message": "Prompt still exceeds the safe input budget after deterministic continuity compaction.",
        "recommended_action": "split_scene",
        "requires_scene_split": True,
    }
    engine.prompt_builder.build = lambda *_args, **_kwargs: {
        "system_prompt": "system",
        "user_prompt": "user",
        "structured_schema": {},
        "token_budget": {
            "target_input_tokens": 60,
            "estimated_input_tokens": 80,
            "remaining_input_tokens": -20,
            "included_sections": [],
            "compressed_sections": [],
            "omitted_sections": [],
            "section_status": {},
            "continuity_policy": [],
            "split_scene_recommended": True,
            "stop_reason": "split_scene_recommended",
            "continuity_warning": continuity_warning,
        },
        "continuity_warning": continuity_warning,
    }

    decision = engine.evaluate(
        scene_id="CH100_SC01",
        bundle={
            "bundle_id": "bundle_CH100_SC01",
            "bundle_snapshot_hash": "bundle_hash_CH100_SC01",
            "snapshot": {"scene_id": "CH100_SC01", "chapter_id": "CH100", "inline_digests": {"scene_card": "Goal"}},
        },
        source_draft_row_id="draft_style_CH100_SC01",
        source_draft_content="Styled draft under review.",
    )
    session.commit()

    report = session.execute(select(QcReport)).scalars().one()
    event = session.execute(select(HumanReviewEvent)).scalars().one()
    attempt = session.execute(select(AttemptTracker).where(AttemptTracker.step == "soft_qc")).scalars().one()
    llm_call = session.execute(select(LlmCall).where(LlmCall.step == "soft_qc")).scalars().one()

    assert client.requests == []
    assert decision.branch == "human_review_required"
    assert decision.stop_reason == "soft_qc_continuity_budget_exceeded"
    assert attempt.details_json["llm_call_id"] == llm_call.llm_call_id
    assert attempt.details_json["continuity_warning"]["requires_scene_split"] is True
    assert llm_call.error_code == "CONTINUITY_BUDGET_EXCEEDED"
    assert report.next_action == "human_review_required"
    assert report.issues_json[0]["issue_key"] == "continuity_budget_exceeded"
    assert report.issues_json[0]["message"] == continuity_warning["message"]
    assert report.issues_json[0]["continuity_warning"]["code"] == continuity_warning["code"]
    assert report.issues_json[0]["continuity_warning"]["recommended_action"] == "split_scene"
    assert report.issues_json[0]["continuity_warning"]["requires_scene_split"] is True
    assert report.issues_json[0]["continuity_warning"]["target_input_tokens"] == 60
    assert isinstance(report.issues_json[0]["continuity_warning"]["estimated_input_tokens"], int)
    assert report.rewrite_brief_json == [{"instruction": "Split the scene and retry QC with a smaller continuity scope."}]
    assert event.details_json["trigger_reason"] == "soft_qc_continuity_budget_exceeded"
    assert event.details_json["replay_context"]["continuity_warning"] == report.issues_json[0]["continuity_warning"]


def test_soft_qc_engine_recomputes_budget_for_final_prompt_before_llm_call(session) -> None:
    _seed_scene(session)
    client = TrackingClient()
    engine = SoftQcEngine(session, llm_client=client)
    engine.prompt_builder.build = lambda *_args, **_kwargs: {
        "system_prompt": "system",
        "user_prompt": "user",
        "structured_schema": {},
        "token_budget": {
            "target_input_tokens": 60,
            "estimated_input_tokens": 10,
            "remaining_input_tokens": 50,
            "included_sections": [],
            "compressed_sections": [],
            "omitted_sections": [],
            "section_status": {},
            "continuity_policy": [],
            "split_scene_recommended": False,
            "stop_reason": None,
            "continuity_warning": None,
        },
        "continuity_warning": None,
    }

    decision = engine.evaluate(
        scene_id="CH100_SC01",
        bundle={
            "bundle_id": "bundle_CH100_SC01",
            "bundle_snapshot_hash": "bundle_hash_CH100_SC01",
            "snapshot": {"scene_id": "CH100_SC01", "chapter_id": "CH100", "inline_digests": {"scene_card": "Goal"}},
        },
        source_draft_row_id="draft_style_CH100_SC01",
        source_draft_content=" ".join(["oversized styled draft"] * 80),
    )
    session.commit()

    report = session.execute(select(QcReport)).scalars().one()

    assert client.requests == []
    assert decision.branch == "human_review_required"
    assert report.issues_json[0]["issue_key"] == "continuity_budget_exceeded"
