"""Plagiarism 检测:规范化 n-gram 索引 + 扩展匹配。

参见《风格参考模块重构执行手册 v1.1》§7.3。
- ngram_size: 8(规范化后字符,短 n-gram 用于初步定位)
- threshold_chars: 12(命中后向后扩展,规范化后 ≥12 字符连续才算 plagiarism)

两个关键设计:
1. **规范化匹配** — 比较前去除空白与标点(Unicode P* 类别)并统一小写,
   防止「插空格 / 换标点」式微改绕过;命中位置通过偏移映射回原文。
2. **倒排索引建在 generated_text 上** — generated(通常 1-3k 字)远小于
   语料(全书段落,可达 30 万字)。对小文本建 n-gram dict、对语料单遍扫描,
   复杂度 O(len(generated) + sum(corpus_lengths)),全书语料也不超预算。
"""

from __future__ import annotations

import unicodedata

from novel_system.services.style_reference.schemas import (
    PlagiarismHit,
    PlagiarismReport,
)


def _is_ignorable(ch: str) -> bool:
    """规范化时丢弃的字符:空白 + 标点/符号(Unicode P* / S* 类别)。"""
    if ch.isspace():
        return True
    cat = unicodedata.category(ch)
    return cat.startswith("P") or cat.startswith("S")


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """返回 (规范化文本, 每个规范化字符在原文中的下标)。"""
    chars: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(text):
        if _is_ignorable(ch):
            continue
        chars.append(ch.lower())
        index_map.append(i)
    return "".join(chars), index_map


def normalize_text_for_matching(text: str) -> str:
    """Normalize by lowering and stripping whitespace/punctuation for comparison."""
    return "".join(ch.lower() for ch in text if not _is_ignorable(ch))


_normalize = normalize_text_for_matching


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """合并重叠/相邻的 [start, end) 区间,保持升序。"""
    if not intervals:
        return []
    intervals.sort()
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def check_plagiarism(
    generated_text: str,
    corpus_texts: list[str],
    *,
    ngram_size: int = 8,
    threshold_chars: int = 12,
) -> PlagiarismReport:
    """扫描 generated_text 是否与 corpus_texts(全书段落)存在
    规范化后 ≥threshold_chars 的连续重叠。"""
    empty = PlagiarismReport(
        passed=True,
        hits=[],
        ngram_size=ngram_size,
        threshold_chars=threshold_chars,
    )
    if not generated_text or not corpus_texts:
        return empty

    gen_norm, gen_map = _normalize_with_map(generated_text)
    if len(gen_norm) < ngram_size:
        return empty

    # 倒排索引:generated 的 n-gram → 规范化起点列表
    gen_ngrams: dict[str, list[int]] = {}
    for i in range(len(gen_norm) - ngram_size + 1):
        gen_ngrams.setdefault(gen_norm[i : i + ngram_size], []).append(i)

    # 对每段语料单遍扫描;命中区间记录在 generated 的规范化坐标系
    hit_intervals: list[tuple[int, int]] = []
    for corpus in corpus_texts:
        if not corpus:
            continue
        c_norm = _normalize(corpus)
        if len(c_norm) < ngram_size:
            continue
        j = 0
        while j <= len(c_norm) - ngram_size:
            window = c_norm[j : j + ngram_size]
            positions = gen_ngrams.get(window)
            if positions is None:
                j += 1
                continue
            best_len = 0
            for gpos in positions:
                match_len = ngram_size
                while (
                    j + match_len < len(c_norm)
                    and gpos + match_len < len(gen_norm)
                    and c_norm[j + match_len] == gen_norm[gpos + match_len]
                ):
                    match_len += 1
                if match_len >= threshold_chars:
                    hit_intervals.append((gpos, gpos + match_len))
                if match_len > best_len:
                    best_len = match_len
            # 跳过已匹配段,避免同一重叠重复报告
            j += best_len if best_len >= threshold_chars else 1

    if not hit_intervals:
        return empty

    hits: list[PlagiarismHit] = []
    for norm_start, norm_end in _merge_intervals(hit_intervals):
        orig_start = gen_map[norm_start]
        orig_end = gen_map[norm_end - 1] + 1
        hits.append(
            PlagiarismHit(
                matched_text=generated_text[orig_start:orig_end],
                position=orig_start,
                matched_length=norm_end - norm_start,
            )
        )

    return PlagiarismReport(
        passed=False,
        hits=hits,
        ngram_size=ngram_size,
        threshold_chars=threshold_chars,
    )
