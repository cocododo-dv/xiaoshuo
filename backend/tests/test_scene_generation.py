from __future__ import annotations

import logging

import pytest
from sqlalchemy import select

from novel_system.db.models import (
    AttemptTracker,
    AuthorPreferenceProfile,
    ChapterGoal,
    ChapterState,
    FinalScene,
    GenerationPlanningArtifact,
    LlmCall,
    RelationProfile,
    SceneBlueprint,
    SceneBundle,
    SceneCard,
    SceneDraft,
    SceneRunState,
    StoryProject,
    VoiceProfile,
)
from novel_system.services.bundle_builder import BundleBuilder
from novel_system.services.errors import DomainError
from novel_system.services.context_budget import estimate_tokens
from novel_system.services.llm_client import LLMRequest, LLMResponse
from novel_system.services.near_final import (
    CHAPTER_ARCHITECTURE_ARTIFACT,
    CHARACTER_PRESSURE_ARTIFACT,
    NearFinalAcceptanceService,
    NearFinalPlanningService,
)
from novel_system.services.prompt_builder import PromptConfigurationError
from novel_system.services.orchestrator import Orchestrator
from novel_system.services.qc_engine import HardQcEngine, SoftQcEngine
from novel_system.services.scene_blueprint import SceneBlueprintService
from novel_system.services.scene_generation import SceneGenerationService, StyleGenerationResult
from tests.accounted_llm_fakes import AccountedGenerateMixin
from tests.real_llm_fakes import ScenePipelineOnlineFake


class FakeSceneClient(AccountedGenerateMixin):
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


class FakeFailingClient(AccountedGenerateMixin):
    def generate(self, request: LLMRequest) -> LLMResponse:
        raise ValueError("malformed provider payload")


class FakeDeTemplateClient(AccountedGenerateMixin):
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


def _seed_scene(session, *, must_include_text: str | None = "A red envelope changes hands.") -> None:
    session.add(StoryProject(project_id="PROJECT100", title="Scene generation", outline_text=""))
    session.add(
        ChapterGoal(
            chapter_id="CH100",
            project_id="PROJECT100",
            planned_scene_count=1,
            chapter_goal="A reunion turns dangerous.",
        )
    )
    session.add(ChapterState(chapter_id="CH100", current_phase="drafting"))
    session.add(
        SceneCard(
            scene_id="CH100_SC01",
            project_id="PROJECT100",
            chapter_id="CH100",
            scene_seq=1,
            pov_character_id="CHAR_A",
            onstage_chars_json=["CHAR_A", "CHAR_B"],
            location="Clocktower Roof",
            scene_goal="Force both characters to reveal what they know.",
            beats_json=["arrival", "reveal", "standoff"],
            must_include_text=must_include_text,
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


def _seed_scene_planning(session) -> None:
    """预置章级架构 + 角色压力规划产物（status=active），让编排复用而非联网生成。

    这样 scene_blueprint（另由 _seed_scene_blueprint 预置）与规划两步都被跳过、
    不产生 LLM 调用，测试才能干净地落到 neutral_draft 的目标失败点。"""
    session.add(
        GenerationPlanningArtifact(
            row_id="planning_chapter_arch_CH100_seed",
            artifact_type=CHAPTER_ARCHITECTURE_ARTIFACT,
            object_type="chapter",
            object_id="CH100",
            chapter_id="CH100",
            payload_json={
                "chapter_promise": "the scene must change the available choices",
                "escalation_path": ["pressure appears", "a choice narrows", "a cost lands"],
                "reveal_plan": ["the governing constraint is exposed"],
                "payoff_target": "the chosen action creates the next problem",
                "character_shift": "certainty gives way to costly resolve",
                "ending_question": "what will the choice cost next",
            },
            status="active",
        )
    )
    session.add(
        GenerationPlanningArtifact(
            row_id="planning_char_pressure_CH100_SC01_seed",
            artifact_type=CHARACTER_PRESSURE_ARTIFACT,
            object_type="scene",
            object_id="CH100_SC01",
            chapter_id="CH100",
            scene_id="CH100_SC01",
            payload_json={
                "surface_goal": "finish the immediate task",
                "hidden_fear": "the choice will expose a weakness",
                "wrong_belief": "control can prevent every loss",
                "shame_point": "asking for help feels like surrender",
                "avoidance_strategy": "delay the irreversible choice",
                "relationship_debt": "an old promise remains unpaid",
                "current_mask": "measured confidence",
            },
            status="active",
        )
    )
    session.commit()


def test_run_scene_persists_provider_neutral_draft_and_bundle_linkage(session) -> None:
    # This test isolates persistence/lineage. Continuity blocking for a missing
    # must-include fact is exercised explicitly by the offline test below.
    _seed_scene(session, must_include_text=None)
    fake_client = FakeSceneClient()
    support = ScenePipelineOnlineFake()

    orchestrator = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=fake_client),
        hard_qc_engine=HardQcEngine(session, llm_client=support),
        soft_qc_engine=SoftQcEngine(session, llm_client=support),
        planning_service=NearFinalPlanningService(session, llm_client=support),
        near_final_service=NearFinalAcceptanceService(session, llm_client=support),
    )
    orchestrator.scene_blueprint_service = SceneBlueprintService(session, llm_client=support)

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
    assert any("Rewrite the supplied source draft" in message["content"] for message in style_request.messages)
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


