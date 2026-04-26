from __future__ import annotations

import pytest
from sqlalchemy import select

from novel_system.db.models import (
    AttemptTracker,
    AuthorPreferenceProfile,
    ChapterGoal,
    ChapterState,
    FinalScene,
    LlmCall,
    RelationProfile,
    SceneBlueprint,
    SceneBundle,
    SceneCard,
    SceneDraft,
    SceneRunState,
    VoiceProfile,
)
from novel_system.services.bundle_builder import BundleBuilder
from novel_system.services.errors import DomainError
from novel_system.services.context_budget import estimate_tokens
from novel_system.services.llm_client import LLMRequest, LLMResponse
from novel_system.services.prompt_builder import PromptConfigurationError
from novel_system.services.orchestrator import Orchestrator
from novel_system.services.scene_generation import SceneGenerationService


class FakeSceneClient:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            structured_output = {
                "scene_text": "Provider-generated neutral scene text.",
                "continuity_notes": ["kept the reunion tense"],
            }
            request_id = "resp_fake_neutral_001"
            model = "fake-neutral-model"
            usage = {"input_tokens": 111, "output_tokens": 29, "total_tokens": 140}
        elif len(self.requests) == 2:
            structured_output = {
                "scene_text": "Provider-generated style scene text.",
                "style_notes": ["leaned harder into rhythm and inner tension"],
            }
            request_id = "resp_fake_style_001"
            model = "fake-style-model"
            usage = {"input_tokens": 121, "output_tokens": 33, "total_tokens": 154}
        else:
            structured_output = {
                "scene_text": "Provider-generated patched scene text.",
                "style_notes": ["applied one controlled patch pass"],
            }
            request_id = "resp_fake_patch_001"
            model = "fake-patch-model"
            usage = {"input_tokens": 131, "output_tokens": 37, "total_tokens": 168}
        return LLMResponse(
            request_id=request_id,
            provider="fake-provider",
            model=model,
            text=__import__("json").dumps(structured_output),
            structured_output=structured_output,
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


class FakeFailingClient:
    def generate(self, request: LLMRequest) -> LLMResponse:
        raise ValueError("malformed provider payload")


class FakeDeTemplateClient:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            structured_output = {
                "scene_text": (
                    "她低头看着钥匙，沉默了片刻。"
                    "他低头看着录音，沉默了片刻。"
                    "她低头看着门缝，沉默了片刻。"
                    "她知道真相必须公开。"
                ),
                "style_notes": ["kept an unsafe template"],
            }
            request_id = "resp_fake_style_template"
            model = "fake-style-model"
        else:
            structured_output = {
                "scene_text": "她把钥匙扣进掌心，转身拔掉录音线。门缝里的光灭了，外面的人开始敲门。",
                "style_notes": ["removed repeated action template"],
            }
            request_id = "resp_fake_de_template"
            model = "fake-patch-model"
        return LLMResponse(
            request_id=request_id,
            provider="fake-provider",
            model=model,
            text=__import__("json").dumps(structured_output),
            structured_output=structured_output,
            response_format="json_object",
            raw_response={"id": request_id, "model": model, "usage": {}, "finish_reason": "stop"},
            usage={"input_tokens": 101, "output_tokens": 25, "total_tokens": 126},
            finish_reason="stop",
        )


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


def _seed_scene_blueprint(session) -> None:
    session.add(
        SceneBlueprint(
            row_id="scene_blueprint_CH100_SC01_seed",
            scene_id="CH100_SC01",
            chapter_id="CH100",
            source_bundle_id="seed_source_CH100_SC01",
            source_bundle_hash="seed_hash_CH100_SC01",
            blueprint_json={
                "character_current_desire": "CHAR_A wants the truth before CHAR_B can leave.",
                "concrete_obstacle": "CHAR_B controls the red envelope and refuses a straight answer.",
                "choice_under_pressure": "CHAR_A must choose whether to trust CHAR_B or expose the clue.",
                "information_release": "The envelope proves someone watched the reunion.",
                "power_shift": "CHAR_B begins with leverage; CHAR_A takes it back by naming the watcher.",
                "emotional_turn": "Suspicion hardens into reluctant alliance.",
                "irreversible_consequence": "Both characters know the secret is no longer private.",
                "ending_reader_question": "Who sent the red envelope?",
                "image_promise": "The red envelope returns with a changed meaning.",
            },
            status="accepted",
        )
    )
    session.commit()


def test_run_scene_persists_provider_neutral_draft_and_bundle_linkage(session) -> None:
    _seed_scene(session)
    fake_client = FakeSceneClient()

    orchestrator = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=fake_client),
    )

    result = orchestrator.run_scene("CH100_SC01")
    session.commit()

    llm_calls = session.execute(select(LlmCall).order_by(LlmCall.created_at.asc(), LlmCall.llm_call_id.asc())).scalars().all()
    llm_calls_by_step = {llm_call.step: llm_call for llm_call in llm_calls}
    neutral_llm_call = llm_calls_by_step["neutral_draft"]
    style_llm_call = llm_calls_by_step["style_draft"]
    bundle = session.execute(select(SceneBundle)).scalars().one()
    neutral_draft = session.execute(
        select(SceneDraft).where(SceneDraft.stage == "neutral_draft")
    ).scalars().one()
    style_draft = session.execute(
        select(SceneDraft).where(SceneDraft.stage == "style_draft")
    ).scalars().one()
    attempt = session.execute(
        select(AttemptTracker).where(AttemptTracker.step == "neutral_draft")
    ).scalars().one()
    final_scene = session.execute(select(FinalScene)).scalars().one()
    state = session.get(SceneRunState, "CH100_SC01")
    soft_qc = result["soft_qc"]

    assert len(fake_client.requests) == 2
    request = fake_client.requests[0]
    assert request.response_format == "json_object"
    assert request.response_schema == {
        "name": "neutral_draft",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["scene_text"],
            "properties": {
                "scene_text": {"type": "string"},
                "continuity_notes": {"type": "array", "items": {"type": "string"}},
            },
        },
    }
    assert request.node_id == "neutral_draft"
    assert request.reasoning_level == "medium"
    assert any("Scene ID: CH100_SC01" in message["content"] for message in request.messages)
    assert any("Return JSON that matches the structured schema exactly." in message["content"] for message in request.messages)
    style_request = fake_client.requests[1]
    assert style_request.model == "gpt-5"
    assert style_request.node_id == "style_draft"
    assert style_request.response_schema == {
        "name": "style_draft",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["scene_text"],
            "properties": {
                "scene_text": {"type": "string"},
                "style_notes": {"type": "array", "items": {"type": "string"}},
            },
        },
    }
    assert style_request.reasoning_level == "medium"
    assert any("Approved Neutral Draft" in message["content"] for message in style_request.messages)
    assert any("Provider-generated neutral scene text." in message["content"] for message in style_request.messages)
    assert any("Rewrite the scene draft with stronger style adherence" in message["content"] for message in style_request.messages)
    assert sum(message["content"].count("Return JSON that matches the structured schema exactly.") for message in style_request.messages) == 1

    assert neutral_draft.content == "Provider-generated neutral scene text."
    assert "Clocktower Roof" not in neutral_draft.content
    assert neutral_draft.generation_llm_call_id == neutral_llm_call.llm_call_id
    assert neutral_draft.source_bundle_id == bundle.bundle_id
    assert neutral_draft.source_bundle_hash == bundle.bundle_snapshot_hash
    assert style_draft.content == "Provider-generated style scene text."
    assert style_draft.generation_llm_call_id == style_llm_call.llm_call_id
    assert style_draft.source_bundle_id == bundle.bundle_id
    assert style_draft.source_bundle_hash == bundle.bundle_snapshot_hash

    assert {"neutral_draft", "hard_qc", "style_draft", "soft_qc"}.issubset(llm_calls_by_step)
    assert neutral_llm_call.provider == "fake-provider"
    assert neutral_llm_call.node_id == "neutral_draft"
    assert neutral_llm_call.reasoning_level == "medium"
    assert neutral_llm_call.model == "fake-neutral-model"
    assert neutral_llm_call.step == "neutral_draft"
    assert neutral_llm_call.scene_id == "CH100_SC01"
    assert neutral_llm_call.chapter_id == "CH100"
    assert neutral_llm_call.prompt_hash
    assert neutral_llm_call.prompt_tokens == 111
    assert neutral_llm_call.completion_tokens == 29
    assert neutral_llm_call.total_tokens == 140
    assert neutral_llm_call.finish_reason == "stop"
    assert neutral_llm_call.error_code is None
    assert neutral_llm_call.request_payload_summary["token_budget"]["estimated_input_tokens"] == sum(
        estimate_tokens(message["content"]) for message in request.messages
    )
    assert style_llm_call.provider == "fake-provider"
    assert style_llm_call.node_id == "style_draft"
    assert style_llm_call.reasoning_level == "medium"
    assert style_llm_call.model == "fake-style-model"
    assert style_llm_call.step == "style_draft"
    assert style_llm_call.scene_id == "CH100_SC01"
    assert style_llm_call.chapter_id == "CH100"
    assert style_llm_call.prompt_hash
    assert style_llm_call.prompt_tokens == 121
    assert style_llm_call.completion_tokens == 33
    assert style_llm_call.total_tokens == 154
    assert style_llm_call.finish_reason == "stop"
    assert style_llm_call.error_code is None
    assert style_llm_call.request_payload_summary["token_budget"]["estimated_input_tokens"] == sum(
        estimate_tokens(message["content"]) for message in style_request.messages
    )

    assert attempt.source_bundle_id == bundle.bundle_id
    assert attempt.details_json == {"row_id": neutral_draft.row_id, "llm_call_id": neutral_llm_call.llm_call_id}
    assert state.current_neutral_draft_row_id == neutral_draft.row_id
    assert state.current_bundle_id == bundle.bundle_id
    assert state.current_bundle_hash == bundle.bundle_snapshot_hash
    assert state.current_style_draft_row_id == style_draft.row_id
    assert state.total_attempt_count == 1
    assert final_scene.source_bundle_id == bundle.bundle_id
    assert final_scene.source_bundle_hash == bundle.bundle_snapshot_hash
    assert final_scene.content == style_draft.content
    assert final_scene.generation_llm_call_id == style_draft.generation_llm_call_id
    assert style_draft.content != neutral_draft.content

    assert result["current_bundle_id"] == bundle.bundle_id
    assert result["current_bundle_hash"] == bundle.bundle_snapshot_hash
    assert soft_qc["branch"] == "continue"


