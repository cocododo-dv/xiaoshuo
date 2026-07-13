"""Wave 3（结果闭环治理 §4.6/§5.5/§5.8/§7.12）：场景 token 预算（5× 单发基线）。

- run 启动时确立 `scene_token_budget = 5 × 单发基线`（已设不覆盖、从不收缩）；
- 凡带 scene_id 的 LLM 调用（成功/失败）累计 `scene_tokens_used`；
- 预算按场景生命周期累计，重跑不重置（§7.12：自动流程不得重置）；
- 预算耗尽只拦「可选支出」（补候选/批判/补丁），不撤销已有正文；
- 扩容唯一入口是作者显式 topup（留审计）。
"""

from __future__ import annotations

import json
import inspect

from sqlalchemy import select

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    LlmCall,
    OperationLog,
    RelationProfile,
    SceneCard,
    SceneDraft,
    SceneRunState,
    VoiceProfile,
)
from novel_system.services.llm_client import LLMRequest, LLMResponse
from novel_system.services.orchestrator import Orchestrator
from novel_system.services.qc_engine import HardQcEngine, SoftQcEngine
from novel_system.services.scene_budget import can_spend, ensure_budget
from novel_system.services.scene_generation import SceneGenerationService

SCENE_ID = "CH400_SC01"
CHAPTER_ID = "CH400"
CALL_TOKENS = 78


def _response(payload: dict, *, request_id: str) -> LLMResponse:
    return LLMResponse(
        request_id=request_id,
        provider="fake-provider",
        model="fake-model",
        text=json.dumps(payload, ensure_ascii=False),
        structured_output=payload,
        response_format="json_object",
        raw_response={"id": request_id, "model": "fake-model", "usage": {"input_tokens": 60, "output_tokens": 18, "total_tokens": CALL_TOKENS}, "finish_reason": "stop"},
        usage={"input_tokens": 60, "output_tokens": 18, "total_tokens": CALL_TOKENS},
        finish_reason="stop",
    )


class CountingSceneClient:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return _response(
            {"scene_text": f"Provider-generated draft #{len(self.requests)}.", "continuity_notes": []},
            request_id=f"resp_scene_{len(self.requests):03d}",
        )


class CountingQcClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return _response(self.payload, request_id=f"resp_qc_{len(self.requests):03d}")


def _hard_pass() -> dict:
    return {"resolution_code": "hard_pass", "pass_flag": True, "next_action": "pass", "issues": [], "rewrite_brief": []}


def _soft_pass() -> dict:
    return {
        "resolution_code": "soft_pass",
        "pass_flag": True,
        "next_action": "pass",
        "issues": [],
        "rewrite_brief": [],
        "carry_forward_note": False,
        "note_scope": None,
        "carry_note_text": None,
    }


def _seed_scene(session) -> None:
    session.add(ChapterGoal(chapter_id=CHAPTER_ID, planned_scene_count=1, chapter_goal="Budgeted reunion."))
    session.add(ChapterState(chapter_id=CHAPTER_ID, current_phase="drafting"))
    session.add(
        SceneCard(
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            scene_seq=1,
            pov_character_id="CHAR_A",
            onstage_chars_json=["CHAR_A", "CHAR_B"],
            location="Harbor",
            scene_goal="Reveal the letter.",
            beats_json=["arrival", "reveal"],
            must_include_text="",
            target_length_band="short",
            scene_type="reunion",
            is_chapter_last=0,
        )
    )
    session.add(SceneRunState(scene_id=SCENE_ID, scene_status="ready"))
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


def _make_orchestrator(session, *, scene_client=None) -> Orchestrator:
    return Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=scene_client or CountingSceneClient()),
        hard_qc_engine=HardQcEngine(session, llm_client=CountingQcClient(_hard_pass())),
        soft_qc_engine=SoftQcEngine(session, llm_client=CountingQcClient(_soft_pass())),
    )


# ---------- 预算确立与累计 ----------

def test_run_establishes_budget_and_accumulates_usage(session) -> None:
    _seed_scene(session)
    result = _make_orchestrator(session).run_scene(SCENE_ID)
    session.commit()

    state = session.get(SceneRunState, SCENE_ID)
    assert result["scene_status"] == "archived"
    assert state.scene_token_budget and state.scene_token_budget > 0
    # 5× 单发基线（§4.6）：预算是基线的整 5 倍
    assert state.scene_token_budget % 5 == 0
    assert state.provider_attempt_budget == 32
    assert state.scene_budget_basis_json["provider_attempt_budget"] == {
        "config_key": "retry_budget.provider_attempt_budget",
        "value": 32,
    }
    # 场景内每次 LLM 调用（生成 + QC + near-final）都计入
    assert state.scene_tokens_used > 0
    assert state.scene_tokens_used % CALL_TOKENS == 0
    # 完成门：总消耗不超过 5× 基线
    assert state.scene_tokens_used <= state.scene_token_budget
    calls = session.execute(select(LlmCall)).scalars().all()
    assert calls
    assert {(call.scope_type, call.scope_id) for call in calls} == {("scene", SCENE_ID)}


