"""Blueprint §6 / §17 — falsifiability test for the Best-of-N adversarial DOWN-bound.

§6.2 钉死的不对称性:「对抗性指标定义的是下界,不是上界」。This test verifies exactly
that property — the machine's job per §6.3 — and deliberately claims nothing more:

  1. the adversarial ranker reliably ranks an AI-slop draft BELOW a clean revision
     of the *same* scene (the down-bound automatic initial screen);
  2. slop trips materially more *prose* AI-flavor dimensions than clean prose;
  3. Best-of-N selection (argmax adversarial_rank_score) picks the clean candidate
     out of a pool of slop + clean;
  4. candidate_dispersion behaves as the §6.3 "search-space opened?" signal
     (identical candidates ≈ 0, varied candidates clearly higher).

It does NOT assert the ranker finds the *best* prose — that up-bound is human
territory (§6.2 / §6.3 终选归人). A green run here means "the floor filter works",
not "the ceiling is reached".

This is the §17 falsifiability criterion for the §6 module: if a future change
flips polarity, drops the adversarial dims, or slips a conformity metric (one that
*rewards* regularity) into the ranker, these assertions break loudly.

Run standalone:  pytest tests/test_best_of_n_selection_validation.py -s
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from novel_system.services.literary_quality import (
    ADVERSARIAL_DIMS,
    adversarial_rank_score,
    analyze_literary_quality,
    candidate_dispersion,
)

# Structural cost/conflict dims (§4/§8) fire on atmosphere prose that has no on-page
# choice; they are part of ADVERSARIAL_DIMS by design but are NOT prose AI-flavor, so
# the "slop is more AI-flavored" assertion looks only at the prose subset.
_STRUCTURAL_DIMS = {"painless_scene", "no_choice_scene", "choice_pressure", "conflict_too_clean"}
PROSE_AI_DIMS = tuple(d for d in ADVERSARIAL_DIMS if d not in _STRUCTURAL_DIMS)


@dataclass
class Pair:
    label: str
    slop: str   # AI-flavored draft (perception filters, named emotion, monotone syntax, faux-poetic)
    clean: str  # show-don't-tell revision of the same beat


PAIRS: list[Pair] = [
    Pair(
        label="信件焚毁的告别",
        slop=(
            "他觉得心口发闷,悲伤涌了上来。他看到她转身,心里一片冰凉。"
            "他意识到自己错了,却已经太迟。他知道,一切都无法挽回。"
            "他叹了口气,仿佛命运早已注定。一切都变得不同了。"
        ),
        clean=(
            "风从窗缝钻进来,吹得烛火歪了歪。林远把那封信折好,又展开,"
            "指节压过纸面的折痕。“你早就料到了。”苏晚没有回头。"
            "他没有答话,只把信凑近火苗,看纸角卷起焦黑,再一点点吞掉墨迹。"
            "灰落在桌上,积成薄薄一层。"
        ),
    ),
    Pair(
        label="门外脚步的逼近",
        slop=(
            "她感到一阵恐惧,浑身发冷。她看到门开了,她意识到危险。"
            "她知道必须逃走,却动弹不得。她转身,慌乱地想跑。"
            "她叹了口气,仿佛命运在催促。一切都变得模糊。"
        ),
        clean=(
            "门轴吱呀响了一声。苏晚的手停在半空,茶杯沿还贴着下唇。"
            "走廊尽头的脚步声不紧不慢,一下,又一下。她把杯子搁回桌面,"
            "没发出声音,指尖却把桌布攥出了褶。"
        ),
    ),
    Pair(
        label="战后归来的重逢",
        slop=(
            "他觉得疲惫不堪,悲伤压在胸口。他看到家门,他感到一阵酸楚。"
            "他知道一切都回不去了。他低头,沉默了片刻。"
            "他点头,仿佛命运早已写好。一切都变得遥远。"
        ),
        clean=(
            "门没锁。林远用肩膀抵开它,血痂在袖口结成硬壳。"
            "灶台是凉的,锅底积了一层灰。他蹲下去,伸手探了探那点早就熄了的余烬,"
            "又把空了的米缸盖子轻轻搁回原处。"
        ),
    ),
]

MARGIN_FLOOR = 0.08  # clean must outrank slop by at least this much


class TestBestOfNDownBound:

    @pytest.mark.parametrize("pair", PAIRS, ids=[p.label for p in PAIRS])
    def test_clean_outranks_slop(self, pair: Pair) -> None:
        slop_score = adversarial_rank_score(pair.slop)
        clean_score = adversarial_rank_score(pair.clean)
        assert clean_score > slop_score + MARGIN_FLOOR, (
            f"{pair.label}: ranker failed the down-bound — "
            f"clean={clean_score:.4f} slop={slop_score:.4f}"
        )

    @pytest.mark.parametrize("pair", PAIRS, ids=[p.label for p in PAIRS])
    def test_slop_trips_more_prose_dims(self, pair: Pair) -> None:
        slop_sig, _ = analyze_literary_quality(pair.slop)
        clean_sig, _ = analyze_literary_quality(pair.clean)
        slop_hits = [d for d in PROSE_AI_DIMS if slop_sig.get(d, {}).get("risk")]
        clean_hits = [d for d in PROSE_AI_DIMS if clean_sig.get(d, {}).get("risk")]
        assert len(slop_hits) >= 3, f"{pair.label}: slop only tripped {slop_hits}"
        assert clean_hits == [], f"{pair.label}: clean tripped prose dims {clean_hits}"

    def test_best_of_n_selects_clean(self, capsys) -> None:
        """argmax adversarial_rank_score over [slop, slop, clean] must pick clean."""
        rows: list[str] = []
        for pair in PAIRS:
            other = next(p for p in PAIRS if p is not pair)
            candidates = [pair.slop, other.slop, pair.clean]
            scores = [adversarial_rank_score(c) for c in candidates]
            best = max(range(len(candidates)), key=lambda i: scores[i])
            rows.append(
                f"  [{pair.label}] scores={[round(s, 3) for s in scores]} -> pick #{best} "
                f"({'CLEAN' if best == 2 else 'SLOP'})"
            )
            assert best == 2, f"{pair.label}: Best-of-N picked a slop candidate {scores}"
        with capsys.disabled():
            print("\n  Best-of-N down-bound selection:\n" + "\n".join(rows))

    def test_dispersion_signal(self) -> None:
        """§6.3 dispersion: identical candidates ≈ 0; varied candidates clearly higher."""
        identical = candidate_dispersion([PAIRS[0].clean, PAIRS[0].clean, PAIRS[0].clean])
        varied = candidate_dispersion([PAIRS[0].clean, PAIRS[1].clean, PAIRS[2].clean])
        assert identical <= 0.01, f"identical candidates should be ~0, got {identical}"
        assert varied > identical, f"varied={varied} should exceed identical={identical}"

    def test_ranker_is_a_floor_not_a_ceiling(self) -> None:
        """§6.2 honesty: a clean draft is not forced to a perfect score.

        The adversarial ranker certifies "few AI-flavor signals" (the floor), not
        literary excellence (the ceiling). Clean prose can sit well below 1.0 — that
        residual is exactly the space §6.3 hands to human 终选, and asserting otherwise
        would be overclaiming. We only require clean prose to clear a sane floor.
        """
        for pair in PAIRS:
            score = adversarial_rank_score(pair.clean)
            assert 0.5 <= score < 1.0, (
                f"{pair.label}: clean score {score:.4f} — ranker should certify a floor, "
                f"not assert perfection"
            )