def test_scene_generation_does_not_append_required_scene_text_when_provider_omits_it(session) -> None:
    _seed_scene(session)
    bundle = {
        "bundle_id": "bundle_CH100_SC01",
        "bundle_snapshot_hash": "bundle_hash_demo",
        "snapshot": {
            "scene_id": "CH100_SC01",
            "chapter_id": "CH100",
            "inline_digests": {"scene_card": "Force both characters to reveal what they know."},
        },
    }
    service = SceneGenerationService(session, llm_client=FakeSceneClient())

    neutral = service.generate_neutral_draft("CH100_SC01", bundle)

    assert neutral.content == "Provider-generated neutral scene text."


def test_bundle_and_style_prompt_include_only_approved_runtime_author_preference(session) -> None:
    _seed_scene(session)
    session.add(
        AuthorPreferenceProfile(
            profile_id="author_pref_draft_ignored",
            scope_type="global",
            scope_ref_id="global",
            status="draft",
            runtime_eligible=0,
            summary_json={"preferred_revision_moves": ["draft preference should stay out of runtime prompts"]},
            source_patch_ids_json=[],
        )
    )
    session.add(
        AuthorPreferenceProfile(
            profile_id="author_pref_approved_runtime",
            scope_type="global",
            scope_ref_id="global",
            status="approved",
            runtime_eligible=1,
            summary_json={
                "preferred_revision_moves": ["sharper rhetorical questions"],
                "rejected_revision_moves": ["expository dialogue"],
                "ai_trace_terms_to_watch": ["somehow meaningful"],
            },
            source_patch_ids_json=["patch_runtime_pref"],
        )
    )
    session.commit()

    bundle = BundleBuilder(session).build("CH100_SC01")
    snapshot = bundle["snapshot"]

    assert snapshot["source_version_refs"]["author_preference_profile_id"] == "author_pref_approved_runtime"
    assert "author_preference_profile" in snapshot["inline_digests"]
    assert "sharper rhetorical questions" in snapshot["inline_digests"]["author_preference_profile"]
    assert "draft preference should stay out" not in snapshot["inline_digests"]["author_preference_profile"]

    fake_client = FakeSceneClient()
    request = SceneGenerationService(session, llm_client=fake_client).generate_style_draft(
        "CH100_SC01",
        bundle,
        neutral_draft_row_id="draft_neutral_CH100_SC01",
        neutral_content="Approved neutral draft.",
    )

    style_prompt = fake_client.requests[0].messages[1]["content"]
    assert "sharper rhetorical questions" in style_prompt
    assert "expository dialogue" in style_prompt
    assert "draft preference should stay out" not in style_prompt
    style_call = session.get(LlmCall, request.llm_call_id)
    assert style_call is not None
    prompt_summary = style_call.request_payload_summary or {}
    assert "author_preference_profile" in prompt_summary["token_budget"]["included_sections"]