def test_rerun_accumulates_and_never_resets(session) -> None:
    _seed_scene(session)
    orchestrator = _make_orchestrator(session)
    orchestrator.run_scene(SCENE_ID)
    session.commit()
    state = session.get(SceneRunState, SCENE_ID)
    first_used = state.scene_tokens_used
    first_budget = state.scene_token_budget

    _make_orchestrator(session).run_scene(SCENE_ID)
    session.commit()
    session.refresh(state)

    # §7.12：重跑不重置——生命周期累计；预算也不因重跑改变
    assert state.scene_tokens_used > first_used
    assert state.scene_token_budget == first_budget


def test_existing_budget_is_not_overwritten(session) -> None:
    _seed_scene(session)
    state = session.get(SceneRunState, SCENE_ID)
    state.scene_token_budget = 99999
    session.commit()

    _make_orchestrator(session).run_scene(SCENE_ID)
    session.commit()
    session.refresh(state)
    assert state.scene_token_budget == 99999


# ---------- can_spend / ensure_budget 纯函数 ----------

def test_can_spend_and_ensure_budget_semantics(session) -> None:
    _seed_scene(session)
    state = session.get(SceneRunState, SCENE_ID)

    assert "provider_attempt_budget" in inspect.signature(ensure_budget).parameters
    ensure_budget(state, 100, provider_attempt_budget=23)
    assert state.scene_token_budget == 500
    assert state.provider_attempt_budget == 23
    assert state.scene_budget_basis_json == {
        "baseline_tokens": 100,
        "budget_multiplier": 5,
        "scene_token_budget": 500,
        "provider_attempt_budget": {
            "config_key": "retry_budget.provider_attempt_budget",
            "value": 23,
        },
    }
    first_basis = dict(state.scene_budget_basis_json)
    ensure_budget(state, 999, provider_attempt_budget=99)  # 已设不覆盖
    assert state.scene_token_budget == 500
    assert state.provider_attempt_budget == 23
    assert state.scene_budget_basis_json == first_basis

    state.scene_tokens_used = 0
    assert can_spend(state, 500) is True
    state.scene_tokens_used = 401
    assert can_spend(state, 100) is False  # 预留不足 → 拒绝
    state.scene_token_budget = None
    assert can_spend(state, 10**9) is True  # 未初始化预算不拦（渐进迁移）


# ---------- 预算耗尽只拦可选支出 ----------

def test_exhausted_budget_skips_optional_spends_but_still_delivers(session) -> None:
    """预算耗尽：near-final 重写、批判、补丁等可选支出被跳过，正文照常交付。"""
    _seed_scene(session)
    state = session.get(SceneRunState, SCENE_ID)
    state.scene_token_budget = 1  # 立即耗尽
    session.commit()

    scene_client = CountingSceneClient()
    from novel_system.services.near_final import NearFinalAcceptanceService

    near_final_fail = {
        "near_final_status": "revision_required",
        "pass_flag": False,
        "overall_score": 0.4,
        "scores": {},
        "findings": [],
        "revision_brief": [{"dimension": "story_necessity", "action": "补足抉择", "priority": "high"}],
        "failure_class": "scene_structure_failure",
        "requires_human_review": False,
    }
    orchestrator = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=scene_client),
        hard_qc_engine=HardQcEngine(session, llm_client=CountingQcClient(_hard_pass())),
        soft_qc_engine=SoftQcEngine(session, llm_client=CountingQcClient(_soft_pass())),
        near_final_service=NearFinalAcceptanceService(
            session, llm_client=CountingQcClient(near_final_fail)
        ),
    )

    result = orchestrator.run_scene(SCENE_ID)
    session.commit()

    # near-final fail 但预算耗尽 → 不烧重写调用，直接交付最佳稿（§5.8 硬行为）
    assert result["scene_status"] == "archived"
    assert result["near_final"]["rewrite_count"] == 0
    # 生成客户端只有 neutral + style 两次调用（无重写第 3 次）
    assert len(scene_client.requests) == 2


# ---------- 扩容唯一入口：作者显式 topup ----------

def test_author_topup_expands_budget_with_audit(client, session) -> None:
    _seed_scene(session)
    state = session.get(SceneRunState, SCENE_ID)
    state.scene_token_budget = 1000
    state.scene_tokens_used = 900
    session.commit()

    response = client.post(
        f"/api/v1/scenes/{SCENE_ID}/budget/topup",
        json={"extra_tokens": 500, "reason": "关键场景需要再补一个候选"},
        headers={"X-Idempotency-Key": "w3-topup-1"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["scene_token_budget"] == 1500

    session.refresh(state)
    assert state.scene_token_budget == 1500

    audits = session.execute(select(OperationLog)).scalars().all()
    topups = [row for row in audits if row.event_type == "scene_budget_topup"]
    assert topups and topups[0].payload_json.get("extra_tokens") == 500


def test_topup_rejects_non_positive(client, session) -> None:
    _seed_scene(session)
    response = client.post(
        f"/api/v1/scenes/{SCENE_ID}/budget/topup",
        json={"extra_tokens": 0},
        headers={"X-Idempotency-Key": "w3-topup-bad"},
    )
    assert response.status_code == 422
