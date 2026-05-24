"""按 paragraph_type 分层抽样。

依据《风格参考模块重构执行手册 v1.1》§A.3 与 PR-3 plan §"抽样策略实现":
- 每 paragraph_type 至少 `min_per_type` 段(若该 type 全量不足则全收)
- 总数不足 `target_n` 时从剩余段按 char_count 加权随机补
- 总数超 `target_n` 时按 type 多样性优先截断
- `target_n=0` 返回空 list;`paragraphs=[]` 返回空 list

对 StyleReferenceParagraph 类型友好,但接受任何含 `paragraph_type` / `char_count`
属性的对象(供测试用 dataclass mock)。
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Sequence


def stratified_sample(
    paragraphs: Sequence[Any],
    *,
    target_n: int,
    min_per_type: int = 3,
    rng: random.Random | None = None,
) -> list[Any]:
    """按 paragraph_type 分层抽样,见 module docstring。"""
    if target_n <= 0 or not paragraphs:
        return []

    rng = rng or random.Random()

    # 按 type 分桶
    buckets: dict[str, list[Any]] = defaultdict(list)
    for p in paragraphs:
        buckets[getattr(p, "paragraph_type", "narration")].append(p)

    # 每 type 先按 char_count 加权随机抽至少 min_per_type 段(or 全量)
    selected_by_type: dict[str, list[Any]] = {}
    for ptype, items in buckets.items():
        if len(items) <= min_per_type:
            selected_by_type[ptype] = list(items)
        else:
            selected_by_type[ptype] = _weighted_sample(items, min_per_type, rng)

    selected: list[Any] = [p for items in selected_by_type.values() for p in items]

    # 若总数不足 target_n,从剩余段补
    if len(selected) < target_n:
        selected_ids = {id(p) for p in selected}
        remaining = [p for p in paragraphs if id(p) not in selected_ids]
        need = target_n - len(selected)
        if remaining:
            extra = _weighted_sample(remaining, min(need, len(remaining)), rng)
            selected.extend(extra)

    # 若超 target_n,按 type 多样性截断(round-robin 各 type 选样)
    if len(selected) > target_n:
        selected = _truncate_by_type_diversity(selected, target_n)

    return selected


def _weighted_sample(items: list[Any], k: int, rng: random.Random) -> list[Any]:
    """从 items 中按 char_count 加权无放回抽 k 个。"""
    if k >= len(items):
        return list(items)
    weights = [max(1, int(getattr(p, "char_count", 1) or 1)) for p in items]
    indices = list(range(len(items)))
    chosen: list[int] = []
    pool_weights = weights.copy()
    for _ in range(k):
        if not indices:
            break
        idx = rng.choices(range(len(indices)), weights=pool_weights, k=1)[0]
        chosen.append(indices.pop(idx))
        pool_weights.pop(idx)
    return [items[i] for i in chosen]


def _truncate_by_type_diversity(selected: list[Any], target_n: int) -> list[Any]:
    """按 type round-robin 顺序保留前 target_n 个,保留 type 多样性。"""
    buckets: dict[str, list[Any]] = defaultdict(list)
    for p in selected:
        buckets[getattr(p, "paragraph_type", "narration")].append(p)
    # round-robin
    types = list(buckets.keys())
    result: list[Any] = []
    while len(result) < target_n:
        progressed = False
        for ptype in types:
            if not buckets[ptype]:
                continue
            result.append(buckets[ptype].pop(0))
            progressed = True
            if len(result) >= target_n:
                break
        if not progressed:
            break
    return result
