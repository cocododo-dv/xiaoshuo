"""CLI for the Best-of-N up-bound blind evaluation (blueprint §6.2 / §17).

The human-in-the-loop measurement the blueprint asks for ("人工盲测量偏好率…是否值
5× token"). The statistics and blinding live in
``novel_system.services.best_of_n_blind_eval`` (fully unit-tested); this is thin glue.

Flow
----
1. Produce candidate sets (from a real LLM run / stored SceneRunState / by hand) as JSON:

       {"candidate_sets": [
           {"scene_id": "S001", "candidates": ["draft A ...", "draft B ...", "draft C ..."]},
           ...
       ]}

2. Build a blinded ballot (Best-of-N pick vs single-shot baseline, shuffled, key hidden):

       python -m novel_system.tools.best_of_n_blind_eval plan \
           --candidates cand.json --out plan.json

   Read the printed ballot, judge each A/B, and record your choices as votes JSON:

       {"cmp_0000": "A", "cmp_0001": "B", ...}

3. Score it (you never saw which side was which):

       python -m novel_system.tools.best_of_n_blind_eval tally \
           --plan plan.json --votes votes.json --token-multiplier 5 --alternative greater

Run ``... demo`` for an end-to-end synthetic example.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import random
import sys
from typing import Any

from novel_system.services.best_of_n_blind_eval import (
    BlindComparison,
    build_blind_plan,
    evaluate,
    format_report,
    tally_votes,
)


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _candidate_sets(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        return list(payload.get("candidate_sets") or [])
    if isinstance(payload, list):
        return payload
    raise SystemExit("candidates JSON must be a list or {\"candidate_sets\": [...]}")


def _print_ballot(plan: list[BlindComparison]) -> None:
    print("\n=== BLIND BALLOT (which draft is better? record A or B per comparison) ===")
    shown = 0
    for cmp in plan:
        if cmp.no_contrast:
            continue  # nothing to judge — Best-of-N matched the baseline
        shown += 1
        b = cmp.ballot_view()
        print(f"\n[{b['comparison_id']}]  scene={b['scene_id']}")
        print(f"  A) {b['option_a']}")
        print(f"  B) {b['option_b']}")
    skipped = len(plan) - shown
    print(f"\n{shown} comparisons to judge"
          + (f"  ({skipped} skipped — Best-of-N changed nothing there)" if skipped else ""))


def _cmd_plan(args: argparse.Namespace) -> int:
    sets = _candidate_sets(_load_json(args.candidates))
    plan = build_blind_plan(sets, seed=args.seed, baseline=args.baseline)
    if not plan:
        raise SystemExit("no comparable scenes (each needs ≥2 candidates)")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump([dataclasses.asdict(c) for c in plan], fh, ensure_ascii=False, indent=2)
        print(f"wrote plan (with hidden key) -> {args.out}")
    _print_ballot(plan)
    return 0


def _cmd_tally(args: argparse.Namespace) -> int:
    plan = [BlindComparison(**d) for d in _load_json(args.plan)]
    votes = _load_json(args.votes)
    result = tally_votes(plan, votes)
    verdict = evaluate(
        result,
        token_multiplier=args.token_multiplier,
        alpha=args.alpha,
        alternative=args.alternative,
    )
    print(format_report(verdict))
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    slop = ("他觉得心口发闷,悲伤涌了上来。他看到她转身,他知道一切都无法挽回。"
            "他叹了口气,仿佛命运早已注定。")
    clean = ("风从窗缝钻进来,吹得烛火歪了歪。林远把信折好又展开,指节压过折痕。"
             "“你早就料到了。”苏晚没有回头。")
    sets = [{"scene_id": f"S{i:03d}", "candidates": [slop, clean]} for i in range(50)]
    plan = build_blind_plan(sets, seed=42)
    # Simulate a judge who prefers the (hidden) Best-of-N pick ~66% of the time.
    rng = random.Random(123)
    votes = {}
    for c in plan:
        if c.no_contrast:
            continue
        prefer_treatment = rng.random() < 0.66
        votes[c.comparison_id] = c.treatment_slot if prefer_treatment else (
            "B" if c.treatment_slot == "A" else "A"
        )
    result = tally_votes(plan, votes)
    print(format_report(evaluate(result, token_multiplier=5.0, alternative="greater")))
    print("\n(demo: synthetic judge @~66% preference; real use feeds human votes)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Best-of-N up-bound blind evaluation (§6.2/§17)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="build a blinded ballot from candidate sets")
    p_plan.add_argument("--candidates", required=True, help="candidates JSON")
    p_plan.add_argument("--out", help="write the full plan (with hidden key) here")
    p_plan.add_argument("--seed", type=int, default=0)
    p_plan.add_argument("--baseline", choices=["first", "random"], default="first")
    p_plan.set_defaults(func=_cmd_plan)

    p_tally = sub.add_parser("tally", help="score votes against a saved plan")
    p_tally.add_argument("--plan", required=True, help="plan JSON from `plan`")
    p_tally.add_argument("--votes", required=True, help="votes JSON {comparison_id: A|B}")
    p_tally.add_argument("--token-multiplier", type=float, default=5.0)
    p_tally.add_argument("--alpha", type=float, default=0.05)
    p_tally.add_argument("--alternative", choices=["two-sided", "greater"], default="two-sided")
    p_tally.set_defaults(func=_cmd_tally)

    p_demo = sub.add_parser("demo", help="end-to-end synthetic example")
    p_demo.set_defaults(func=_cmd_demo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