def test_generate_style_draft_runs_one_de_template_pass_for_high_risk_anti_template(session) -> None:
    _seed_scene(session)
    bundle = {
        "bundle_id": "bundle_CH100_SC01",
        "bundle_snapshot_hash": "bundle_hash_demo",
        "snapshot": {"scene_id": "CH100_SC01", "chapter_id": "CH100", "inline_digests": {"scene_card": "Goal"}},
    }
    fake_client = FakeDeTemplateClient()

    result = SceneGenerationService(session, llm_client=fake_client).generate_style_draft(
        "CH100_SC01",
        bundle,
        neutral_draft_row_id="draft_neutral_CH100_SC01",
        neutral_content="Approved neutral draft.",
    )

    assert len(fake_client.requests) == 2
    assert fake_client.requests[1].node_id == "style_patch"
    assert "De-template Rewrite Brief" in fake_client.requests[1].messages[1]["content"]
    assert "quality:scene:CH100_SC01:template_action_reuse" in fake_client.requests[1].messages[1]["content"]

    drafts = session.execute(select(SceneDraft).order_by(SceneDraft.created_at.asc(), SceneDraft.row_id.asc())).scalars().all()
    assert [draft.stage for draft in drafts] == ["style_draft", "de_template"]
    assert drafts[0].content.startswith("她低头看着钥匙")
    assert drafts[1].content == result.content
    assert result.row_id == drafts[1].row_id

    llm_calls_by_step = {
        row.step: row for row in session.execute(select(LlmCall).order_by(LlmCall.created_at.asc())).scalars().all()
    }
    assert set(llm_calls_by_step) == {"style_draft", "de_template"}
    assert llm_calls_by_step["de_template"].node_id == "style_patch"

    attempts = {
        row.step: row for row in session.execute(select(AttemptTracker).order_by(AttemptTracker.created_at.asc())).scalars().all()
    }
    assert attempts["de_template"].details_json["quality_gate"]["triggered"] is True
    assert attempts["de_template"].details_json["quality_gate"]["rewrite_pass"] == 1
    assert session.get(SceneRunState, "CH100_SC01").current_style_draft_row_id == drafts[1].row_id


