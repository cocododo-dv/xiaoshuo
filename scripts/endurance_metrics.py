"""长篇耐久分层指标收集器（结果闭环治理设计 §8 Wave 7 项 1/2 + §9.4/§10）。

把多章耐久运行报告聚合为**每五章**指标 + **按模型分层**基线，并对 Wave 7 完成门做
可证伪断言。真实 30 章模型跑归 §9.3 发布门（本机不可跑真实模型）；本收集器是那次
运行的判定逻辑，纯 Python、离线可测。

输入报告 schema（harness 产出，最小约定）::

    {
      "chapters": [
        {"chapter_index": 1, "model": "gpt-5-mini", "archived": true,
         "scenes": [{"archived": true, "tokens": 5000}, ...],
         "continuity_errors": 0, "q0_q1_unresolved": 0, "source_leak": 0,
         "voice_drift": [{"severity": "high", "resolved": false}, ...],
         "cross_chapter_repetition": [{"severity": "high"}, ...],
         "foreshadow_debt": 2},
        ...
      ],
      "db_size_samples": [{"after_chapter": 5, "bytes": 1000000}, ...],
      "latency_p95_ms": {"catalog": 800, "scene_state": 900, "chapter_manuscript": 1200}
    }

Wave 7 完成门（§8 Wave7 完成门 / §9.4）：
- 全 N 章后端归档；Q0/Q1 与来源泄漏均 0；
- 无未处理高严重度声音漂移 / 跨章自我重复；
- 第 21–30 章平均 tokens_per_archived_scene ≤ 第 1–10 章的 1.5×；
- 目录/场景状态/章节成稿三读取接口 p95 < 2s。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

TOKENS_RATIO_CAP = 1.5
P95_CAP_MS = 2000
READ_ENDPOINTS = ("catalog", "scene_state", "chapter_manuscript")


def _archived_scene_tokens(chapters: list[dict[str, Any]]) -> tuple[int, int]:
    """返回（归档场景数, 归档场景总 tokens）。"""
    scenes = 0
    tokens = 0
    for ch in chapters:
        for sc in ch.get("scenes") or []:
            if sc.get("archived"):
                scenes += 1
                tokens += int(sc.get("tokens") or 0)
    return scenes, tokens


def tokens_per_archived_scene(chapters: list[dict[str, Any]]) -> float | None:
    scenes, tokens = _archived_scene_tokens(chapters)
    return (tokens / scenes) if scenes else None


def bucket_by_five(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 chapter_index 每五章分桶，输出桶级指标。"""
    ordered = sorted(chapters, key=lambda c: int(c.get("chapter_index", 0)))
    buckets: list[dict[str, Any]] = []
    for start in range(0, len(ordered), 5):
        window = ordered[start : start + 5]
        if not window:
            continue
        scenes, tokens = _archived_scene_tokens(window)
        buckets.append({
            "chapters": [int(c.get("chapter_index", 0)) for c in window],
            "archived_scene_count": scenes,
            "tokens_per_archived_scene": (tokens / scenes) if scenes else None,
            "continuity_errors": sum(int(c.get("continuity_errors") or 0) for c in window),
            "foreshadow_debt": sum(int(c.get("foreshadow_debt") or 0) for c in window),
            "high_voice_drift_unresolved": _count_high(window, "voice_drift", require_unresolved=True),
            "high_cross_chapter_repetition": _count_high(window, "cross_chapter_repetition"),
        })
    return buckets


def _count_high(chapters: list[dict[str, Any]], key: str, *, require_unresolved: bool = False) -> int:
    total = 0
    for ch in chapters:
        for item in ch.get(key) or []:
            if str(item.get("severity", "")).lower() != "high":
                continue
            if require_unresolved and item.get("resolved"):
                continue
            total += 1
    return total


