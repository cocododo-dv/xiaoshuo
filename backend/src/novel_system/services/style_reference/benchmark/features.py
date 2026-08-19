"""内容克制的中文文体特征与隐藏参考分类器。

这里刻意不使用主题词、人物名或字符 n-gram；只使用句段长度、标点、虚词、
代词、连接词和现有可解释硬指标，减少“写了同一件事”被误判成“风格相同”。
首版是确定性诊断器，不把自动分数包装成人类审美结论。
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from typing import Iterable, Mapping

from novel_system.services.style_reference.benchmark.manifest import (
    CorpusWork,
    StyleBenchmarkError,
)
from novel_system.services.style_reference.metrics import (
    METRIC_NAMES,
    MetricsEngine,
    ParagraphRecord,
)
from novel_system.services.style_reference.text_utils import split_sentences


FEATURE_VERSION = "zh_explainable_stylometry_v1"
REFERENCE_CHUNK_TARGET_CHARS = 700
REFERENCE_CHUNK_MIN_CHARS = 320
_TYPE_RATIO_METRICS = frozenset(
    {
        "dialogue_ratio",
        "psychology_ratio",
        "description_env_ratio",
        "description_char_ratio",
        "action_ratio",
        "narration_ratio",
        "transition_ratio",
        "flashback_ratio",
    }
)
_TEXT_METRICS = tuple(name for name in METRIC_NAMES if name not in _TYPE_RATIO_METRICS)
_PUNCTUATION = {
    "comma": "，,",
    "period": "。.",
    "semicolon": "；;",
    "colon": "：:",
    "question": "？?",
    "exclamation": "！!",
    "enumeration": "、",
    "quote": "“”‘’「」『』\"'",
    "parenthesis": "（）()【】",
}
_PATTERN_PUNCTUATION = {
    "dash": re.compile(r"——|—"),
    "ellipsis": re.compile(r"……|…|\.{3,}"),
}
_FUNCTION_MARKERS = (
    "的",
    "了",
    "是",
    "在",
    "有",
    "也",
    "而",
    "但",
    "却",
    "便",
    "就",
    "又",
    "都",
    "只",
    "还",
    "将",
    "把",
    "被",
    "着",
    "过",
    "呢",
    "吧",
    "啊",
    "么",
    "吗",
    "其",
    "之",
    "者",
    "所",
    "以",
    "于",
    "与",
    "并",
    "仍",
    "乃",
    "故",
    "且",
    "若",
    "倘",
    "然而",
    "于是",
    "所以",
    "因为",
    "虽然",
    "似乎",
    "仿佛",
    "大约",
    "忽然",
    "自然",
    "其实",
    "可是",
)
_PRONOUN_MARKERS = ("我", "你", "他", "她", "它", "我们", "你们", "他们", "她们")


@dataclass(frozen=True, slots=True)
class ReferenceChunk:
    author_id: str
    work_title: str
    chunk_index: int
    text: str
    features: dict[str, float]


class StyleFeatureExtractor:
    def __init__(self, *, metrics_engine: MetricsEngine | None = None) -> None:
        self._metrics = metrics_engine or MetricsEngine()

    def extract(self, text: str) -> dict[str, float]:
        normalized = str(text or "").strip()
        if not normalized:
            raise StyleBenchmarkError("不能从空文本提取风格特征")
        paragraphs = [
            part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()
        ]
        if not paragraphs:
            paragraphs = [normalized]
        sentences = [
            sentence.strip()
            for sentence in split_sentences(normalized)
            if sentence.strip()
        ]
        sentence_lengths = [_visible_length(sentence) for sentence in sentences] or [
            _visible_length(normalized)
        ]
        paragraph_lengths = [_visible_length(paragraph) for paragraph in paragraphs]
        visible_chars = max(1, _visible_length(normalized))

        base = self._metrics.compute_all(
            [
                ParagraphRecord(text=paragraph, paragraph_type="narration")
                for paragraph in paragraphs
            ]
        )
        features = {f"metric.{name}": float(base[name]) for name in _TEXT_METRICS}
        features.update(
            {
                "shape.sentence_mean": statistics.fmean(sentence_lengths),
                "shape.sentence_std": _pstdev(sentence_lengths),
                "shape.sentence_q25": _quantile(sentence_lengths, 0.25),
                "shape.sentence_median": _quantile(sentence_lengths, 0.5),
                "shape.sentence_q75": _quantile(sentence_lengths, 0.75),
                "shape.sentence_per_1k": len(sentence_lengths) * 1000.0 / visible_chars,
                "shape.paragraph_mean": statistics.fmean(paragraph_lengths),
                "shape.paragraph_std": _pstdev(paragraph_lengths),
                "shape.paragraph_q75": _quantile(paragraph_lengths, 0.75),
                "shape.paragraph_per_1k": len(paragraphs) * 1000.0 / visible_chars,
                "shape.single_sentence_paragraph_ratio": sum(
                    1
                    for paragraph in paragraphs
                    if len(split_sentences(paragraph)) <= 1
                )
                / len(paragraphs),
                "shape.dialogue_paragraph_ratio": sum(
                    1 for paragraph in paragraphs if _looks_like_dialogue(paragraph)
                )
                / len(paragraphs),
                "shape.cjk_ratio": sum(
                    1 for char in normalized if "\u3400" <= char <= "\u9fff"
                )
                / visible_chars,
                "shape.latin_ratio": sum(
                    1 for char in normalized if char.isascii() and char.isalpha()
                )
                / visible_chars,
                "shape.digit_ratio": sum(1 for char in normalized if char.isdigit())
                / visible_chars,
            }
        )
        for name, chars in _PUNCTUATION.items():
            features[f"punct.{name}_per_1k"] = (
                sum(normalized.count(char) for char in set(chars))
                * 1000.0
                / visible_chars
            )
        for name, pattern in _PATTERN_PUNCTUATION.items():
            features[f"punct.{name}_per_1k"] = (
                len(pattern.findall(normalized)) * 1000.0 / visible_chars
            )
        for marker in _FUNCTION_MARKERS:
            features[f"function.{marker}_per_1k"] = (
                normalized.count(marker) * 1000.0 / visible_chars
            )
        for marker in _PRONOUN_MARKERS:
            features[f"pronoun.{marker}_per_1k"] = (
                normalized.count(marker) * 1000.0 / visible_chars
            )
        return features


class HiddenStyleEvaluator:
    """在隐藏作品块上拟合可解释 centroid，并返回相对作者距离。"""

    def __init__(
        self,
        works_by_author: Mapping[str, Iterable[CorpusWork]],
        *,
        extractor: StyleFeatureExtractor | None = None,
        target_chunk_chars: int = REFERENCE_CHUNK_TARGET_CHARS,
        min_chunk_chars: int = REFERENCE_CHUNK_MIN_CHARS,
    ) -> None:
        if len(works_by_author) < 2:
            raise StyleBenchmarkError("隐藏风格评估器至少需要两个作者")
        self.extractor = extractor or StyleFeatureExtractor()
        self.chunks_by_author: dict[str, tuple[ReferenceChunk, ...]] = {}
        for author_id, works_iter in works_by_author.items():
            chunks: list[ReferenceChunk] = []
            for work in works_iter:
                for chunk_index, chunk_text in enumerate(
                    chunk_work_text(
                        work.text,
                        target_chars=target_chunk_chars,
                        min_chars=min_chunk_chars,
                    )
                ):
                    chunks.append(
                        ReferenceChunk(
                            author_id=author_id,
                            work_title=work.title,
                            chunk_index=chunk_index,
                            text=chunk_text,
                            features=self.extractor.extract(chunk_text),
                        )
                    )
            if len(chunks) < 2:
                raise StyleBenchmarkError(f"作者 {author_id} 的隐藏语料不足两个有效块")
            work_titles = {chunk.work_title for chunk in chunks}
            if len(work_titles) < 2:
                raise StyleBenchmarkError(
                    f"作者 {author_id} 的隐藏语料不足两篇作品，不能做整篇作品留出校准"
                )
            self.chunks_by_author[author_id] = tuple(chunks)

        self.author_ids = tuple(sorted(self.chunks_by_author))
        self._feature_names = tuple(
            sorted(next(iter(self.chunks_by_author.values()))[0].features)
        )
        self._global_means, self._scales, self._weights = self._fit_feature_space()
        self._centroids = {
            author_id: self._centroid([chunk.features for chunk in chunks])
            for author_id, chunks in self.chunks_by_author.items()
        }

    @property
    def active_feature_count(self) -> int:
        return len(self._weights)

    def similarities(self, text: str) -> dict[str, float]:
        vector = self._standardize(self.extractor.extract(text))
        return {
            author_id: round(-self._distance(vector, centroid), 6)
            for author_id, centroid in self._centroids.items()
        }

    def classify(self, text: str) -> tuple[str, dict[str, float]]:
        similarities = self.similarities(text)
        predicted = max(
            self.author_ids, key=lambda author_id: (similarities[author_id], author_id)
        )
        return predicted, similarities

    def calibration_report(self) -> dict[str, object]:
        per_author: dict[str, dict[str, float | int]] = {}
        confusion: dict[str, dict[str, int]] = {
            author_id: {candidate: 0 for candidate in self.author_ids}
            for author_id in self.author_ids
        }
        all_margins: list[float] = []
        fold_feature_counts: list[int] = []
        for author_id, chunks in self.chunks_by_author.items():
            correct = 0
            margins: list[float] = []
            work_titles = sorted({chunk.work_title for chunk in chunks})
            for held_work_title in work_titles:
                # 整篇作品不仅从作者质心移除，也从该折的均值、尺度和特征权重
                # 拟合中移除；否则特征选择仍间接“看过”测试作品。
                fold_chunks = {
                    candidate: tuple(
                        item
                        for item in candidate_chunks
                        if not (
                            candidate == author_id
                            and item.work_title == held_work_title
                        )
                    )
                    for candidate, candidate_chunks in self.chunks_by_author.items()
                }
                if not fold_chunks[author_id]:
                    raise StyleBenchmarkError(
                        f"作者 {author_id} 留出 {held_work_title} 后没有训练作品"
                    )
                means, scales, weights = self._fit_feature_space_for(fold_chunks)
                fold_feature_counts.append(len(weights))
                centroids = {
                    candidate: self._centroid_for(
                        [item.features for item in candidate_chunks],
                        means=means,
                        scales=scales,
                        weights=weights,
                    )
                    for candidate, candidate_chunks in fold_chunks.items()
                }
                held_chunks = [
                    chunk for chunk in chunks if chunk.work_title == held_work_title
                ]
                for chunk in held_chunks:
                    vector = self._standardize_for(
                        chunk.features,
                        means=means,
                        scales=scales,
                        weights=weights,
                    )
                    scores = {
                        candidate: -self._distance_for(
                            vector, centroid, weights=weights
                        )
                        for candidate, centroid in centroids.items()
                    }
                    predicted = max(
                        self.author_ids,
                        key=lambda candidate: (scores[candidate], candidate),
                    )
                    confusion[author_id][predicted] += 1
                    correct += int(predicted == author_id)
                    margin = scores[author_id] - max(
                        score
                        for candidate, score in scores.items()
                        if candidate != author_id
                    )
                    margins.append(margin)
                    all_margins.append(margin)
            per_author[author_id] = {
                "chunk_count": len(chunks),
                "work_count": len({chunk.work_title for chunk in chunks}),
                "accuracy": round(correct / len(chunks), 4),
                "mean_margin": round(statistics.fmean(margins), 6),
            }
        macro_accuracy = statistics.fmean(
            float(row["accuracy"]) for row in per_author.values()
        )
        return {
            "feature_version": FEATURE_VERSION,
            "calibration_split_unit": "whole_work",
            "calibration_feature_fit": "per_fold_without_held_work",
            "active_feature_count": self.active_feature_count,
            "calibration_min_active_feature_count": min(fold_feature_counts),
            "macro_accuracy": round(macro_accuracy, 4),
            "mean_correct_margin": round(statistics.fmean(all_margins), 6),
            "per_author": per_author,
            "confusion": confusion,
        }

    def _fit_feature_space(
        self,
    ) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
        return self._fit_feature_space_for(self.chunks_by_author)

    def _fit_feature_space_for(
        self,
        chunks_by_author: Mapping[str, Iterable[ReferenceChunk]],
    ) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
        author_feature_values: dict[str, dict[str, list[float]]] = {}
        for author_id in self.author_ids:
            chunks = tuple(chunks_by_author[author_id])
            if not chunks:
                raise StyleBenchmarkError(f"作者 {author_id} 的校准折没有训练片段")
            author_feature_values[author_id] = {
                name: [chunk.features[name] for chunk in chunks]
                for name in self._feature_names
            }
        global_means: dict[str, float] = {}
        scales: dict[str, float] = {}
        weights: dict[str, float] = {}
        for name in self._feature_names:
            author_means = [
                statistics.fmean(author_feature_values[author_id][name])
                for author_id in self.author_ids
            ]
            within_variances = [
                (
                    statistics.pvariance(author_feature_values[author_id][name])
                    if len(author_feature_values[author_id][name]) > 1
                    else 0.0
                )
                for author_id in self.author_ids
            ]
            between_variance = statistics.pvariance(author_means)
            within_variance = statistics.fmean(within_variances)
            total_variance = between_variance + within_variance
            if total_variance <= 1e-10:
                continue
            scale = math.sqrt(total_variance)
            effect = math.sqrt(between_variance) / (
                math.sqrt(within_variance) + scale * 0.1 + 1e-9
            )
            global_means[name] = statistics.fmean(author_means)
            scales[name] = scale
            weights[name] = min(4.0, max(0.25, effect))
        if len(weights) < 8:
            raise StyleBenchmarkError("隐藏语料没有形成足够的可区分风格特征")
        return global_means, scales, weights

    def _standardize(self, features: Mapping[str, float]) -> dict[str, float]:
        return self._standardize_for(
            features,
            means=self._global_means,
            scales=self._scales,
            weights=self._weights,
        )

    @staticmethod
    def _standardize_for(
        features: Mapping[str, float],
        *,
        means: Mapping[str, float],
        scales: Mapping[str, float],
        weights: Mapping[str, float],
    ) -> dict[str, float]:
        return {
            name: max(
                -8.0, min(8.0, (float(features[name]) - means[name]) / scales[name])
            )
            for name in weights
        }

    def _centroid(self, vectors: list[Mapping[str, float]]) -> dict[str, float]:
        return self._centroid_for(
            vectors,
            means=self._global_means,
            scales=self._scales,
            weights=self._weights,
        )

    @classmethod
    def _centroid_for(
        cls,
        vectors: list[Mapping[str, float]],
        *,
        means: Mapping[str, float],
        scales: Mapping[str, float],
        weights: Mapping[str, float],
    ) -> dict[str, float]:
        if not vectors:
            raise StyleBenchmarkError("留一校准无法计算空 centroid")
        standardized = [
            cls._standardize_for(
                vector,
                means=means,
                scales=scales,
                weights=weights,
            )
            for vector in vectors
        ]
        return {
            name: statistics.fmean(vector[name] for vector in standardized)
            for name in weights
        }

    def _distance(
        self, vector: Mapping[str, float], centroid: Mapping[str, float]
    ) -> float:
        return self._distance_for(vector, centroid, weights=self._weights)

    @staticmethod
    def _distance_for(
        vector: Mapping[str, float],
        centroid: Mapping[str, float],
        *,
        weights: Mapping[str, float],
    ) -> float:
        weight_sum = sum(weights.values())
        return (
            sum(
                weights[name] * min(abs(vector[name] - centroid[name]), 8.0)
                for name in weights
            )
            / weight_sum
        )


def chunk_work_text(text: str, *, target_chars: int, min_chars: int) -> tuple[str, ...]:
    if target_chars <= 0 or min_chars <= 0 or min_chars > target_chars:
        raise ValueError("chunk size 参数无效")
    blocks = [
        part.strip() for part in re.split(r"\n\s*\n", str(text or "")) if part.strip()
    ]
    atomic: list[str] = []
    for block in blocks:
        if len(block) <= target_chars * 2:
            atomic.append(block)
            continue
        atomic.extend(_split_long_block(block, target_chars))

    chunks: list[str] = []
    current: list[str] = []
    current_chars = 0
    for block in atomic:
        if (
            current
            and current_chars >= min_chars
            and current_chars + len(block) > target_chars
        ):
            chunks.append("\n\n".join(current))
            current = []
            current_chars = 0
        current.append(block)
        current_chars += len(block)
        if current_chars >= target_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_chars = 0
    if current:
        tail = "\n\n".join(current)
        if chunks and len(tail) < min_chars:
            chunks[-1] = f"{chunks[-1]}\n\n{tail}"
        else:
            chunks.append(tail)
    return tuple(chunk for chunk in chunks if len(chunk) >= min_chars)


def _split_long_block(text: str, target_chars: int) -> list[str]:
    sentences = split_sentences(text)
    if len(sentences) <= 1:
        return [
            text[index : index + target_chars]
            for index in range(0, len(text), target_chars)
        ]
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > target_chars:
            parts.append(current)
            current = ""
        current += sentence
    if current:
        parts.append(current)
    return parts


def _visible_length(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def _pstdev(values: list[int]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def _quantile(values: list[int], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def _looks_like_dialogue(paragraph: str) -> bool:
    stripped = paragraph.lstrip()
    return stripped.startswith(("“", "‘", "「", "『", '"', "—"))