def test_author_instruction_is_frozen_into_bundle_and_reaches_neutral_prompt(session) -> None:
    _seed_scene(session)
    note = "把选择提前到第一段，结尾不要解释。"
    bundle = BundleBuilder(session).build("CH100_SC01", author_note=note)

    snapshot = bundle["snapshot"]
    assert snapshot["inline_digests"]["author_instruction"] == note
    assert snapshot["source_version_refs"]["author_instruction_hash"]
    assert any(
        item["slot"] == "author_instruction"
        for item in snapshot["ordered_injections"]
    )

    fake_client = FakeSceneClient()
    SceneGenerationService(session, llm_client=fake_client).generate_neutral_draft(
        "CH100_SC01",
        bundle,
        author_note=note,
    )
    prompt_text = "\n".join(message["content"] for message in fake_client.requests[0].messages)
    assert note in prompt_text


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


class _FakeBestOfNDeTemplateClient(AccountedGenerateMixin):
    """每个候选的 style 稿都返回触发反模板闸的模板文本，去模板稿返回各异的清理文本。"""

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self._style_n = 0
        self._patch_n = 0

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if request.node_id == "style_patch":
            self._patch_n += 1
            structured_output = {
                "scene_text": (
                    f"清理稿{self._patch_n}：她把钥匙扣进掌心，拔掉录音线；门缝里的光灭了，"
                    f"走廊尽头响起第{self._patch_n}声敲门，她没有回头。"
                ),
                "style_notes": ["removed repeated action template"],
            }
            request_id = f"resp_fake_de_template_{self._patch_n}"
            model = "fake-patch-model"
        else:
            self._style_n += 1
            structured_output = {
                "scene_text": (
                    "她低头看着钥匙，沉默了片刻。"
                    "他低头看着录音，沉默了片刻。"
                    "她低头看着门缝，沉默了片刻。"
                    f"她知道真相必须公开。候选{self._style_n}。"
                ),
                "style_notes": ["kept an unsafe template"],
            }
            request_id = f"resp_fake_style_template_{self._style_n}"
            model = "fake-style-model"
        return LLMResponse(
            request_id=request_id,
            provider="fake-provider",
            model=model,
            text=__import__("json").dumps(structured_output),
            structured_output=structured_output,
            response_format="json_object",
            raw_response={"id": request_id, "model": model, "usage": {}, "finish_reason": "stop"},
            usage={"input_tokens": 80, "output_tokens": 30, "total_tokens": 110},
            finish_reason="stop",
        )


