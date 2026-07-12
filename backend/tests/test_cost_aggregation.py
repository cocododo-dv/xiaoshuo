"""Wave 6（结果闭环治理 §5.8/§10）：token/费用聚合——场景/章节/项目三级。

完成门：任意场景可解释总成本、各阶段占比、是否超预算、评审是否独立。跨 provider
token 不相加（分词器不同）、汇总以费用为准；三口径（估算/实际/计费）；额外成本
（失败重试/重复 QC/低分散补候选）可归因。
"""
from __future__ import annotations

from novel_system.db.models import FinalScene, LlmCall, SceneCard, SceneRunState
from novel_system.services import cost_aggregation as ca


def _scene(session, scene_id, chapter_id="CH1", project_id="proj1", seq=1):
    session.add(
        SceneCard(
            scene_id=scene_id,
            chapter_id=chapter_id,
            project_id=project_id,
            scene_seq=seq,
            scene_goal="g",
        )
    )
    session.flush()


def _runstate(session, scene_id, *, budget=None, used=0, criticality=None, policy=None):
    session.add(
        SceneRunState(
            scene_id=scene_id,
            scene_token_budget=budget,
            scene_tokens_used=used,
            criticality_level=criticality,
            run_policy=policy,
        )
    )
    session.flush()


def _call(
    session,
    scene_id,
    *,
    node_id,
    tokens=150,
    provider="openai_compatible",
    model="gpt-5",
    chapter_id="CH1",
    project_id="proj1",
    error_code=None,
    created_at=None,
):
    idx = _call.counter = getattr(_call, "counter", 0) + 1
    session.add(
        LlmCall(
            llm_call_id=f"llm_{idx:04d}",
            provider=provider,
            model=model,
            node_id=node_id,
            step=node_id,
            scene_id=scene_id,
            chapter_id=chapter_id,
            project_id=project_id,
            prompt_tokens=int(tokens * 2 // 3),
            completion_tokens=int(tokens // 3),
            total_tokens=tokens,
            error_code=error_code,
            created_at=created_at or f"2026-07-12T00:00:{idx:02d}Z",
        )
    )
    session.flush()


def _archived(session, scene_id, chapter_id="CH1"):
    session.add(
        FinalScene(
            row_id=f"fs_{scene_id}",
            scene_id=scene_id,
            chapter_id=chapter_id,
            content="正文",
            status="archived",
            source_bundle_id="b",
            source_bundle_hash="h",
        )
    )
    session.flush()


# ---- classify_phase ----------------------------------------------------------

def test_classify_phase_maps_known_nodes():
    assert ca.classify_phase("style_draft", "style_draft") == "candidate_generation"
    assert ca.classify_phase("neutral_draft", "neutral_draft") == "candidate_generation"
    assert ca.classify_phase("hard_qc", "hard_qc") == "quality_check"
    assert ca.classify_phase("near_final_acceptance_review", "x") == "quality_check"
    assert ca.classify_phase("style_patch", "style_patch") == "revision"
    assert ca.classify_phase("scene_auto_rewrite", "x") == "revision"
    assert ca.classify_phase("writer_deep_review", "x") == "review"
    assert ca.classify_phase("style_profile_extract", "x") == "other"


# ---- scene_cost --------------------------------------------------------------

def test_scene_cost_phase_shares_sum_to_one(session):
    _scene(session, "S1")
    _runstate(session, "S1")
    _call(session, "S1", node_id="style_draft", tokens=300)
    _call(session, "S1", node_id="hard_qc", tokens=100)
    _call(session, "S1", node_id="writer_deep_review", tokens=100)
    result = ca.scene_cost(session, "S1")
    shares = sum(p["share"] for p in result["phase_breakdown"].values())
    assert abs(shares - 1.0) < 1e-6
    assert result["phase_breakdown"]["candidate_generation"]["call_count"] == 1
    assert result["total_cost"] > 0
    assert result["call_count"] == 3


def test_scene_cost_cross_provider_tokens_not_summed(session):
    _scene(session, "S2")
    _runstate(session, "S2")
    _call(session, "S2", node_id="style_draft", provider="openai_compatible", model="gpt-5", tokens=200)
    _call(session, "S2", node_id="hard_qc", provider="anthropic", model="claude", tokens=100)
    result = ca.scene_cost(session, "S2")
    assert result["cross_provider"] is True
    assert set(result["tokens_by_provider"]) == {"openai_compatible", "anthropic"}
    assert result["tokens_by_provider"]["openai_compatible"] == 200
    assert result["tokens_by_provider"]["anthropic"] == 100


def test_scene_cost_budget_over_and_under(session):
    _scene(session, "S3")
    _runstate(session, "S3", budget=1000, used=1200, policy="strict")
    _call(session, "S3", node_id="style_draft", tokens=150)
    over = ca.scene_cost(session, "S3")
    assert over["budget"]["over_budget"] is True
    assert over["budget"]["usage_ratio"] > 1.0
    assert over["budget"]["run_policy"] == "strict"

    _scene(session, "S3b")
    _runstate(session, "S3b", budget=1000, used=200)
    _call(session, "S3b", node_id="style_draft", tokens=150)
    under = ca.scene_cost(session, "S3b")
    assert under["budget"]["over_budget"] is False


def test_scene_cost_three_calibers(session):
    _scene(session, "S4")
    _runstate(session, "S4", budget=1000, used=150)
    _call(session, "S4", node_id="style_draft", tokens=150)
    result = ca.scene_cost(session, "S4")
    cal = result["calibers"]
    assert set(cal) >= {"estimate", "actual", "billed"}
    assert cal["actual"]["tokens"] == 150  # provider usage
    assert cal["billed"]["is_estimate"] is True  # prompt-cache 折扣未接入


def test_scene_cost_extra_cost_attribution(session):
    _scene(session, "S5")
    _runstate(session, "S5", criticality="standard")  # 标准场景初始 N=2
    # 3 个候选 → 超出初始 2 → 1 个补候选归 low_dispersion_topup
    _call(session, "S5", node_id="style_draft", tokens=100, created_at="2026-07-12T00:00:01Z")
    _call(session, "S5", node_id="style_draft", tokens=100, created_at="2026-07-12T00:00:02Z")
    _call(session, "S5", node_id="style_draft", tokens=100, created_at="2026-07-12T00:00:03Z")
    # 2 个 QC → 第 2 个归 repeat_qc
    _call(session, "S5", node_id="hard_qc", tokens=50, created_at="2026-07-12T00:00:04Z")
    _call(session, "S5", node_id="hard_qc", tokens=50, created_at="2026-07-12T00:00:05Z")
    # 1 个失败调用 → failed_call
    _call(session, "S5", node_id="style_patch", tokens=40, error_code="LLM_TIMEOUT", created_at="2026-07-12T00:00:06Z")
    extra = ca.scene_cost(session, "S5")["extra_cost"]
    assert extra["failed_call_cost"] > 0
    assert extra["repeat_qc_cost"] > 0
    assert extra["low_dispersion_topup_cost"] > 0
    assert extra["total"] > 0
    assert 0 <= extra["retry_cost_ratio"] <= 1


def test_scene_cost_empty_no_calls(session):
    _scene(session, "S6")
    _runstate(session, "S6")
    result = ca.scene_cost(session, "S6")
    assert result["total_cost"] == 0
    assert result["call_count"] == 0


def test_scene_cost_includes_judge_independence(session):
    _scene(session, "S7")
    _runstate(session, "S7")
    _call(session, "S7", node_id="style_draft", model="gpt-5", tokens=100)
    _call(session, "S7", node_id="near_final_acceptance_review", model="gpt-5", tokens=100)
    result = ca.scene_cost(session, "S7")
    assert "judge_independence" in result
    # 同场景 writer 与评审都用 gpt-5 → observed correlated
    assert result["judge_independence"]["correlated_judge"] is True


# ---- chapter / project rollup ------------------------------------------------

def test_chapter_cost_archived_metrics(session):
    _scene(session, "C1S1", chapter_id="CHX")
    _scene(session, "C1S2", chapter_id="CHX")
    _call(session, "C1S1", node_id="style_draft", tokens=200, chapter_id="CHX")
    _call(session, "C1S2", node_id="style_draft", tokens=100, chapter_id="CHX")
    _archived(session, "C1S1", chapter_id="CHX")
    _archived(session, "C1S2", chapter_id="CHX")
    result = ca.chapter_cost(session, "CHX")
    assert result["archived_scene_count"] == 2
    assert result["total_tokens"] == 300
    assert result["tokens_per_archived_scene"] == 150


def test_project_cost_rollup(session):
    _scene(session, "P1S1", chapter_id="PCH1", project_id="P1")
    _scene(session, "P1S2", chapter_id="PCH2", project_id="P1")
    _call(session, "P1S1", node_id="style_draft", tokens=200, chapter_id="PCH1", project_id="P1")
    _call(session, "P1S2", node_id="hard_qc", tokens=100, chapter_id="PCH2", project_id="P1")
    _archived(session, "P1S1", chapter_id="PCH1")
    result = ca.project_cost(session, "P1")
    assert result["total_cost"] > 0
    assert result["chapter_count"] == 2
    assert "judge_independence" in result
    assert result["archived_scene_count"] == 1
