"""Wave 7（§8 项 1/2 + §9.4）：长篇耐久分层指标收集器判定逻辑（离线可测）。

真实 30 章模型跑归发布门；本测试锁定收集器的分桶/分层/完成门断言极性。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load():
    path = Path(__file__).resolve().parents[2] / "scripts" / "endurance_metrics.py"
    spec = importlib.util.spec_from_file_location("endurance_metrics", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


em = _load()


def _chapter(idx, *, model="gpt-5-mini", tokens=5000, scenes=3, drift_high_unresolved=0,
             repetition_high=0, q0q1=0, leak=0):
    return {
        "chapter_index": idx, "model": model, "archived": True,
        "scenes": [{"archived": True, "tokens": tokens} for _ in range(scenes)],
        "continuity_errors": 0, "q0_q1_unresolved": q0q1, "source_leak": leak,
        "foreshadow_debt": 0,
        "voice_drift": [{"severity": "high", "resolved": False}] * drift_high_unresolved,
        "cross_chapter_repetition": [{"severity": "high"}] * repetition_high,
    }


def _clean_report(tokens_early=5000, tokens_late=5000):
    chapters = []
    for i in range(1, 31):
        tok = tokens_early if i <= 10 else tokens_late if i >= 21 else 5000
        chapters.append(_chapter(i, tokens=tok))
    return {
        "chapters": chapters,
        "latency_p95_ms": {"catalog": 800, "scene_state": 900, "chapter_manuscript": 1500},
        "db_size_samples": [{"after_chapter": 5, "bytes": 10 ** 6}],
    }


def test_clean_30_chapter_report_passes():
    verdict = em.evaluate_endurance(_clean_report())
    assert verdict["passed"] is True
    assert verdict["failures"] == []
    assert verdict["chapters_archived"] == 30


def test_token_regression_fails():
    # 21–30 平均是 1–10 的 2× > 1.5× 上限
    verdict = em.evaluate_endurance(_clean_report(tokens_early=4000, tokens_late=8000))
    assert verdict["passed"] is False
    assert any("TOKENS_PER_SCENE_REGRESSION" in f for f in verdict["failures"])
    assert verdict["tokens_ratio_21_30_vs_1_10"] == pytest.approx(2.0)


def test_token_ratio_within_cap_passes():
    # 1.5× 恰好不超（4000 → 6000）
    verdict = em.evaluate_endurance(_clean_report(tokens_early=4000, tokens_late=6000))
    assert not any("TOKENS_PER_SCENE_REGRESSION" in f for f in verdict["failures"])


def test_high_unresolved_voice_drift_fails():
    report = _clean_report()
    report["chapters"][25]["voice_drift"] = [{"severity": "high", "resolved": False}]
    verdict = em.evaluate_endurance(report)
    assert verdict["passed"] is False
    assert any("HIGH_VOICE_DRIFT_UNRESOLVED" in f for f in verdict["failures"])


def test_resolved_drift_does_not_fail():
    report = _clean_report()
    report["chapters"][25]["voice_drift"] = [{"severity": "high", "resolved": True}]
    verdict = em.evaluate_endurance(report)
    assert not any("HIGH_VOICE_DRIFT" in f for f in verdict["failures"])


def test_chapter_shortfall_fails():
    report = _clean_report()
    report["chapters"] = report["chapters"][:20]  # 只 20 章
    verdict = em.evaluate_endurance(report)
    assert verdict["passed"] is False
    assert any("CHAPTER_COVERAGE_SHORTFALL" in f for f in verdict["failures"])


def test_p95_too_slow_fails():
    report = _clean_report()
    report["latency_p95_ms"]["chapter_manuscript"] = 2500
    verdict = em.evaluate_endurance(report)
    assert verdict["passed"] is False
    assert any("P95_TOO_SLOW" in f and "chapter_manuscript" in f for f in verdict["failures"])


def test_q0q1_and_leak_fail():
    report = _clean_report()
    report["chapters"][3]["q0_q1_unresolved"] = 1
    report["chapters"][4]["source_leak"] = 2
    verdict = em.evaluate_endurance(report)
    assert any("Q0_Q1_UNRESOLVED" in f for f in verdict["failures"])
    assert any("SOURCE_LEAK" in f for f in verdict["failures"])


def test_bucket_by_five_makes_six_buckets():
    buckets = em.bucket_by_five(_clean_report()["chapters"])
    assert len(buckets) == 6
    assert buckets[0]["chapters"] == [1, 2, 3, 4, 5]
    assert buckets[-1]["chapters"] == [26, 27, 28, 29, 30]


def test_stratify_by_model_no_cross_mixing():
    chapters = [
        _chapter(1, model="gpt-5-mini", drift_high_unresolved=1),
        _chapter(2, model="gpt-5", repetition_high=1),
    ]
    by_model = em.stratify_by_model(chapters)
    assert by_model["gpt-5-mini"]["high_voice_drift_unresolved"] == 1
    assert by_model["gpt-5-mini"]["high_cross_chapter_repetition"] == 0
    assert by_model["gpt-5"]["high_cross_chapter_repetition"] == 1
    assert by_model["gpt-5"]["high_voice_drift_unresolved"] == 0