def test_generate_style_draft_blocks_provider_when_scene_must_split(session) -> None:
    _seed_scene(session)
    fake_client = FakeSceneClient()
    service = SceneGenerationService(session, llm_client=fake_client)

    class StubPromptBuilder:
        def build(self, *_args, **_kwargs):
            return {
                "template_name": "style_draft",
                "template_version": "test",
                "system_prompt": "system",
                "user_prompt": "user\n\nReturn JSON that matches the structured schema exactly.",
                "structured_schema": {},
                "prompt_hash": "prompt_hash_style_split",
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

    service._prompt_builder_instance = StubPromptBuilder()
    bundle = {
        "bundle_id": "bundle_CH100_SC01",
        "bundle_snapshot_hash": "bundle_hash_demo",
        "snapshot": {"scene_id": "CH100_SC01", "chapter_id": "CH100", "inline_digests": {"scene_card": "Goal"}},
    }

    with pytest.raises(DomainError) as exc:
        service.generate_style_draft(
            "CH100_SC01",
            bundle,
            neutral_draft_row_id="draft_neutral_CH100_SC01",
            neutral_content=" ".join(["oversized neutral draft"] * 80),
        )

    assert exc.value.code == "CONTINUITY_BUDGET_EXCEEDED"
    assert fake_client.requests == []

    llm_call = session.execute(select(LlmCall).where(LlmCall.step == "style_draft")).scalars().one()
    attempt = session.execute(select(AttemptTracker).where(AttemptTracker.step == "style_draft")).scalars().one()

    assert llm_call.error_code == "CONTINUITY_BUDGET_EXCEEDED"
    assert llm_call.request_payload_summary["continuity_warning"]["requires_scene_split"] is True
    assert attempt.status == "failed"


def test_generate_neutral_draft_records_failed_attempt_and_bumps_counter(session) -> None:
    _seed_scene(session)
    bundle = {"bundle_id": "bundle_CH100_SC01", "bundle_snapshot_hash": "bundle_hash_demo", "snapshot": {"scene_id": "CH100_SC01", "chapter_id": "CH100", "inline_digests": {"scene_card": "Force both characters to reveal what they know."}}}
    service = SceneGenerationService(session, llm_client=FakeFailingClient())

    state = session.get(SceneRunState, "CH100_SC01")
    state.current_bundle_id = bundle["bundle_id"]
    state.current_bundle_hash = bundle["bundle_snapshot_hash"]
    session.commit()

    try:
        service.generate_neutral_draft("CH100_SC01", bundle)
    except ValueError as exc:
        assert str(exc) == "malformed provider payload"
    else:
        raise AssertionError("expected generation failure")

    session.commit()

    llm_call = session.execute(select(LlmCall)).scalars().one()
    attempt = session.execute(select(AttemptTracker).where(AttemptTracker.step == "neutral_draft")).scalars().one()
    state = session.get(SceneRunState, "CH100_SC01")

    assert llm_call.error_code == "ValueError"
    assert attempt.status == "failed"
    assert attempt.source_bundle_id == bundle["bundle_id"]
    assert attempt.details_json["error_code"] == "ValueError"
    assert attempt.details_json["llm_call_id"] == llm_call.llm_call_id
    assert state.total_attempt_count == 1
    assert state.current_bundle_id == bundle["bundle_id"]
    assert state.current_bundle_hash == bundle["bundle_snapshot_hash"]
    assert state.current_neutral_draft_row_id is None


def test_run_scene_records_neutral_prompt_builder_failure_and_clears_stale_state(session, monkeypatch) -> None:
    _seed_scene(session)
    _seed_scene_blueprint(session)
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "false")
    monkeypatch.delenv("NOVEL_SYSTEM_LLM_API_KEY", raising=False)
    monkeypatch.delenv("NOVEL_SYSTEM_LLM_BASE_URL", raising=False)

    state = session.get(SceneRunState, "CH100_SC01")
    state.current_neutral_draft_row_id = "stale_neutral"
    state.current_qc_report_id = "stale_qc"
    state.soft_patch_count = 1
    session.commit()

    def failing_prompt_builder(self):
        raise PromptConfigurationError("prompts config missing")

    monkeypatch.setattr(SceneGenerationService, "_prompt_builder", failing_prompt_builder)

    orchestrator = Orchestrator(session)
    with pytest.raises(PromptConfigurationError):
        orchestrator.run_scene("CH100_SC01")
    session.commit()

    llm_call = session.execute(select(LlmCall)).scalars().one()
    attempt = session.execute(select(AttemptTracker).where(AttemptTracker.step == "neutral_draft")).scalars().one()
    state = session.get(SceneRunState, "CH100_SC01")

    assert llm_call.step == "neutral_draft"
    assert llm_call.error_code == "PromptConfigurationError"
    assert attempt.status == "failed"
    assert state.current_neutral_draft_row_id is None
    assert state.current_qc_report_id is None
    assert state.soft_patch_count == 0