def stratify_by_model(chapters: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按模型分层记漂移/重复基线（§8 项 2：低价模型须分层，避免跨模型混杂误报）。"""
    by_model: dict[str, dict[str, Any]] = {}
    for ch in chapters:
        model = str(ch.get("model") or "unknown")
        entry = by_model.setdefault(model, {
            "chapter_count": 0,
            "high_voice_drift_unresolved": 0,
            "high_cross_chapter_repetition": 0,
        })
        entry["chapter_count"] += 1
        entry["high_voice_drift_unresolved"] += _count_high([ch], "voice_drift", require_unresolved=True)
        entry["high_cross_chapter_repetition"] += _count_high([ch], "cross_chapter_repetition")
    return by_model


def evaluate_endurance(report: dict[str, Any], *, total_chapters: int = 30) -> dict[str, Any]:
    chapters = list(report.get("chapters") or [])
    failures: list[str] = []

    # 1) 全 N 章归档
    archived = [c for c in chapters if c.get("archived")]
    if len(chapters) < total_chapters or len(archived) < total_chapters:
        failures.append(
            f"CHAPTER_COVERAGE_SHORTFALL: archived {len(archived)}/{total_chapters}"
        )

    # 2) Q0/Q1 与来源泄漏 0
    q0q1 = sum(int(c.get("q0_q1_unresolved") or 0) for c in chapters)
    leaks = sum(int(c.get("source_leak") or 0) for c in chapters)
    if q0q1:
        failures.append(f"Q0_Q1_UNRESOLVED: {q0q1}")
    if leaks:
        failures.append(f"SOURCE_LEAK: {leaks}")

    # 3) 无未处理高严重度声音漂移 / 跨章重复
    drift = _count_high(chapters, "voice_drift", require_unresolved=True)
    repetition = _count_high(chapters, "cross_chapter_repetition")
    if drift:
        failures.append(f"HIGH_VOICE_DRIFT_UNRESOLVED: {drift}")
    if repetition:
        failures.append(f"HIGH_CROSS_CHAPTER_REPETITION: {repetition}")

    # 4) tokens 比：21–30 ≤ 1.5× 1–10
    def _window(lo: int, hi: int) -> list[dict[str, Any]]:
        return [c for c in chapters if lo <= int(c.get("chapter_index", 0)) <= hi]

    early = tokens_per_archived_scene(_window(1, 10))
    late = tokens_per_archived_scene(_window(21, 30))
    ratio = None
    if early and late:
        ratio = late / early
        if ratio > TOKENS_RATIO_CAP:
            failures.append(
                f"TOKENS_PER_SCENE_REGRESSION: 21-30 avg {late:.0f} > {TOKENS_RATIO_CAP}× 1-10 avg {early:.0f}"
            )

    # 5) 三读取接口 p95 < 2s
    p95 = report.get("latency_p95_ms") or {}
    for ep in READ_ENDPOINTS:
        val = p95.get(ep)
        if val is not None and float(val) >= P95_CAP_MS:
            failures.append(f"P95_TOO_SLOW: {ep}={val}ms >= {P95_CAP_MS}ms")

    return {
        "passed": not failures,
        "failures": failures,
        "total_chapters_expected": total_chapters,
        "chapters_archived": len(archived),
        "tokens_ratio_21_30_vs_1_10": ratio,
        "buckets": bucket_by_five(chapters),
        "by_model": stratify_by_model(chapters),
        "db_size_samples": report.get("db_size_samples") or [],
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="长篇耐久分层指标收集器（Wave 7 §8）")
    parser.add_argument("report", help="运行报告 JSON 路径")
    parser.add_argument("--total-chapters", type=int, default=30)
    parser.add_argument("--out", help="判定 JSON 输出路径")
    args = parser.parse_args(argv)
    with open(args.report, encoding="utf-8") as f:
        report = json.load(f)
    verdict = evaluate_endurance(report, total_chapters=args.total_chapters)
    text = json.dumps(verdict, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
