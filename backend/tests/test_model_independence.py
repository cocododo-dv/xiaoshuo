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
        "chapter_judge_advisory",
        "extractor_fast",
    } <= slots


def test_default_routing_reports_correlated_near_final_judges(session):
    # critic 异源并不能掩盖两个 near-final judge 与 writer 同源。
    result = mi.judge_independence(session)
    assert result["correlated_judge"] is True
    assert result["independent"] is False
    assert result["writer"]["model"] != result["critic"]["model"]
    assert result["comparisons"]["critic_independent"]["status"] == "independent"
    assert result["comparisons"]["judge_advisory"]["status"] == "correlated"
    assert result["comparisons"]["chapter_judge_advisory"]["status"] == "correlated"


def test_same_model_marks_correlated_and_downweights(session, monkeypatch):
    def _fake_route(_session, node_id):
        return {"provider": "openai_compatible", "model": "gpt-5", "degraded": False}

    monkeypatch.setattr(mi, "_node_route", _fake_route)
    result = mi.judge_independence(session)
    assert result["correlated_judge"] is True
    assert result["independent"] is False
    assert result["weight_hint"] == "downweight"
    assert set(result["correlated_roles"]) == {
        "critic_independent",
        "judge_advisory",
        "chapter_judge_advisory",
    }


def test_all_review_roles_can_be_independent(session, monkeypatch):
    routes = {
        "style_draft": ("writer_provider", "writer_model"),
        "soft_qc": ("critic_provider", "critic_model"),
        "near_final_acceptance_review": ("judge_provider", "judge_model"),
        "chapter_near_final_review": ("chapter_provider", "chapter_model"),
    }

    def _fake_route(_session, node_id):
        provider, model = routes[node_id]
        return {"provider": provider, "model": model, "degraded": False}

    monkeypatch.setattr(mi, "_node_route", _fake_route)
    result = mi.judge_independence(session)
    assert result["independence_status"] == "independent"
    assert result["correlated_judge"] is False
    assert result["correlated_roles"] == []


def test_unknown_judge_route_is_not_claimed_independent(session, monkeypatch):
    def _fake_route(_session, node_id):
        if node_id == "chapter_near_final_review":
            return {"provider": None, "model": None, "degraded": True}
        return {"provider": node_id, "model": node_id, "degraded": False}

    monkeypatch.setattr(mi, "_node_route", _fake_route)
    result = mi.judge_independence(session)
    assert result["independence_status"] == "unknown"
    assert result["independent"] is False
    assert result["unknown_roles"] == ["chapter_judge_advisory"]


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
    assert observed["correlated_roles"] == ["judge_advisory"]
    assert observed["role_evidence"]["judge_advisory"]["shared_sources"] == ["p/gpt-5"]


def test_observed_independent_when_review_uses_other_model(session):
    scene_id = "scene_obs_diff"
    _seed_call(session, node_id="style_draft", provider="p", model="gpt-5", scene_id=scene_id)
    _seed_call(session, node_id="near_final_acceptance_review", provider="p", model="gpt-5-mini", scene_id=scene_id)
    observed = mi.observed_correlated_judge(session, scene_id)
    assert observed is not None
    assert observed["correlated_judge"] is False
    assert observed["independent"] is False
    assert observed["independence_status"] == "independent_observed_partial"


def test_observed_chapter_judge_is_compared_separately(session):
    scene_id = "scene_obs_chapter_judge"
    _seed_call(session, node_id="style_draft", provider="p", model="gpt-5", scene_id=scene_id)
    _seed_call(session, node_id="soft_qc", provider="p", model="gpt-5-mini", scene_id=scene_id)
    _seed_call(session, node_id="chapter_near_final_review", provider="p", model="gpt-5", scene_id=scene_id)

    observed = mi.observed_correlated_judge(session, scene_id)

    assert observed is not None
    assert observed["role_evidence"]["critic_independent"]["status"] == "independent"
    assert observed["role_evidence"]["chapter_judge_advisory"]["status"] == "correlated"
    assert observed["correlated_roles"] == ["chapter_judge_advisory"]


def test_observed_evidence_includes_literary_rewrite_as_writer(session):
    scene_id = "scene_obs_rewrite"
    _seed_call(session, node_id="style_draft", provider="p", model="writer-a", scene_id=scene_id)
    _seed_call(
        session,
        node_id="scene_literary_rewrite",
        provider="p",
        model="writer-b",
        scene_id=scene_id,
    )
    _seed_call(
        session,
        node_id="near_final_acceptance_review",
        provider="p",
        model="writer-b",
        scene_id=scene_id,
    )

    observed = mi.observed_correlated_judge(session, scene_id)

    assert observed is not None
    assert "scene_literary_rewrite" in observed["writer_node_ids"]
    assert observed["writer_sources_by_node"]["scene_literary_rewrite"] == [
        "p/writer-b"
    ]
    assert observed["role_evidence"]["judge_advisory"]["shared_sources"] == [
        "p/writer-b"
    ]


def test_observed_chapter_scope_uses_all_calls_in_chapter(session):
    _seed_call(session, node_id="style_draft", provider="p", model="gpt-5", scene_id="chapter_scene_1")
    _seed_call(
        session,
        node_id="chapter_near_final_review",
        provider="p",
        model="gpt-5",
        scene_id="chapter_scene_2",
    )
    for row in session.query(LlmCall).filter(LlmCall.scene_id.in_(("chapter_scene_1", "chapter_scene_2"))):
        row.chapter_id = "chapter_scope_1"
    session.flush()

    observed = mi.observed_correlated_judge(
        session,
        None,
        chapter_id="chapter_scope_1",
    )

    assert observed is not None
    assert observed["scope_type"] == "chapter"
    assert observed["scope_id"] == "chapter_scope_1"
    assert observed["correlated_roles"] == ["chapter_judge_advisory"]


def test_observed_none_when_no_review_call(session):
    scene_id = "scene_obs_writeronly"
    _seed_call(session, node_id="style_draft", provider="p", model="gpt-5", scene_id=scene_id)
    # 只有 writer 调用、没有评审调用 → 无法观测独立性
    assert mi.observed_correlated_judge(session, scene_id) is None