def test_best_of_n_multiple_candidates_de_template_no_pk_collision(session) -> None:
    """QA3 回归：Best-of-N 下 ≥2 个候选都触发去模板时，去模板稿 row_id 必须互异，
    不得因共用 row_id 撞 SceneDraft 主键抛 IntegrityError 致整跑崩溃。"""
    _seed_scene(session)
    bundle = {
        "bundle_id": "bundle_CH100_SC01",
        "bundle_snapshot_hash": "bundle_hash_demo",
        "snapshot": {"scene_id": "CH100_SC01", "chapter_id": "CH100", "inline_digests": {"scene_card": "Goal"}},
    }
    fake_client = _FakeBestOfNDeTemplateClient()

    # 修复前：第二个候选的去模板稿与第一个共用 row_id → flush 抛 IntegrityError。
    results = SceneGenerationService(session, llm_client=fake_client).generate_style_draft_candidates(
        "CH100_SC01",
        bundle,
        neutral_draft_row_id="draft_neutral_CH100_SC01",
        neutral_content="Approved neutral draft.",
        n_candidates=2,
    )
    assert results, "应至少产出一个候选"

    de_template_drafts = session.execute(
        select(SceneDraft).where(SceneDraft.stage == "de_template")
    ).scalars().all()
    assert len(de_template_drafts) >= 2, f"应有 ≥2 条去模板稿(每候选一条)，实得 {len(de_template_drafts)}"
    row_ids = [d.row_id for d in de_template_drafts]
    assert len(set(row_ids)) == len(row_ids), f"去模板稿 row_id 必须互异，实得 {row_ids}"


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
    _seed_scene_planning(session)
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
    _seed_scene_planning(session)
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

    support = ScenePipelineOnlineFake()
    orchestrator = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=support),
        hard_qc_engine=HardQcEngine(session, llm_client=support),
    )
    with pytest.raises(KeyError):
        orchestrator.run_scene("CH100_SC01")
    session.commit()

    llm_calls = session.execute(
        select(LlmCall).order_by(LlmCall.created_at.asc(), LlmCall.llm_call_id.asc())
    ).scalars().all()
    attempt = session.execute(select(AttemptTracker).where(AttemptTracker.step == "style_draft")).scalars().one()
    state = session.get(SceneRunState, "CH100_SC01")

    assert [llm_call.step for llm_call in llm_calls] == ["neutral_draft", "hard_qc", "style_draft"]
    # 缺路由统一为引导性错误码(原为裸 "KeyError");原始 KeyError 仍向上抛(见 raises)
    assert llm_calls[-1].error_code == "LLM_ROUTE_NOT_CONFIGURED"
    assert attempt.status == "failed"
    assert attempt.details_json["llm_call_id"] == llm_calls[-1].llm_call_id
    assert attempt.details_json["error_code"] == "LLM_ROUTE_NOT_CONFIGURED"
    assert state.current_style_draft_row_id is None


def test_online_draft_keeps_drafts_but_cannot_archive_missing_required_fact(session) -> None:
    # 离线确定性生成已退役：接入在线记账替身后草稿照常生成，但缺失必含事实时
    # 最终文本闸门仍拦住归档（FINAL_TEXT_CONTINUITY_BLOCKED），草稿与准定稿保留。
    _seed_scene(session)
    support = ScenePipelineOnlineFake()

    orchestrator = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=support),
        hard_qc_engine=HardQcEngine(session, llm_client=support),
        soft_qc_engine=SoftQcEngine(session, llm_client=support),
        planning_service=NearFinalPlanningService(session, llm_client=support),
        near_final_service=NearFinalAcceptanceService(session, llm_client=support),
    )
    orchestrator.scene_blueprint_service = SceneBlueprintService(session, llm_client=support)
    with pytest.raises(DomainError) as blocked:
        orchestrator.run_scene("CH100_SC01")
    assert blocked.value.code == "FINAL_TEXT_CONTINUITY_BLOCKED"
    assert "continuity:missing_required_text" in blocked.value.details["final_text_gate"]["archive_blockers"]
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
    assert final_scene.status == "near_final_ready"

    assert {"neutral_draft", "hard_qc", "style_draft", "soft_qc"}.issubset(llm_calls_by_step)
    assert all(llm_call.provider == "test-online-provider" for llm_call in llm_calls)
    assert all(llm_call.finish_reason == "stop" for llm_call in llm_calls)
    assert neutral_draft.content.startswith("Accounted online test draft")
    assert "A red envelope changes hands." not in neutral_draft.content
    assert "Clocktower Roof" not in neutral_draft.content
    assert neutral_draft.generation_llm_call_id == neutral_llm_call.llm_call_id
    assert style_draft.content != neutral_draft.content
    assert style_draft.generation_llm_call_id == style_llm_call.llm_call_id
    assert final_scene.content == style_draft.content