def test_run_scene_records_style_routing_failure(session, monkeypatch) -> None:
    _seed_scene(session)
    _seed_scene_blueprint(session)
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "false")
    monkeypatch.delenv("NOVEL_SYSTEM_LLM_API_KEY", raising=False)
    monkeypatch.delenv("NOVEL_SYSTEM_LLM_BASE_URL", raising=False)

    class FakeRoutingConfig:
        def __init__(self) -> None:
            self.task_routing = {
                "neutral_draft": type(
                    "TaskConfig",
                    (),
                    {
                        "provider": "offline_deterministic",
                        "model": "offline-neutral",
                        "temperature": 0.6,
                        "max_output_tokens": 6000,
                        "response_format": "json_object",
                    },
                )(),
                "hard_qc": type(
                    "TaskConfig",
                    (),
                    {
                        "provider": "offline_deterministic",
                        "model": "offline-hard-qc",
                        "temperature": 0.0,
                        "max_output_tokens": 4000,
                        "response_format": "json_object",
                    },
                )(),
            }

    monkeypatch.setattr(
        "novel_system.services.llm_task_runner.load_model_routing_config",
        lambda: FakeRoutingConfig(),
    )

    orchestrator = Orchestrator(session)
    with pytest.raises(KeyError):
        orchestrator.run_scene("CH100_SC01")
    session.commit()

    llm_calls = session.execute(
        select(LlmCall).order_by(LlmCall.created_at.asc(), LlmCall.llm_call_id.asc())
    ).scalars().all()
    attempt = session.execute(select(AttemptTracker).where(AttemptTracker.step == "style_draft")).scalars().one()
    state = session.get(SceneRunState, "CH100_SC01")

    assert [llm_call.step for llm_call in llm_calls] == ["neutral_draft", "hard_qc", "style_draft"]
    assert llm_calls[-1].error_code == "KeyError"
    assert attempt.status == "failed"
    assert attempt.details_json["llm_call_id"] == llm_calls[-1].llm_call_id
    assert attempt.details_json["error_code"] == "KeyError"
    assert state.current_style_draft_row_id is None


