"""Tests for the Best-of-N up-bound blind evaluation harness — §6.2 / §17.

Verifies the machinery a human uses to answer "is Best-of-N worth 5× tokens?":
blinding leaks nothing, votes fold back correctly through the hidden key, the exact
binomial test matches known values (incl. the blueprint's 38/60 anchor), and the
cost/benefit verdict classifies justified / marginal / no-benefit / need-more-samples.
"""
from __future__ import annotations

import pytest

from novel_system.services.best_of_n_blind_eval import (
    BlindEvalResult,
    binomial_one_sided_p,
    binomial_two_sided_p,
    build_blind_plan,
    evaluate,
    format_report,
    min_n_for_significance,
    select_best_of_n,
    tally_votes,
)

# A clean (low AI-flavor) vs slop (high AI-flavor) pair — the ranker must prefer clean.
SLOP = (
    "他觉得心口发闷,悲伤涌了上来。他看到她转身,心里一片冰凉。"
    "他知道,一切都无法挽回。他叹了口气,仿佛命运早已注定。一切都变得不同了。"
)
CLEAN = (
    "风从窗缝钻进来,吹得烛火歪了歪。林远把那封信折好,又展开,指节压过纸面的折痕。"
    "“你早就料到了。”苏晚没有回头。他没有答话,只把信凑近火苗,看纸角卷起焦黑。"
)


def test_select_best_of_n_matches_ranker() -> None:
    # CLEAN should outrank SLOP, so the Best-of-N pick is the clean candidate.
    assert select_best_of_n([SLOP, CLEAN]) == 1
    assert select_best_of_n([CLEAN, SLOP]) == 0


def test_blind_plan_hides_treatment_but_is_recoverable() -> None:
    plan = build_blind_plan([{"scene_id": "s1", "candidates": [SLOP, CLEAN]}], seed=1)
    assert len(plan) == 1
    cmp = plan[0]
    # Judge-facing ballot must NOT leak which side is the Best-of-N pick.
    ballot = cmp.ballot_view()
    assert set(ballot) == {"comparison_id", "scene_id", "option_a", "option_b"}
    assert "treatment_slot" not in ballot
    # But the hidden key correctly points at the clean candidate (the Best-of-N pick).
    treatment_text = cmp.option_a if cmp.treatment_slot == "A" else cmp.option_b
    assert treatment_text == CLEAN
    assert cmp.best_index == 1 and cmp.baseline_index == 0
    assert cmp.no_contrast is False


def test_no_contrast_flagged_when_bestofn_equals_baseline() -> None:
    # candidates[0] is already the best → Best-of-N changes nothing vs single-shot.
    plan = build_blind_plan([{"scene_id": "s1", "candidates": [CLEAN, SLOP]}], seed=0)
    assert plan[0].no_contrast is True


def test_plan_is_deterministic_given_seed() -> None:
    sets = [{"scene_id": "s1", "candidates": [SLOP, CLEAN]}]
    a = build_blind_plan(sets, seed=7)[0]
    b = build_blind_plan(sets, seed=7)[0]
    assert a.treatment_slot == b.treatment_slot


def test_tally_folds_votes_through_hidden_key() -> None:
    plan = build_blind_plan(
        [
            {"scene_id": "s1", "candidates": [SLOP, CLEAN]},
            {"scene_id": "s2", "candidates": [SLOP, CLEAN]},
        ],
        seed=3,
    )
    # Vote for whichever slot is actually the treatment in each comparison.
    votes = {c.comparison_id: c.treatment_slot for c in plan}
    res = tally_votes(plan, votes)
    assert res.treatment_wins == 2 and res.control_wins == 0
    # Now vote the opposite slot everywhere → all control wins.
    opp = {c.comparison_id: ("B" if c.treatment_slot == "A" else "A") for c in plan}
    res2 = tally_votes(plan, opp)
    assert res2.treatment_wins == 0 and res2.control_wins == 2


def test_tally_counts_unvoted_and_invalid() -> None:
    plan = build_blind_plan([{"scene_id": "s1", "candidates": [SLOP, CLEAN]}], seed=2)
    cid = plan[0].comparison_id
    assert tally_votes(plan, {}).unvoted == 1
    assert tally_votes(plan, {cid: "X"}).invalid == 1