def test_generate_style_draft_candidates_returns_sorted_list(session) -> None:
    _seed_scene(session)
    fake_client = FakeSceneClient()
    service = SceneGenerationService(session, llm_client=fake_client)
    bundle_builder = BundleBuilder(session)
    bundle = bundle_builder.build("CH100_SC01")

    neutral = service.generate_neutral_draft("CH100_SC01", bundle)
    candidates = service.generate_style_draft_candidates(
        "CH100_SC01",
        bundle,
        neutral_draft_row_id=neutral.row_id,
        neutral_content=neutral.content,
        n_candidates=3,
    )
    session.commit()

    assert len(candidates) >= 1
    assert all(isinstance(c, StyleGenerationResult) for c in candidates)
    assert all(c.content for c in candidates)

    attempts = session.execute(
        select(AttemptTracker).where(AttemptTracker.step == "style_draft")
    ).scalars().all()
    candidate_indices = [a.details_json.get("candidate_index") for a in attempts if a.details_json.get("candidate_index") is not None]
    assert len(candidate_indices) >= 1

    state = session.get(SceneRunState, "CH100_SC01")
    assert state.current_style_draft_row_id == candidates[0].row_id


def test_candidate_ranking_records_expected_quality_strategy_degradation(
    session,
    monkeypatch,
    caplog,
) -> None:
    from novel_system.services.quality_strategy import QualityStrategyResolver

    _seed_scene(session)
    service = SceneGenerationService(session, llm_client=FakeSceneClient())
    bundle = BundleBuilder(session).build("CH100_SC01")
    neutral = service.generate_neutral_draft("CH100_SC01", bundle)

    def fail_with_domain_error(_resolver, _scene):
        raise DomainError("QUALITY_POLICY_EVIDENCE_INVALID", "invalid evidence", 409)

    monkeypatch.setattr(QualityStrategyResolver, "resolve_for_scene", fail_with_domain_error)
    with caplog.at_level(logging.WARNING, logger="novel_system.services.scene_generation"):
        candidates = service.generate_style_draft_candidates(
            "CH100_SC01",
            bundle,
            neutral_draft_row_id=neutral.row_id,
            neutral_content=neutral.content,
            n_candidates=1,
        )

    assert candidates
    attempt = session.execute(
        select(AttemptTracker).where(
            AttemptTracker.scene_id == "CH100_SC01",
            AttemptTracker.step == "style_draft",
        )
    ).scalars().one()
    assert attempt.details_json["quality_strategy"] == {
        "status": "degraded",
        "matched_policy_id": None,
        "error_code": "QUALITY_POLICY_EVIDENCE_INVALID",
        "fallback": "project_or_builtin_weights",
    }
    assert "quality strategy ranking degraded" in caplog.text


def test_candidate_ranking_does_not_hide_unexpected_strategy_errors(
    session,
    monkeypatch,
) -> None:
    from novel_system.services.quality_strategy import QualityStrategyResolver

    _seed_scene(session)
    service = SceneGenerationService(session, llm_client=FakeSceneClient())
    bundle = BundleBuilder(session).build("CH100_SC01")
    neutral = service.generate_neutral_draft("CH100_SC01", bundle)

    def fail_with_programming_error(_resolver, _scene):
        raise RuntimeError("resolver implementation bug")

    monkeypatch.setattr(QualityStrategyResolver, "resolve_for_scene", fail_with_programming_error)
    with pytest.raises(RuntimeError, match="resolver implementation bug"):
        service.generate_style_draft_candidates(
            "CH100_SC01",
            bundle,
            neutral_draft_row_id=neutral.row_id,
            neutral_content=neutral.content,
            n_candidates=1,
        )


def test_adversarial_rank_score_lower_for_ai_heavy_text() -> None:
    from novel_system.services.literary_quality import adversarial_rank_score

    clean_text = (
        "She opened the door. He must choose the archive or save the child. "
        "The cost was his position. He left."
    )
    ai_heavy_text = (
        "She suddenly realized the moon was somehow meaningful. "
        "Everything changed forever. As if fate."
    )
    assert adversarial_rank_score(clean_text) > adversarial_rank_score(ai_heavy_text)


def test_candidate_dispersion_detects_identical_vs_diverse() -> None:
    from novel_system.services.literary_quality import candidate_dispersion

    same = ["She opened the door." * 3, "She opened the door." * 3]
    assert candidate_dispersion(same) == 0.0

    diverse = [
        "She ran through the fog, choosing to reveal the hidden letters.",
        "He opened the safe and left the key on the windowsill.",
    ]
    assert candidate_dispersion(diverse) > 0.0
