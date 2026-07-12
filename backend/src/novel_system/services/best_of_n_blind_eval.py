"""Best-of-N up-bound blind evaluation — blueprint §6.2 / §17.

§17: 「上 Best-of-N 后,用人工盲测量偏好率。判据不是二元的——偏好率是连续的
(如 60 次盲测 38 次选 Best-of-N,p 值已低),正确的问题是『这点改善是否值 5 倍
token 成本』。」

§6.2: the adversarial ranker only governs the **down-bound** (machine filters out the
worst — already verified in test_best_of_n_selection_validation). The **up-bound** —
"among candidates that cleared the floor, does a human actually prefer the one Best-of-N
paid 5× tokens to select?" — is human territory. This module is the *machinery* for that
human measurement:

  1. build_blind_plan  — for each scene, pit the Best-of-N pick against the single-shot
     baseline (what N=1 would have produced), anonymise + shuffle into A/B so the judge
     cannot tell which is which, and keep a hidden key.
  2. tally_votes       — fold the human's A/B votes back through the hidden key into
     treatment-vs-control wins.
  3. evaluate          — preference rate + EXACT two-sided binomial p-value + a
     transparent, configurable cost/benefit verdict.

It is generator-agnostic: feed candidate sets from a live LLM run, a stored SceneRunState,
or a fixtures file. The blinding + statistics are pure and fully unit-tested. The
"is it worth it" threshold is a *labeled, configurable judgment knob* (the blueprint says
so) — this module surfaces the numbers; it does not pretend the business call is objective.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import comb
from typing import Any

from novel_system.services.literary_quality import adversarial_rank_score


# ---------------------------------------------------------------------------
# Selection — reuse the SAME ranker the production pipeline uses, so the blind
# test measures the REAL Best-of-N pick, not a re-implementation.
# ---------------------------------------------------------------------------

def select_best_of_n(candidates: list[str], *, weights: dict[str, float] | None = None) -> int:
    """Index of the candidate the Best-of-N down-bound screen would pick (argmax)."""
    if not candidates:
        raise ValueError("candidates must be non-empty")
    scores = [adversarial_rank_score(c, weights=weights) for c in candidates]
    best = 0
    for i in range(1, len(scores)):
        if scores[i] > scores[best]:
            best = i
    return best


# ---------------------------------------------------------------------------
# Blind plan
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class BlindComparison:
    comparison_id: str
    scene_id: str
    option_a: str
    option_b: str
    # hidden from the judge until tally:
    treatment_slot: str          # "A" or "B" — which option is the Best-of-N pick
    best_index: int
    baseline_index: int
    no_contrast: bool            # Best-of-N picked the same candidate as the baseline

    def ballot_view(self) -> dict[str, str]:
        """The judge-facing view — NO leakage of which side is the Best-of-N pick."""
        return {
            "comparison_id": self.comparison_id,
            "scene_id": self.scene_id,
            "option_a": self.option_a,
            "option_b": self.option_b,
        }


def build_blind_plan(
    candidate_sets: list[dict[str, Any]],
    *,
    seed: int = 0,
    baseline: str = "first",
    weights: dict[str, float] | None = None,
) -> list[BlindComparison]:
    """Build a blinded A/B plan: Best-of-N pick vs single-shot baseline, per scene.

    candidate_sets: ``[{"scene_id": str, "candidates": [str, ...]}, ...]``
    baseline: ``"first"`` (candidate[0] = what a single un-sampled shot yields) or
              ``"random"`` (a random non-best candidate, seeded — models "any single shot").
    A scene whose Best-of-N pick == baseline is kept but flagged ``no_contrast`` (the
    measurement honestly records "Best-of-N changed nothing here").
    """
    rng = random.Random(seed)
    plan: list[BlindComparison] = []
    for i, cs in enumerate(candidate_sets):
        scene_id = str(cs.get("scene_id") or f"scene_{i}")
        candidates = list(cs.get("candidates") or [])
        if len(candidates) < 2:
            continue  # cannot compare Best-of-N vs baseline with <2 candidates
        best_idx = select_best_of_n(candidates, weights=weights)
        if baseline == "random":
            pool = [j for j in range(len(candidates)) if j != best_idx]
            baseline_idx = rng.choice(pool) if pool else best_idx
        else:
            baseline_idx = 0
        no_contrast = best_idx == baseline_idx
        # Shuffle treatment/control into A/B (hidden coin).
        treatment_is_a = rng.random() < 0.5
        if treatment_is_a:
            option_a, option_b, treatment_slot = candidates[best_idx], candidates[baseline_idx], "A"
        else:
            option_a, option_b, treatment_slot = candidates[baseline_idx], candidates[best_idx], "B"
        plan.append(BlindComparison(
            comparison_id=f"cmp_{i:04d}",
            scene_id=scene_id,
            option_a=option_a,
            option_b=option_b,
            treatment_slot=treatment_slot,
            best_index=best_idx,
            baseline_index=baseline_idx,
            no_contrast=no_contrast,
        ))
    return plan


# ---------------------------------------------------------------------------
# Tally + statistics
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class BlindEvalResult:
    treatment_wins: int = 0
    control_wins: int = 0
    no_contrast: int = 0
    invalid: int = 0
    unvoted: int = 0
    ties: int = 0  # Wave 5（§6.2）：平局照记，但不计入胜场、不进显著性分母

    @property
    def decisive(self) -> int:
        """Votes that actually compared two different candidates (ties excluded)."""
        return self.treatment_wins + self.control_wins


def tally_votes(plan: list[BlindComparison], votes: dict[str, str]) -> BlindEvalResult:
    """Fold A/B votes through the hidden key. votes: {comparison_id: "A"|"B"}."""
    result = BlindEvalResult()
    for cmp in plan:
        if cmp.no_contrast:
            result.no_contrast += 1
            continue
        vote = votes.get(cmp.comparison_id)
        if vote is None:
            result.unvoted += 1
            continue
        vote = str(vote).strip().upper()
        if vote not in ("A", "B"):
            result.invalid += 1
            continue
        if vote == cmp.treatment_slot:
            result.treatment_wins += 1
        else:
            result.control_wins += 1
    return result


def tally_votes_with_ties(plan: list[BlindComparison], votes: dict[str, str]) -> BlindEvalResult:
    """Wave 5（§6.2）：折叠 A/B/tie 投票。平局照记（``ties``），不计胜场、不进分母。

    votes: ``{comparison_id: "A"|"B"|"tie"}``（大小写不敏感；"tie"/"平局" 均记平局）。
    """
    result = BlindEvalResult()
    for cmp in plan:
        if cmp.no_contrast:
            result.no_contrast += 1
            continue
        raw = votes.get(cmp.comparison_id)
        if raw is None:
            result.unvoted += 1
            continue
        vote = str(raw).strip().upper()
        if vote in ("TIE", "平局", "T"):
            result.ties += 1
            continue
        if vote not in ("A", "B"):
            result.invalid += 1
            continue
        if vote == cmp.treatment_slot:
            result.treatment_wins += 1
        else:
            result.control_wins += 1
    return result


def binomial_two_sided_p(k: int, n: int, p: float = 0.5) -> float:
    """Exact two-sided binomial test p-value (method of small p-values)."""
    if n <= 0:
        return 1.0
    k = max(0, min(k, n))
    probs = [comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(n + 1)]
    threshold = probs[k] * (1 + 1e-9)
    return min(1.0, sum(pr for pr in probs if pr <= threshold))


def binomial_one_sided_p(k: int, n: int, p: float = 0.5) -> float:
    """Exact one-sided (greater) binomial p-value: P(X >= k).

    A preference test is directional — "is Best-of-N *better*?" — so the one-sided test
    is the natural match for the §17 question. (It is also why the blueprint's loose
    "38/60, p 值已低" reads as significant: 38/60 is p≈0.026 one-sided but a borderline
    p≈0.052 under an exact *two-sided* test. Sidedness matters; the harness exposes both.)
    """
    if n <= 0:
        return 1.0
    k = max(0, min(k, n))
    return min(1.0, sum(comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(k, n + 1)))


def min_n_for_significance(observed_rate: float, *, alpha: float = 0.05, cap: int = 5000) -> int | None:
    """Smallest sample size at which *observed_rate* would reach two-sided significance.

    Answers the §17 planning question "how many blind judgments do I need?".
    Returns None if not reached within *cap*.
    """
    if observed_rate == 0.5:
        return None
    for n in range(2, cap + 1):
        k = round(observed_rate * n)
        if binomial_two_sided_p(k, n) < alpha:
            return n
    return None


def min_wins_for_significance(n: int, *, alpha: float = 0.05) -> int | None:
    """Wave 5（§6.2）：n 个非平局对上，达到双侧精确二项 p<alpha 所需的最小胜场（多数方向）。

    设计 §6.2 阈值表锚点（alpha=0.05）：n=30→21、25→18、27→20、28→20、29→21。
    返回满足 ``k > n/2`` 且 ``binomial_two_sided_p(k, n) < alpha`` 的最小 k；不存在返回 None。
    """
    if n <= 0:
        return None
    for k in range(n // 2 + 1, n + 1):
        if k * 2 > n and binomial_two_sided_p(k, n, 0.5) < alpha:
            return k
    return None


@dataclass(slots=True)
class StrategyDecision:
    """§9.4 默认策略判据 + §8 项 7 每模块 keep/downgrade/disable 结论。"""

    non_tie_n: int
    treatment_wins: int
    control_wins: int
    ties: int
    preference_rate: float
    p_value: float
    min_wins: int | None
    significant: bool          # treatment 在多数方向达到双侧显著
    decision: str              # upgrade_to_default | keep_optional | disable | need_more_samples
    requires_fresh_replication: bool
    rationale: str


def default_strategy_decision(
    result: BlindEvalResult,
    *,
    target_n: int = 30,
    target_wins: int = 21,
    alpha: float = 0.05,
    is_ablation: bool = True,
) -> StrategyDecision:
    """把盲评 tally 折成 §9.4 的默认策略决定与每模块结论。

    - ``upgrade_to_default``：非平局 n≥target_n(30) 且 treatment 胜≥target_wins(21) 且双侧 p<alpha。
    - ``disable``：control 显著更优（treatment 显著更差）——该模块应关闭。
    - ``keep_optional``：其余（含"显著但欠功效 n<30"、"不显著")——负结果是有效结论，保持可选。
    - ``need_more_samples``：非平局 n==0。

    不自动翻转任何生产默认（§11 规则 7）；``requires_fresh_replication`` 标记消融序列升级
    默认前需第二批 30 组非平局对复验（§8 项 8 防多重比较假阳性）。
    """
    t, c, ties = result.treatment_wins, result.control_wins, result.ties
    non_tie_n = t + c
    if non_tie_n == 0:
        return StrategyDecision(
            non_tie_n=0, treatment_wins=t, control_wins=c, ties=ties,
            preference_rate=0.0, p_value=1.0, min_wins=None, significant=False,
            decision="need_more_samples", requires_fresh_replication=False,
            rationale="无非平局有效对，无法判定。",
        )
    rate = t / non_tie_n
    p = binomial_two_sided_p(t, non_tie_n, 0.5)
    min_wins = min_wins_for_significance(non_tie_n, alpha=alpha)
    treatment_sig = min_wins is not None and t >= min_wins
    control_sig = min_wins is not None and c >= min_wins

    if control_sig:
        decision = "disable"
        requires_replication = False
        rationale = (
            f"Control 显著更优（{c}/{non_tie_n}，双侧 p={p:.3f}<{alpha}）：该模块使偏好下降，建议关闭。"
        )
    elif non_tie_n >= target_n and t >= target_wins and p < alpha:
        decision = "upgrade_to_default"
        requires_replication = is_ablation
        rationale = (
            f"treatment 偏好 {rate:.0%}（{t}/{non_tie_n}，双侧 p={p:.3f}<{alpha}），达 {target_wins}/{target_n} 门槛，"
            f"可升级为默认" + ("；作为消融序列须再取一批 30 组非平局对复验（§8 项 8）。" if is_ablation else "。")
        )
    else:
        decision = "keep_optional"
        requires_replication = False
        if treatment_sig and non_tie_n < target_n:
            rationale = (
                f"treatment 在 n={non_tie_n} 上显著（≥{min_wins} 胜），但未达 30 组功效门槛，暂保持可选，补足样本再定。"
            )
        else:
            rationale = (
                f"treatment 偏好 {rate:.0%}（{t}/{non_tie_n}，双侧 p={p:.3f}）未达显著/门槛，保持可选（负结果是有效结论）。"
            )

    return StrategyDecision(
        non_tie_n=non_tie_n, treatment_wins=t, control_wins=c, ties=ties,
        preference_rate=round(rate, 4), p_value=round(p, 6), min_wins=min_wins,
        significant=treatment_sig and non_tie_n >= target_n and t >= target_wins,
        decision=decision, requires_fresh_replication=requires_replication,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Verdict — surfaces the numbers + a transparent, configurable cost/benefit call
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class BlindEvalVerdict:
    total_scenes: int
    decisive: int
    treatment_wins: int
    control_wins: int
    no_contrast: int
    preference_rate: float          # P(human prefers Best-of-N pick | decisive)
    p_value: float
    significant: bool
    token_multiplier: float
    worth_it_rate: float            # the JUDGMENT bar (configurable, not objective)
    verdict: str
    rationale: str
    p_sided: str = "two-sided"
    notes: list[str] = field(default_factory=list)


def evaluate(
    result: BlindEvalResult,
    *,
    token_multiplier: float = 5.0,
    alpha: float = 0.05,
    min_samples: int = 20,
    worth_it_rate: float | None = None,
    alternative: str = "two-sided",
) -> BlindEvalVerdict:
    """Turn a tally into preference rate + p-value + a transparent cost/benefit verdict.

    worth_it_rate: the preference rate above which the quality gain is deemed to justify
    paying *token_multiplier*× tokens. This is a BUSINESS JUDGMENT, not science — the
    blueprint says so. Default heuristic scales the bar with cost: the more you pay, the
    more decisively humans must prefer the result. Override freely.

    alternative: ``"two-sided"`` (conservative default) or ``"greater"`` (one-sided —
    the natural match for the directional "is Best-of-N better?" question).
    """
    decisive = result.decisive
    wins = result.treatment_wins
    rate = (wins / decisive) if decisive else 0.0
    if decisive == 0:
        p = 1.0
    elif alternative == "greater":
        p = binomial_one_sided_p(wins, decisive)
    else:
        p = binomial_two_sided_p(wins, decisive)
    side_label = "one-sided" if alternative == "greater" else "two-sided"
    significant = decisive >= min_samples and p < alpha

    if worth_it_rate is None:
        # Cost-scaled bar: 2× ⇒ 0.55, 5× ⇒ ~0.62, 10× ⇒ ~0.65. Capped, transparent.
        worth_it_rate = min(0.75, 0.5 + 0.12 * min(1.0, (token_multiplier - 1) / 4.0))

    notes: list[str] = []
    if result.no_contrast:
        notes.append(
            f"{result.no_contrast} scene(s): Best-of-N picked the same candidate as the "
            f"single-shot baseline — it changed nothing there (counts against ROI)."
        )
    if result.unvoted:
        notes.append(f"{result.unvoted} comparison(s) had no vote.")
    if result.invalid:
        notes.append(f"{result.invalid} vote(s) were invalid (not A/B).")

    if decisive < min_samples:
        verdict = "need_more_samples"
        need = min_n_for_significance(rate) if rate != 0.5 else None
        rationale = (
            f"Only {decisive} decisive judgments (< {min_samples}). "
            + (f"At the observed rate ~{rate:.0%}, ≈{need} would reach significance."
               if need else "Observed rate ~50% — no detectable preference at any n.")
        )
    elif not significant:
        verdict = "no_detectable_benefit"
        rationale = (
            f"Preference {rate:.0%} (n={decisive}) is not distinguishable from chance "
            f"({side_label} p={p:.3f} ≥ {alpha}). At {token_multiplier:g}× token cost, not justified on this evidence."
        )
    elif rate >= worth_it_rate:
        verdict = "justified"
        rationale = (
            f"Humans prefer the Best-of-N pick {rate:.0%} of the time "
            f"({side_label} p={p:.3f} < {alpha}), clearing the {worth_it_rate:.0%} bar for {token_multiplier:g}× cost."
        )
    else:
        verdict = "marginal"
        rationale = (
            f"A real but small edge: {rate:.0%} ({side_label} p={p:.3f}) is significant yet below the "
            f"{worth_it_rate:.0%} bar that {token_multiplier:g}× token cost would warrant. "
            f"Consider reserving Best-of-N for key scenes only (§6.4)."
        )

    return BlindEvalVerdict(
        total_scenes=decisive + result.no_contrast,
        decisive=decisive,
        treatment_wins=result.treatment_wins,
        control_wins=result.control_wins,
        no_contrast=result.no_contrast,
        preference_rate=round(rate, 4),
        p_value=round(p, 6),
        significant=significant,
        token_multiplier=token_multiplier,
        worth_it_rate=round(worth_it_rate, 4),
        verdict=verdict,
        rationale=rationale,
        p_sided=side_label,
        notes=notes,
    )


def format_report(verdict: BlindEvalVerdict) -> str:
    lines = [
        "=" * 64,
        "  Best-of-N up-bound blind evaluation (§6.2 / §17)",
        "=" * 64,
        f"  scenes compared     : {verdict.total_scenes}  "
        f"(decisive {verdict.decisive}, no-contrast {verdict.no_contrast})",
        f"  Best-of-N preferred : {verdict.treatment_wins} / {verdict.decisive}  "
        f"= {verdict.preference_rate:.0%}",
        f"  {verdict.p_sided} p-value{'' if verdict.p_sided == 'two-sided' else '  '} : "
        f"{verdict.p_value:.4f}  ({'significant' if verdict.significant else 'not significant'})",
        f"  token cost          : {verdict.token_multiplier:g}×   "
        f"worth-it bar: {verdict.worth_it_rate:.0%}",
        "-" * 64,
        f"  VERDICT: {verdict.verdict.upper()}",
        f"  {verdict.rationale}",
    ]
    for n in verdict.notes:
        lines.append(f"  · {n}")
    lines.append("=" * 64)
    return "\n".join(lines)
