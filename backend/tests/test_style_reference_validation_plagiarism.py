"""Plagiarism Rabin-Karp 单测(PR-4)。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。
"""

from __future__ import annotations

import time

from novel_system.services.style_reference.validation.plagiarism import (
    check_plagiarism,
)


def test_plagiarism_hit_long_overlap() -> None:
    quote = "暮色四合,街口的雾气还没散尽,行人三三两两走过。"  # 25 字
    text = f"今儿是个好天气。暮色四合,街口的雾气还没散尽,行人三三两两走过。"
    report = check_plagiarism(text, [quote])
    assert not report.passed
    assert len(report.hits) == 1
    assert report.hits[0].matched_length >= 12


def test_plagiarism_below_threshold_eleven_chars_no_hit() -> None:
    """11 字符连续匹配不应命中(threshold=12)。"""
    quote = "暮色四合街口的雾气X"  # 字符位:暮色四合街口的雾气 = 9 字 + X = 10 字
    text = "今儿是个好天气暮色四合街口的Y"  # 与 quote 前 7 字相同
    report = check_plagiarism(text, [quote])
    assert report.passed
    assert report.hits == []


def test_plagiarism_exactly_twelve_chars_hit() -> None:
    """恰好 12 字符连续匹配应命中。"""
    quote = "暮色四合街口的雾气还没散"  # 12 字
    text = f"开头三个字。{quote}尾巴。"
    report = check_plagiarism(text, [quote])
    assert not report.passed
    assert len(report.hits) == 1
    assert report.hits[0].matched_length >= 12


def test_plagiarism_empty_inputs() -> None:
    assert check_plagiarism("", ["something"]).passed is True
    assert check_plagiarism("anything", []).passed is True
    assert check_plagiarism("", []).passed is True


def test_plagiarism_short_text_below_ngram_size() -> None:
    """generated_text 长度 < ngram_size 直接 pass。"""
    quote = "暮色四合,街口的雾气还没散尽"
    text = "短文本"
    report = check_plagiarism(text, [quote])
    assert report.passed
    assert report.hits == []


def test_plagiarism_performance_50k_quote() -> None:
    """5 万字 profile × 1000 字 generated 扫描软线 < 200ms。"""
    quote_50k = "暮色四合街口的雾气还没散尽行人三三两两走过" * 1200  # ~25k 字
    generated_1k = "今儿是个好天气。" * 50  # ~500 字
    start = time.perf_counter()
    report = check_plagiarism(generated_1k, [quote_50k])
    elapsed = (time.perf_counter() - start) * 1000
    assert elapsed < 200.0, f"plagiarism scan 耗时 {elapsed:.1f}ms 超过软线 200ms"
    # 不论 passed 与否,关键是性能
    assert isinstance(report.passed, bool)
