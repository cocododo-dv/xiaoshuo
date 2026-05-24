"""Plagiarism 检测:Rabin-Karp 风格 n-gram 索引 + 扩展匹配。

参见《风格参考模块重构执行手册 v1.1》§7.3。
- ngram_size: 8(短 n-gram 用于初步定位)
- threshold_chars: 12(命中后向后扩展,≥12 字符连续才算 plagiarism)

实现使用 Python dict 作 n-gram 索引(等效 Rabin-Karp 而非显式滚动哈希),
单 generated_text 扫描复杂度 O(n + sum(quote_lengths))。
"""

from __future__ import annotations

from novel_system.services.style_reference.schemas import (
    PlagiarismHit,
    PlagiarismReport,
)


def check_plagiarism(
    generated_text: str,
    profile_quotes: list[str],
    *,
    ngram_size: int = 8,
    threshold_chars: int = 12,
) -> PlagiarismReport:
    """扫描 generated_text 是否含 profile_quotes 中 ≥threshold_chars 连续匹配。"""
    if not generated_text or not profile_quotes or len(generated_text) < ngram_size:
        return PlagiarismReport(
            passed=True,
            hits=[],
            ngram_size=ngram_size,
            threshold_chars=threshold_chars,
        )

    # 构建 quote n-gram → list[(quote_idx, position_in_quote)]
    quote_ngrams: dict[str, list[tuple[int, int]]] = {}
    for qi, quote in enumerate(profile_quotes):
        if len(quote) < ngram_size:
            continue
        for j in range(len(quote) - ngram_size + 1):
            ng = quote[j : j + ngram_size]
            quote_ngrams.setdefault(ng, []).append((qi, j))

    hits: list[PlagiarismHit] = []
    n = len(generated_text)
    i = 0
    while i <= n - ngram_size:
        ng = generated_text[i : i + ngram_size]
        if ng in quote_ngrams:
            best_len = 0
            for qi, qpos in quote_ngrams[ng]:
                quote = profile_quotes[qi]
                match_len = ngram_size
                while (
                    i + match_len < n
                    and qpos + match_len < len(quote)
                    and generated_text[i + match_len] == quote[qpos + match_len]
                ):
                    match_len += 1
                if match_len > best_len:
                    best_len = match_len
            if best_len >= threshold_chars:
                hits.append(
                    PlagiarismHit(
                        matched_text=generated_text[i : i + best_len],
                        position=i,
                        matched_length=best_len,
                    )
                )
                i += best_len  # 跳过整个匹配段,避免重复报告
                continue
        i += 1

    return PlagiarismReport(
        passed=not hits,
        hits=hits,
        ngram_size=ngram_size,
        threshold_chars=threshold_chars,
    )
