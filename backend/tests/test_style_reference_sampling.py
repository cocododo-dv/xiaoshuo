"""sampling.py 单测:分层抽样 / min_per_type / target_n 不足时补 / 截断。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略(PR-3)"。
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

import pytest

from novel_system.services.style_reference.sampling import stratified_sample


@dataclass
class FakeParagraph:
    paragraph_id: str
    paragraph_type: str
    char_count: int


def _make_paragraphs(spec: dict[str, int], char_count: int = 200) -> list[FakeParagraph]:
    paras: list[FakeParagraph] = []
    idx = 0
    for ptype, count in spec.items():
        for _ in range(count):
            paras.append(FakeParagraph(f"p_{idx}", ptype, char_count))
            idx += 1
    return paras


def test_empty_paragraphs_returns_empty() -> None:
    assert stratified_sample([], target_n=10) == []


def test_target_zero_returns_empty() -> None:
    paras = _make_paragraphs({"narration": 5})
    assert stratified_sample(paras, target_n=0) == []


def test_min_per_type_three_each() -> None:
    paras = _make_paragraphs({"dialogue": 10, "narration": 10, "psychology": 10})
    rng = random.Random(42)
    result = stratified_sample(paras, target_n=15, min_per_type=3, rng=rng)
    counter = Counter(p.paragraph_type for p in result)
    # 每 type 至少 3 段
    for ptype in ("dialogue", "narration", "psychology"):
        assert counter[ptype] >= 3, f"{ptype} 仅 {counter[ptype]} 段,不足 min_per_type=3"
    assert len(result) == 15


def test_type_under_min_takes_all() -> None:
    """某 type 全量段数 < min_per_type 时,该 type 应全收。"""
    paras = _make_paragraphs({"dialogue": 2, "narration": 10})
    rng = random.Random(42)
    result = stratified_sample(paras, target_n=10, min_per_type=3, rng=rng)
    counter = Counter(p.paragraph_type for p in result)
    assert counter["dialogue"] == 2  # 全量
    assert counter["narration"] >= 3


def test_total_below_target_fills_to_target() -> None:
    """每 type 抽 min_per_type 后总数 < target_n,应从剩余继续补。"""
    paras = _make_paragraphs({"dialogue": 10, "narration": 10})  # 总 20 段
    rng = random.Random(42)
    result = stratified_sample(paras, target_n=15, min_per_type=3, rng=rng)
    assert len(result) == 15


def test_total_above_target_truncates_keeps_diversity() -> None:
    """初步选了 >target_n 段时按 type 多样性截断。"""
    paras = _make_paragraphs({"a": 5, "b": 5, "c": 5})  # 三 type 各 3 段 = 9
    rng = random.Random(42)
    result = stratified_sample(paras, target_n=5, min_per_type=3, rng=rng)
    counter = Counter(p.paragraph_type for p in result)
    assert len(result) == 5
    # 至少 2 个 type 出现(round-robin 多样性)
    assert len(counter) >= 2


def test_rng_determinism() -> None:
    """同 seed 的 rng 应产出同结果(可重复测试)。"""
    paras = _make_paragraphs({"dialogue": 8, "narration": 8})
    first = stratified_sample(paras, target_n=10, rng=random.Random(123))
    second = stratified_sample(paras, target_n=10, rng=random.Random(123))
    assert [p.paragraph_id for p in first] == [p.paragraph_id for p in second]


def test_min_per_type_zero_works() -> None:
    paras = _make_paragraphs({"dialogue": 5, "narration": 5})
    result = stratified_sample(paras, target_n=4, min_per_type=0, rng=random.Random(7))
    assert len(result) == 4


def test_char_count_weighted() -> None:
    """char_count 大的段被选中概率更高(经验性)。"""
    paras = [FakeParagraph(f"p_{i}", "narration", char_count=10) for i in range(5)]
    paras.append(FakeParagraph("p_heavy", "narration", char_count=10000))
    # 多次抽样验证 heavy 段在 100 次抽样中至少出现 50% 以上
    rng = random.Random(0)
    hits = 0
    for _ in range(100):
        result = stratified_sample(paras, target_n=1, min_per_type=0, rng=rng)
        if result and result[0].paragraph_id == "p_heavy":
            hits += 1
    # 10000 vs 5*10 = 50,权重比 200:1,1 次抽样 hit 概率应远超 50%
    assert hits >= 50, f"heavy paragraph only hit {hits}/100 — weighting may be broken"
