"""Quantitative validation 单测(PR-7 §7.2)。"""

from __future__ import annotations

from dataclasses import dataclass

from novel_system.services.style_reference.metrics import METRIC_NAMES
from novel_system.services.style_reference.validation.quantitative import check_quantitative


@dataclass
class _FakeProfile:
    """轻量 stub,只保留 check_quantitative 用到的 profile_json 属性。"""

    profile_json: dict


def _profile_with_baseline(metrics_baseline: dict) -> _FakeProfile:
    return _FakeProfile(profile_json={"metrics_baseline": metrics_baseline})


def test_empty_generated_returns_empty() -> None:
    profile = _profile_with_baseline(
        {"avg_sentence_length": {"mean": 18.0, "std": 4.0}}
    )
    assert check_quantitative("", profile) == []


def test_missing_baseline_returns_empty() -> None:
    profile = _FakeProfile(profile_json={})
    text = "一段不太长的中文文本。"
    assert check_quantitative(text, profile) == []


def test_metric_within_tolerance_passes() -> None:
    """generated 与 baseline avg_sentence_length 相近 → passed=True。"""
    profile = _profile_with_baseline(
        {"avg_sentence_length": {"mean": 10.0, "std": 5.0}}
    )
    text = "甲乙丙丁戊。子丑寅卯辰巳午未申。"  # 句长 5, 9 → 平均 7
    reports = check_quantitative(text, profile)
    avg = next(r for r in reports if r.metric == "avg_sentence_length")
    assert avg.passed
    assert avg.tolerance >= 6.25  # 5.0 * 1.25 floor 之外


def test_metric_far_outside_tolerance_fails() -> None:
    """生成 avg_sentence_length=4 vs baseline mean=30 std=1 → deviation 远超 tolerance。"""
    profile = _profile_with_baseline(
        {"avg_sentence_length": {"mean": 30.0, "std": 1.0}}
    )
    text = "短。还短。"
    reports = check_quantitative(text, profile)
    avg = next(r for r in reports if r.metric == "avg_sentence_length")
    assert not avg.passed
    assert avg.deviation_ratio > 1.0


def test_floor_fallback_when_std_zero() -> None:
    """std=0 时 tolerance 仍 ≥ floor(避免除以零或过严)。"""
    floors = {"avg_sentence_length": 3.0}
    profile = _profile_with_baseline(
        {"avg_sentence_length": {"mean": 10.0, "std": 0.0}}
    )
    text = "一句话。"
    reports = check_quantitative(text, profile, floors=floors)
    avg = next(r for r in reports if r.metric == "avg_sentence_length")
    assert avg.tolerance >= 3.0


def test_two_profiles_yield_different_tolerances() -> None:
    """同段文本对不同 std 的 baseline,tolerance 不同。"""
    tight = _profile_with_baseline(
        {"avg_sentence_length": {"mean": 10.0, "std": 1.0}}
    )
    loose = _profile_with_baseline(
        {"avg_sentence_length": {"mean": 10.0, "std": 8.0}}
    )
    text = "一段普通的中文文本句子。"
    tight_avg = next(
        r for r in check_quantitative(text, tight) if r.metric == "avg_sentence_length"
    )
    loose_avg = next(
        r for r in check_quantitative(text, loose) if r.metric == "avg_sentence_length"
    )
    assert loose_avg.tolerance > tight_avg.tolerance


def test_dimension_routing() -> None:
    """dimension 按 metric 归类:sensory_* → scene;ratio 类 → narrative;其余 → language。"""
    profile = _profile_with_baseline(
        {
            "avg_sentence_length": {"mean": 10.0, "std": 3.0},
            "dialogue_ratio": {"mean": 0.3, "std": 0.1},
            "sensory_visual_per_1k": {"mean": 5.0, "std": 2.0},
        }
    )
    text = "他低头看着脚下的路,一阵阵的寒意。"
    reports = check_quantitative(text, profile)
    by_metric = {r.metric: r.dimension for r in reports}
    assert by_metric["avg_sentence_length"] == "language"
    assert by_metric["dialogue_ratio"] == "narrative"
    assert by_metric["sensory_visual_per_1k"] == "scene"