def test_run_scene_uses_offline_fallback_when_llm_disabled(session, monkeypatch) -> None:
    _seed_scene(session)
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "false")
    monkeypatch.delenv("NOVEL_SYSTEM_LLM_API_KEY", raising=False)
    monkeypatch.delenv("NOVEL_SYSTEM_LLM_BASE_URL", raising=False)

    orchestrator = Orchestrator(session)
    result = orchestrator.run_scene("CH100_SC01")
    session.commit()

    llm_calls = session.execute(
        select(LlmCall).order_by(LlmCall.created_at.asc(), LlmCall.llm_call_id.asc())
    ).scalars().all()
    llm_calls_by_step = {llm_call.step: llm_call for llm_call in llm_calls}
    neutral_llm_call = llm_calls_by_step["neutral_draft"]
    style_llm_call = llm_calls_by_step["style_draft"]
    neutral_draft = session.execute(
        select(SceneDraft).where(SceneDraft.stage == "neutral_draft")
    ).scalars().one()
    style_draft = session.execute(
        select(SceneDraft).where(SceneDraft.stage == "style_draft")
    ).scalars().one()
    final_scene = session.execute(select(FinalScene)).scalars().one()

    assert {"neutral_draft", "hard_qc", "style_draft", "soft_qc"}.issubset(llm_calls_by_step)
    assert all(llm_call.provider == "offline_deterministic" for llm_call in llm_calls)
    assert all(llm_call.finish_reason == "offline_fallback" for llm_call in llm_calls)
    assert neutral_draft.content.startswith(
        "Offline neutral draft for CH100_SC01. The scene advances clearly, preserves continuity, "
        "and satisfies the compiled bundle constraints."
    )
    assert "A red envelope changes hands." not in neutral_draft.content
    assert "Clocktower Roof" not in neutral_draft.content
    assert neutral_draft.generation_llm_call_id == neutral_llm_call.llm_call_id
    assert style_draft.content != neutral_draft.content
    assert style_draft.generation_llm_call_id == style_llm_call.llm_call_id
    assert final_scene.content == style_draft.content
    assert final_scene.generation_llm_call_id == style_draft.generation_llm_call_id
    assert result["current_bundle_id"]
