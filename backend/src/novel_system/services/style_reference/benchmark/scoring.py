"""风格基准结果矩阵、泄漏守卫、自动评分与盲评包。"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import statistics
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from novel_system.services.style_reference.benchmark.features import (
    HiddenStyleEvaluator,
)
from novel_system.services.style_reference.benchmark.manifest import (
    BenchmarkCase,
    StyleBenchmarkBundle,
    StyleBenchmarkError,
    canonical_json,
    hash_text,
)
from novel_system.services.style_reference.validation.plagiarism import (
    check_plagiarism,
    normalize_text_for_matching,
)


STYLE_BENCHMARK_RESULTS_SCHEMA_VERSION = 1
PROMPT_LEAK_NGRAM_CHARS = 12
DEFAULT_THRESHOLDS = {
    "reference_macro_accuracy": 0.65,
    "style_attribution_accuracy": 0.65,
    "style_attribution_min_per_author": 0.60,
    "paired_contrast_accuracy": 0.65,
    "paired_contrast_min_per_author": 0.60,
    "styled_non_neutral_rate": 1.0,
    "content_preservation_mean": 0.9,
    "content_full_pass_rate": 1.0,
    "length_full_pass_rate": 1.0,
    "plagiarism_pass_rate": 1.0,
    "prompt_leakage_pass_rate": 1.0,
    "identity_blinding_pass_rate": 1.0,
    "module_lineage_coverage": 1.0,
}


@dataclass(frozen=True, slots=True)
class GenerationSample:
    case_id: str
    arm: str
    target_author_id: str | None
    generated_text: str
    actual_prompt_text: str | None
    generation_metadata: dict[str, Any]

    @property
    def key(self) -> tuple[str, str, str]:
        return self.case_id, self.arm, self.target_author_id or ""

    @property
    def text_hash(self) -> str:
        return hash_text(self.generated_text)


def score_style_benchmark(
    bundle: StyleBenchmarkBundle,
    results_source: str | Path | Mapping[str, Any],
    *,
    thresholds: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """评分隐藏矩阵；报告只保留隐藏语料哈希与聚合量，不回显留出正文。"""

    samples = load_generation_results(bundle, results_source)
    evaluator = HiddenStyleEvaluator(
        {hidden.author_id: hidden.holdout_works for hidden in bundle.hidden_authors}
    )
    calibration = evaluator.calibration_report()
    leak_guard = _PromptLeakGuard(bundle)
    identity_guard = _IdentityLeakGuard(bundle)
    reference_texts = [
        work.text for author in bundle.public.authors for work in author.train_works
    ] + [work.text for author in bundle.hidden_authors for work in author.holdout_works]
    neutral_by_case = {
        sample.case_id: sample for sample in samples if sample.arm == "neutral"
    }
    scored: list[dict[str, Any]] = []
    for sample in samples:
        case = bundle.public.case_for(sample.case_id)
        predicted_author, similarities = evaluator.classify(sample.generated_text)
        prompt_leakage = leak_guard.inspect(sample.actual_prompt_text)
        identity_blinding = identity_guard.inspect(sample.actual_prompt_text)
        plagiarism = check_plagiarism(sample.generated_text, reference_texts)
        content = _content_preservation(case, sample.generated_text)
        length_score = _length_score(case, sample.generated_text)
        lineage = _lineage_check(bundle, sample, neutral_by_case)
        target_margin = None
        attributed_correctly = None
        if sample.target_author_id is not None:
            target_score = similarities[sample.target_author_id]
            decoy_score = max(
                score
                for author_id, score in similarities.items()
                if author_id != sample.target_author_id
            )
            target_margin = round(target_score - decoy_score, 6)
            attributed_correctly = predicted_author == sample.target_author_id
        scored.append(
            {
                "case_id": sample.case_id,
                "arm": sample.arm,
                "target_author_id": sample.target_author_id,
                "generated_text_sha256": sample.text_hash,
                # 只改换行、空白或标点不能证明风格模块真的改写了正文。保留
                # 原始哈希用于血缘审计，同时用与抄袭守卫相同的规范化规则
                # 生成第二个哈希，专门识别“中性稿仅重新排版”的假阳性。
                "generated_normalized_sha256": hash_text(
                    normalize_text_for_matching(sample.generated_text)
                ),
                "generated_char_count": _visible_char_count(sample.generated_text),
                "predicted_author_id": predicted_author,
                "similarities": similarities,
                "target_margin": target_margin,
                "attributed_correctly": attributed_correctly,
                "content_preservation": content,
                "length_score": length_score,
                "plagiarism": {
                    "passed": plagiarism.passed,
                    "hit_count": len(plagiarism.hits),
                    "max_matched_chars": max(
                        (hit.matched_length for hit in plagiarism.hits), default=0
                    ),
                    "threshold_chars": plagiarism.threshold_chars,
                },
                "prompt_leakage": prompt_leakage,
                "identity_blinding": identity_blinding,
                "module_lineage": lineage,
                "generation_metadata": _safe_generation_metadata(
                    sample.generation_metadata
                ),
            }
        )

    summary = _aggregate(bundle, scored)
    effective_thresholds = _effective_thresholds(thresholds)
    gates = {
        "reference_calibrated": float(calibration["macro_accuracy"])
        >= effective_thresholds["reference_macro_accuracy"],
        "style_attribution": summary["style_attribution_accuracy"]
        >= effective_thresholds["style_attribution_accuracy"],
        "balanced_style_attribution": summary["style_attribution_min_per_author"]
        >= effective_thresholds["style_attribution_min_per_author"],
        "paired_contrast": summary["paired_contrast_accuracy"]
        >= effective_thresholds["paired_contrast_accuracy"],
        "balanced_paired_contrast": summary["paired_contrast_min_per_author"]
        >= effective_thresholds["paired_contrast_min_per_author"],
        "styled_output_changed": summary["styled_non_neutral_rate"]
        >= effective_thresholds["styled_non_neutral_rate"],
        "positive_neutral_gain": summary["mean_neutral_gain"] > 0.0,
        "content_preserved": summary["content_preservation_mean"]
        >= effective_thresholds["content_preservation_mean"],
        "all_required_facts_preserved": summary["content_full_pass_rate"]
        >= effective_thresholds["content_full_pass_rate"],
        "length_compliant": summary["length_full_pass_rate"]
        >= effective_thresholds["length_full_pass_rate"],
        "no_reference_copy": summary["plagiarism_pass_rate"]
        >= effective_thresholds["plagiarism_pass_rate"],
        "prompt_holdout_clean": summary["prompt_leakage_pass_rate"]
        >= effective_thresholds["prompt_leakage_pass_rate"],
        "author_identity_blinded": summary["identity_blinding_pass_rate"]
        >= effective_thresholds["identity_blinding_pass_rate"],
        "module_lineage_verified": summary["module_lineage_coverage"]
        >= effective_thresholds["module_lineage_coverage"],
    }
    benchmark_passed = all(gates.values())
    return {
        "schema_version": STYLE_BENCHMARK_RESULTS_SCHEMA_VERSION,
        "benchmark_id": bundle.public.benchmark_id,
        "manifest_version": bundle.public.manifest_version,
        "public_manifest_hash": bundle.public.public_manifest_hash,
        "benchmark_manifest_hash": bundle.benchmark_manifest_hash,
        "reference_calibration": calibration,
        "thresholds": effective_thresholds,
        "gates": gates,
        "benchmark_passed": benchmark_passed,
        "summary": summary,
        "evidence_governance": {
            "provenance": "automated_cross_content_style_diagnostic",
            "holdout_visibility": "hidden_from_generation_path",
            "split_unit": "whole_work",
            "human_verified": False,
            "policy_evidence_eligible": False,
            "claim": "relative_style_signal_only",
            "limitations": [
                "首版仅含两位公版作者，作者与体裁仍有混杂，不能解释为作者身份识别器。",
                "两位作者的隐藏作品量不均衡；宏平均可减轻数量偏置，但不能消除语料差异。",
                "生成侧已匿名化作者名与篇名，但模型预训练可能识别公版正文，无法完全消除先验污染。",
                "自动文体距离只能证明可测风格信号；自然度与审美上限仍需盲评。",
            ],
        },
        "samples": scored,
    }


def load_generation_results(
    bundle: StyleBenchmarkBundle,
    source: str | Path | Mapping[str, Any],
) -> tuple[GenerationSample, ...]:
    payload = _load_results_payload(source)
    if payload.get("schema_version") != STYLE_BENCHMARK_RESULTS_SCHEMA_VERSION:
        raise StyleBenchmarkError("结果 schema_version 必须是 1")
    if payload.get("benchmark_id") != bundle.public.benchmark_id:
        raise StyleBenchmarkError("结果 benchmark_id 与清单不一致")
    if payload.get("manifest_version") != bundle.public.manifest_version:
        raise StyleBenchmarkError("结果 manifest_version 与清单不一致")
    if payload.get("public_manifest_hash") != bundle.public.public_manifest_hash:
        raise StyleBenchmarkError("结果 public_manifest_hash 与冻结公开清单不一致")
    raw_samples = payload.get("generations")
    if not isinstance(raw_samples, list):
        raise StyleBenchmarkError("结果 generations 必须是列表")

    samples: list[GenerationSample] = []
    seen: set[tuple[str, str, str]] = set()
    author_ids = set(bundle.public.author_ids)
    case_ids = {case.case_id for case in bundle.public.cases}
    for index, raw in enumerate(raw_samples):
        if not isinstance(raw, Mapping):
            raise StyleBenchmarkError(f"generations[{index}] 必须是对象")
        case_id = str(raw.get("case_id") or "").strip()
        arm = str(raw.get("arm") or "").strip()
        target_raw = raw.get("target_author_id")
        target_author_id = (
            str(target_raw).strip()
            if isinstance(target_raw, str) and target_raw.strip()
            else None
        )
        text = str(raw.get("generated_text") or "").strip()
        prompt_raw = raw.get("actual_prompt_text")
        prompt = (
            prompt_raw.strip()
            if isinstance(prompt_raw, str) and prompt_raw.strip()
            else None
        )
        metadata_raw = raw.get("generation_metadata")
        metadata = (
            deepcopy(dict(metadata_raw)) if isinstance(metadata_raw, Mapping) else {}
        )
        if (
            case_id not in case_ids
            or arm not in {"neutral", "styled"}
            or _visible_char_count(text) < 40
        ):
            raise StyleBenchmarkError(f"generations[{index}] 场景、arm 或正文无效")
        if arm == "neutral" and target_author_id is not None:
            raise StyleBenchmarkError("neutral 样本不得声明 target_author_id")
        if arm == "styled" and target_author_id not in author_ids:
            raise StyleBenchmarkError("styled 样本必须声明清单内 target_author_id")
        sample = GenerationSample(
            case_id=case_id,
            arm=arm,
            target_author_id=target_author_id,
            generated_text=text,
            actual_prompt_text=prompt,
            generation_metadata=metadata,
        )
        if sample.key in seen:
            raise StyleBenchmarkError(f"结果矩阵单元重复: {sample.key}")
        seen.add(sample.key)
        samples.append(sample)

    expected = {(case.case_id, "neutral", "") for case in bundle.public.cases} | {
        (case.case_id, "styled", author.author_id)
        for case in bundle.public.cases
        for author in bundle.public.authors
    }
    if seen != expected:
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        raise StyleBenchmarkError(f"结果矩阵不完整；missing={missing}, extra={extra}")
    return tuple(sorted(samples, key=lambda item: item.key))


def _effective_thresholds(overrides: Mapping[str, float] | None) -> dict[str, float]:
    effective = dict(DEFAULT_THRESHOLDS)
    for key, raw_value in dict(overrides or {}).items():
        if key not in DEFAULT_THRESHOLDS:
            raise StyleBenchmarkError(f"未知 benchmark threshold: {key}")
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise StyleBenchmarkError(f"benchmark threshold 必须是数值: {key}")
        value = float(raw_value)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise StyleBenchmarkError(f"benchmark threshold 必须在 0..1: {key}")
        if value < DEFAULT_THRESHOLDS[key]:
            raise StyleBenchmarkError(f"不能降低冻结 benchmark threshold: {key}")
        effective[key] = value
    return effective


def build_blind_review_artifacts(
    bundle: StyleBenchmarkBundle,
    results_source: str | Path | Mapping[str, Any],
    *,
    seed: str = "style-benchmark-v1",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """创建候选身份盲化的人工复核包与单独答案键。"""

    samples = load_generation_results(bundle, results_source)
    by_case = {case.case_id: [] for case in bundle.public.cases}
    for sample in samples:
        by_case[sample.case_id].append(sample)
    author_labels = {author.author_id: author.label for author in bundle.public.authors}
    packet_tasks: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    for case in bundle.public.cases:
        for target_author_id in bundle.public.author_ids:
            candidates = list(by_case[case.case_id])
            shuffle_seed = int(
                hashlib.sha256(
                    f"{seed}:{case.case_id}:{target_author_id}".encode("utf-8")
                ).hexdigest()[:16],
                16,
            )
            random.Random(shuffle_seed).shuffle(candidates)
            public_candidates: list[dict[str, str]] = []
            for ordinal, sample in enumerate(candidates):
                opaque_id = hashlib.sha256(
                    f"{seed}:{case.case_id}:{target_author_id}:{ordinal}:{sample.text_hash}".encode(
                        "utf-8"
                    )
                ).hexdigest()[:16]
                public_candidates.append(
                    {"sample_id": opaque_id, "text": sample.generated_text}
                )
                key_rows.append(
                    {
                        "task_id": f"{case.case_id}:{target_author_id}",
                        "sample_id": opaque_id,
                        "case_id": case.case_id,
                        "arm": sample.arm,
                        "target_author_id": sample.target_author_id,
                        "generated_text_sha256": sample.text_hash,
                    }
                )
            packet_tasks.append(
                {
                    "task_id": f"{case.case_id}:{target_author_id}",
                    "case": case.public_payload(),
                    "target_style_label": author_labels[target_author_id],
                    "instructions": {
                        "rank": [
                            "target_style_fit",
                            "naturalness",
                            "content_preservation",
                        ],
                        "flag": ["reference_copy_suspicion", "obvious_ai_voice"],
                        "candidate_identity": "blinded",
                    },
                    "candidates": public_candidates,
                }
            )
    packet = {
        "schema_version": 1,
        "benchmark_id": bundle.public.benchmark_id,
        "manifest_version": bundle.public.manifest_version,
        "blind_seed_hash": hash_text(seed),
        "tasks": packet_tasks,
    }
    answer_key = {
        "schema_version": 1,
        "benchmark_id": bundle.public.benchmark_id,
        "manifest_version": bundle.public.manifest_version,
        "blind_packet_sha256": hashlib.sha256(
            canonical_json(packet).encode("utf-8")
        ).hexdigest(),
        "samples": key_rows,
    }
    return packet, answer_key


class _PromptLeakGuard:
    def __init__(self, bundle: StyleBenchmarkBundle) -> None:
        train_hashes = _ngram_hashes(
            work.text for author in bundle.public.authors for work in author.train_works
        )
        hidden_hashes = _ngram_hashes(
            work.text
            for author in bundle.hidden_authors
            for work in author.holdout_works
        )
        self._hidden_only_hashes = hidden_hashes - train_hashes

    def inspect(self, prompt: str | None) -> dict[str, Any]:
        if prompt is None:
            return {"verified": False, "passed": False, "hidden_ngram_hit_count": None}
        hits = _text_ngram_hashes(prompt).intersection(self._hidden_only_hashes)
        return {
            "verified": True,
            "passed": not hits,
            "hidden_ngram_hit_count": len(hits),
            "ngram_chars": PROMPT_LEAK_NGRAM_CHARS,
        }


class _IdentityLeakGuard:
    def __init__(self, bundle: StyleBenchmarkBundle) -> None:
        markers: set[str] = set()
        for author in bundle.public.authors:
            markers.add(author.author_id.casefold())
            public_name = (
                re.split(r"[（(]", author.label, maxsplit=1)[0].strip().casefold()
            )
            if public_name:
                markers.add(public_name)
        self._markers = tuple(sorted(markers))

    def inspect(self, prompt: str | None) -> dict[str, Any]:
        if prompt is None:
            return {
                "verified": False,
                "passed": False,
                "identity_marker_hit_count": None,
            }
        normalized = prompt.casefold()
        hit_count = sum(marker in normalized for marker in self._markers)
        return {
            "verified": True,
            "passed": hit_count == 0,
            "identity_marker_hit_count": hit_count,
        }


def _ngram_hashes(texts) -> set[str]:  # noqa: ANN001
    hashes: set[str] = set()
    for text in texts:
        hashes.update(_text_ngram_hashes(text))
    return hashes


def _text_ngram_hashes(text: str) -> set[str]:
    normalized = normalize_text_for_matching(text)
    if len(normalized) < PROMPT_LEAK_NGRAM_CHARS:
        return set()
    return {
        hash_text(normalized[index : index + PROMPT_LEAK_NGRAM_CHARS])
        for index in range(len(normalized) - PROMPT_LEAK_NGRAM_CHARS + 1)
    }


def _content_preservation(case: BenchmarkCase, text: str) -> dict[str, Any]:
    normalized = text.casefold()
    group_results = [
        any(term.casefold() in normalized for term in group)
        for group in case.required_term_groups
    ]
    score = sum(group_results) / len(group_results)
    return {
        "score": round(score, 4),
        "passed": all(group_results),
        "matched_groups": sum(group_results),
        "group_count": len(group_results),
    }


def _length_score(case: BenchmarkCase, text: str) -> float:
    # 基准声明的是有效字符长度；空格、换行和制表符不能被用来“填满”字数。
    length = _visible_char_count(text)
    if case.min_chars <= length <= case.max_chars:
        return 1.0
    if length < case.min_chars:
        return round(length / case.min_chars, 4)
    return round(case.max_chars / length, 4)


def _visible_char_count(text: str) -> int:
    return sum(not char.isspace() for char in text)


def _lineage_check(
    bundle: StyleBenchmarkBundle,
    sample: GenerationSample,
    neutral_by_case: Mapping[str, GenerationSample],
) -> dict[str, Any]:
    if sample.arm == "neutral":
        path = str(sample.generation_metadata.get("generation_path") or "")
        checks = {
            "neutral_generation_path": path == "neutral_draft",
            "reference_profiles_absent": sample.generation_metadata.get(
                "reference_profile_ids"
            )
            == [],
        }
    else:
        author = bundle.public.author_for(sample.target_author_id or "")
        neutral = neutral_by_case[sample.case_id]
        profile_id = str(
            sample.generation_metadata.get("style_reference_profile_id") or ""
        ).strip()
        checks = {
            "style_reference_generation_path": sample.generation_metadata.get(
                "generation_path"
            )
            == "style_reference_module",
            "profile_id_present": bool(profile_id),
            "single_target_profile": sample.generation_metadata.get(
                "reference_profile_ids"
            )
            == [profile_id],
            "training_corpus_bound": sample.generation_metadata.get(
                "training_corpus_checksum"
            )
            == author.training_checksum,
            "same_neutral_source": sample.generation_metadata.get(
                "source_neutral_sha256"
            )
            == neutral.text_hash,
        }
    return {"passed": all(checks.values()), "checks": checks}


def _aggregate(
    bundle: StyleBenchmarkBundle, scored: list[dict[str, Any]]
) -> dict[str, Any]:
    styled = [row for row in scored if row["arm"] == "styled"]
    neutral = {row["case_id"]: row for row in scored if row["arm"] == "neutral"}
    styled_lookup = {(row["case_id"], row["target_author_id"]): row for row in styled}
    target_margins = [float(row["target_margin"]) for row in styled]
    paired_margins: list[float] = []
    paired_margins_by_author: dict[str, list[float]] = {
        author_id: [] for author_id in bundle.public.author_ids
    }
    neutral_gains: list[float] = []
    for case in bundle.public.cases:
        neutral_row = neutral[case.case_id]
        for target_author_id in bundle.public.author_ids:
            target_row = styled_lookup[(case.case_id, target_author_id)]
            decoy_rows = [
                styled_lookup[(case.case_id, other)]
                for other in bundle.public.author_ids
                if other != target_author_id
            ]
            target_similarity = float(target_row["similarities"][target_author_id])
            paired_margin = target_similarity - max(
                float(row["similarities"][target_author_id]) for row in decoy_rows
            )
            paired_margins.append(paired_margin)
            paired_margins_by_author[target_author_id].append(paired_margin)
            neutral_scores = neutral_row["similarities"]
            neutral_margin = float(neutral_scores[target_author_id]) - max(
                float(score)
                for author_id, score in neutral_scores.items()
                if author_id != target_author_id
            )
            neutral_gains.append(float(target_row["target_margin"]) - neutral_margin)

    prompt_rows = [row["prompt_leakage"] for row in scored]
    verified_prompt_count = sum(1 for row in prompt_rows if row["verified"])
    prompt_pass_count = sum(
        1 for row in prompt_rows if row["verified"] and row["passed"]
    )
    identity_rows = [row["identity_blinding"] for row in scored]
    identity_pass_count = sum(
        1 for row in identity_rows if row["verified"] and row["passed"]
    )
    per_author: dict[str, dict[str, Any]] = {}
    for author_id in bundle.public.author_ids:
        author_rows = [row for row in styled if row["target_author_id"] == author_id]
        author_paired = paired_margins_by_author[author_id]
        per_author[author_id] = {
            "sample_count": len(author_rows),
            "style_attribution_accuracy": round(
                sum(bool(row["attributed_correctly"]) for row in author_rows)
                / len(author_rows),
                4,
            ),
            "mean_target_margin": round(
                statistics.fmean(float(row["target_margin"]) for row in author_rows),
                6,
            ),
            "paired_contrast_accuracy": round(
                sum(margin > 0 for margin in author_paired) / len(author_paired),
                4,
            ),
            "mean_paired_contrast_margin": round(
                statistics.fmean(author_paired), 6
            ),
            "exact_neutral_fallback_count": sum(
                row["generated_text_sha256"]
                == neutral[row["case_id"]]["generated_text_sha256"]
                for row in author_rows
            ),
            "neutral_equivalent_fallback_count": sum(
                row["generated_normalized_sha256"]
                == neutral[row["case_id"]]["generated_normalized_sha256"]
                for row in author_rows
            ),
        }
    attribution_min = min(
        float(row["style_attribution_accuracy"]) for row in per_author.values()
    )
    paired_min = min(
        float(row["paired_contrast_accuracy"]) for row in per_author.values()
    )
    styled_non_neutral_count = sum(
        row["generated_normalized_sha256"]
        != neutral[row["case_id"]]["generated_normalized_sha256"]
        for row in styled
    )
    exact_neutral_fallback_count = sum(
        row["generated_text_sha256"]
        == neutral[row["case_id"]]["generated_text_sha256"]
        for row in styled
    )
    return {
        "case_count": len(bundle.public.cases),
        "generation_count": len(scored),
        "styled_generation_count": len(styled),
        "style_attribution_accuracy": round(
            sum(bool(row["attributed_correctly"]) for row in styled) / len(styled), 4
        ),
        "style_attribution_min_per_author": round(attribution_min, 4),
        "mean_target_margin": round(statistics.fmean(target_margins), 6),
        "paired_contrast_accuracy": round(
            sum(margin > 0 for margin in paired_margins) / len(paired_margins), 4
        ),
        "paired_contrast_min_per_author": round(paired_min, 4),
        "mean_paired_contrast_margin": round(statistics.fmean(paired_margins), 6),
        "mean_neutral_gain": round(statistics.fmean(neutral_gains), 6),
        "styled_non_neutral_rate": round(
            styled_non_neutral_count / len(styled), 4
        ),
        "exact_neutral_fallback_count": exact_neutral_fallback_count,
        "neutral_equivalent_fallback_count": len(styled)
        - styled_non_neutral_count,
        "per_author": per_author,
        "content_preservation_mean": round(
            statistics.fmean(
                float(row["content_preservation"]["score"]) for row in scored
            ),
            4,
        ),
        "content_full_pass_rate": round(
            sum(bool(row["content_preservation"]["passed"]) for row in scored)
            / len(scored),
            4,
        ),
        "length_score_mean": round(
            statistics.fmean(float(row["length_score"]) for row in scored), 4
        ),
        "length_full_pass_rate": round(
            sum(float(row["length_score"]) == 1.0 for row in scored) / len(scored),
            4,
        ),
        "plagiarism_pass_rate": round(
            sum(bool(row["plagiarism"]["passed"]) for row in scored) / len(scored), 4
        ),
        "prompt_leakage_verified_count": verified_prompt_count,
        "prompt_leakage_pass_rate": round(prompt_pass_count / len(scored), 4),
        "identity_blinding_pass_rate": round(identity_pass_count / len(scored), 4),
        "module_lineage_coverage": round(
            sum(bool(row["module_lineage"]["passed"]) for row in scored) / len(scored),
            4,
        ),
    }


def _safe_generation_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "generation_path",
        "style_reference_profile_id",
        "training_corpus_checksum",
        "source_neutral_sha256",
        "reference_profile_ids",
        "model",
        "provider",
        "llm_call_id",
        "prompt_hash",
    }
    return {key: deepcopy(value) for key, value in metadata.items() if key in allowed}


def _load_results_payload(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return deepcopy(dict(source))
    path = Path(source).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StyleBenchmarkError(f"生成结果不可读或不是合法 JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise StyleBenchmarkError("生成结果根节点必须是对象")
    return payload