@pytest.mark.parametrize(
    "k,n,expected",
    [
        (30, 60, "eq1"),         # exactly chance → p == 1.0
        (38, 60, "borderline"),  # blueprint anchor: exact two-sided p≈0.052 — NOT <0.05!
        (40, 60, "lt05"),        # a genuinely significant two-sided result
        (33, 60, "gt05"),        # mild lean → not significant
        (0, 10, "lt05"),         # extreme → significant
        (5, 10, "eq1"),          # exactly chance
    ],
)
def test_binomial_two_sided_matches_known_values(k, n, expected) -> None:
    p = binomial_two_sided_p(k, n)
    if expected == "eq1":
        assert p == pytest.approx(1.0)
    elif expected == "lt05":
        assert p < 0.05
    elif expected == "gt05":
        assert p > 0.05
    elif expected == "borderline":
        assert 0.045 < p < 0.06  # the blueprint's "p 值已低" is loose; exact two-sided ≈0.052


def test_binomial_one_sided_makes_blueprint_anchor_significant() -> None:
    # The directional (one-sided) test — the natural match for "is Best-of-N better?" —
    # DOES clear 0.05 for 38/60 (p≈0.026), which is what the blueprint loosely meant.
    one = binomial_one_sided_p(38, 60)
    two = binomial_two_sided_p(38, 60)
    assert one < 0.05 < two            # significant one-sided, borderline two-sided
    assert one == pytest.approx(two / 2, rel=0.05)  # symmetric null ⇒ one ≈ two/2


def test_min_n_for_significance() -> None:
    assert min_n_for_significance(0.5) is None       # no effect → never significant
    n60 = min_n_for_significance(0.60)
    assert n60 is not None and 20 <= n60 <= 120      # ~60% needs a few dozen judgments


def _result(t: int, c: int, no_contrast: int = 0) -> BlindEvalResult:
    return BlindEvalResult(treatment_wins=t, control_wins=c, no_contrast=no_contrast)


def test_verdict_justified_two_sided() -> None:
    v = evaluate(_result(40, 20), token_multiplier=5.0)   # 66.7%, two-sided p≈0.014
    assert v.significant is True
    assert v.verdict == "justified"
    assert v.preference_rate == pytest.approx(0.6667, abs=1e-3)


def test_sidedness_changes_borderline_verdict() -> None:
    # 38/60 (63.3%): borderline two-sided (not significant) vs significant one-sided.
    two = evaluate(_result(38, 22), token_multiplier=5.0, alternative="two-sided")
    one = evaluate(_result(38, 22), token_multiplier=5.0, alternative="greater")
    assert two.significant is False and two.verdict == "no_detectable_benefit"
    assert one.significant is True and one.verdict == "justified"


def test_verdict_marginal_significant_but_below_cost_bar() -> None:
    v = evaluate(_result(116, 84), token_multiplier=5.0)  # 58%, significant, < 62% bar
    assert v.significant is True
    assert v.verdict == "marginal"


def test_verdict_no_detectable_benefit() -> None:
    v = evaluate(_result(33, 27), token_multiplier=5.0)   # 55%, not significant
    assert v.significant is False
    assert v.verdict == "no_detectable_benefit"


def test_verdict_need_more_samples() -> None:
    v = evaluate(_result(7, 3), token_multiplier=5.0)     # n=10 < min_samples
    assert v.verdict == "need_more_samples"


def test_full_flow_demo_report() -> None:
    sets = [{"scene_id": f"s{i}", "candidates": [SLOP, CLEAN]} for i in range(30)]
    plan = build_blind_plan(sets, seed=11)
    # Simulate a judge who always prefers the (hidden) Best-of-N pick.
    votes = {c.comparison_id: c.treatment_slot for c in plan}
    res = tally_votes(plan, votes)
    v = evaluate(res, token_multiplier=5.0)
    assert res.decisive == 30
    assert v.verdict == "justified"
    report = format_report(v)
    assert "VERDICT: JUSTIFIED" in report
