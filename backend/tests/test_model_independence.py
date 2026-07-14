"""Wave 6（结果闭环治理 §5.7）：LLM 角色槽独立性与 correlated_judge 标记。

生产默认要求 critic_independent 与 writer_primary 至少在模型或提供商之一不同；
同源时标记 correlated_judge=true 并降权提示。判定只影响咨询权重/展示，不改阻断权
（§5.7：LLM 评审在任何模型组合下都只提案，不单独硬阻断）。
"""
from __future__ import annotations

import uuid

from novel_system.db.models import LlmCall
from novel_system.services import model_independence as mi


def _seed_call(session, *, node_id, provider, model, scene_id):
    session.add(
        LlmCall(
            llm_call_id=f"llm_{uuid.uuid4().hex[:10]}",
            scope_type="scene",
            scope_id=scene_id,
            provider=provider,
            model=model,
            node_id=node_id,
            step=node_id,
            scene_id=scene_id,
            chapter_id="ch1",
            project_id="proj1",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
    )
    session.flush()


def test_independence_slots_cover_section_5_7():
    slots = set(mi.INDEPENDENCE_SLOTS)
    assert {
        "writer_primary",
        "writer_explorer",
        "critic_independent",
        "judge_advisory",
        "extractor_fast",
    } <= slots


def test_default_routing_writer_and_critic_are_independent(session):
    # 默认（离线）路由：writer style_draft=gpt-5，critic soft_qc=gpt-5-mini → 不同模型
    result = mi.judge_independence(session)
    assert result["correlated_judge"] is False
    assert result["independent"] is True
    assert result["writer"]["model"] != result["critic"]["model"]


def test_same_model_marks_correlated_and_downweights(session, monkeypatch):
    def _fake_route(_session, node_id):
        return {"provider": "openai_compatible", "model": "gpt-5", "degraded": False}

    monkeypatch.setattr(mi, "_node_route", _fake_route)
    result = mi.judge_independence(session)
    assert result["correlated_judge"] is True
    assert result["independent"] is False
    assert result["weight_hint"] == "downweight"


def test_resolve_slot_degrades_gracefully_when_route_unknown(session, monkeypatch):
    # task_config 抛 + 注册表也无 → degraded，不 500
    monkeypatch.setattr(
        mi, "_node_route",
        lambda _s, _n: {"provider": None, "model": None, "degraded": True},
    )
    slot = mi.resolve_slot(session, "writer_primary")
    assert slot["degraded"] is True
    assert slot["provider"] is None


def test_observed_correlated_judge_from_recorded_calls(session):
    scene_id = "scene_obs_same"
    _seed_call(session, node_id="style_draft", provider="p", model="gpt-5", scene_id=scene_id)
    _seed_call(session, node_id="near_final_acceptance_review", provider="p", model="gpt-5", scene_id=scene_id)
    observed = mi.observed_correlated_judge(session, scene_id)
    assert observed is not None
    assert observed["correlated_judge"] is True


def test_observed_independent_when_review_uses_other_model(session):
    scene_id = "scene_obs_diff"
    _seed_call(session, node_id="style_draft", provider="p", model="gpt-5", scene_id=scene_id)
    _seed_call(session, node_id="near_final_acceptance_review", provider="p", model="gpt-5-mini", scene_id=scene_id)
    observed = mi.observed_correlated_judge(session, scene_id)
    assert observed is not None
    assert observed["correlated_judge"] is False


def test_observed_none_when_no_review_call(session):
    scene_id = "scene_obs_writeronly"
    _seed_call(session, node_id="style_draft", provider="p", model="gpt-5", scene_id=scene_id)
    # 只有 writer 调用、没有评审调用 → 无法观测独立性
    assert mi.observed_correlated_judge(session, scene_id) is None
