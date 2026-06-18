"""Style Reference v1.1 硬指标计算(纯函数,无 LLM)。

依据《风格参考模块重构执行手册 v1.1》§6.3。
贯穿三阶段使用:
  ① 抽取(PR-3)时作为 prompt 上下文注入 `metrics_anchor`
  ② 验证(PR-7)时作为对照(`quantitative` 路径)
  ③ 预览(PR-4)时作为置信度证据

中文分句沿用 `text_utils.split_sentences`。感官词表从
`config/style_reference/sensory_lexicon.yaml` 读。
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Callable, Literal

from novel_system.services.style_reference.config_loader import load_yaml_config
from novel_system.services.style_reference.text_utils import split_sentences

# ---------------------------------------------------------------------------
# MetricName 全清单(26 项;与 §6.3 严格对账)
# ---------------------------------------------------------------------------

MetricName = Literal[
    # 语言层(13)
    "avg_sentence_length",
    "sentence_length_std",
    "short_sentence_ratio",
    "long_sentence_ratio",
    "punctuation_density_per_1k",
    "dash_em_density_per_1k",
    "ellipsis_density_per_1k",
    "semicolon_density_per_1k",
    "question_density_per_1k",
    "classical_word_ratio",
    "colloquial_marker_ratio",
    "metaphor_density_per_1k",
    "personification_density_per_1k",
    # 叙事层(8,paragraph_type 比例)
    "dialogue_ratio",
    "psychology_ratio",
    "description_env_ratio",
    "description_char_ratio",
    "action_ratio",
    "narration_ratio",
    "transition_ratio",
    "flashback_ratio",
    # 感官(5,场景层)
    "sensory_visual_per_1k",
    "sensory_auditory_per_1k",
    "sensory_olfactory_per_1k",
    "sensory_tactile_per_1k",
    "sensory_gustatory_per_1k",
]

METRIC_NAMES: tuple[str, ...] = (
    "avg_sentence_length",
    "sentence_length_std",
    "short_sentence_ratio",
    "long_sentence_ratio",
    "punctuation_density_per_1k",
    "dash_em_density_per_1k",
    "ellipsis_density_per_1k",
    "semicolon_density_per_1k",
    "question_density_per_1k",
    "classical_word_ratio",
    "colloquial_marker_ratio",
    "metaphor_density_per_1k",
    "personification_density_per_1k",
    "dialogue_ratio",
    "psychology_ratio",
    "description_env_ratio",
    "description_char_ratio",
    "action_ratio",
    "narration_ratio",
    "transition_ratio",
    "flashback_ratio",
    "sensory_visual_per_1k",
    "sensory_auditory_per_1k",
    "sensory_olfactory_per_1k",
    "sensory_tactile_per_1k",
    "sensory_gustatory_per_1k",
)

# 常量词表
_PUNCT_CHARS = "。！？，；:、——…“”\"\"‘’「」『』《》()【】!?,;:."
_CLASSICAL_MARKERS = ("之", "乎", "者", "也", "焉", "矣", "哉", "曰", "兮", "其")
_COLLOQUIAL_MARKERS = ("吧", "呢", "啊", "嗯", "哎", "嘛", "哦", "哪", "呀", "罢", "嘞")
# 比喻关键词;TODO(PR-3):LLM 抽取增强,目前以词表近似
_METAPHOR_MARKERS = ("像", "如同", "仿佛", "犹如", "好似", "恰似", "宛如", "似的", "好像")
# 拟人词表;TODO(PR-3):LLM 增强。PR-2 占位为空,personification_density_per_1k 暂返 0
_PERSONIFICATION_MARKERS: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# ParagraphRecord 与 MetricsEngine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParagraphRecord:
    """metrics 计算的最小段落抽象。

    PR-2 ingest 调 segmentation 拿到结果后用此类型传给 MetricsEngine,
    不依赖 ORM 实例(便于纯函数测试)。
    """

    text: str
    paragraph_type: str  # ParagraphType.value

    @property
    def char_count(self) -> int:
        return len(self.text)


class MetricsEngine:
    """26 项 MetricName 的纯函数实现。

    用法::

        engine = MetricsEngine()
        means = engine.compute_all(paragraphs)               # dict[name, float]
        var   = engine.compute_with_variance(paragraphs)     # dict[name, (mean, std)]
    """

    def __init__(self, sensory_lexicon: dict[str, list[str]] | None = None) -> None:
        self._sensory_lexicon = sensory_lexicon if sensory_lexicon is not None else self._load_sensory_lexicon()

    @staticmethod
    def _load_sensory_lexicon() -> dict[str, list[str]]:
        cfg = load_yaml_config("sensory_lexicon")
        # cfg 顶层是 dict {visual: [...], auditory: [...], ...}
        return {sense: [str(w) for w in cfg.get(sense, [])] for sense in
                ("visual", "auditory", "olfactory", "tactile", "gustatory")}

    def compute_all(self, paragraphs: list[ParagraphRecord]) -> dict[str, float]:
        if not paragraphs:
            return {name: 0.0 for name in METRIC_NAMES}
        return {
            name: statistics.fmean(self._per_paragraph(name, p) for p in paragraphs)
            for name in METRIC_NAMES
        }

    def compute_with_variance(
        self, paragraphs: list[ParagraphRecord]
    ) -> dict[str, tuple[float, float]]:
        """返回 {metric: (mean, std)}。

        - **mean** 为全文单值(== ``compute_all``,逐段值的均值),不随分块变化;
        - **std** 为**块间标准差**(块 ≈ 场景大小,见 ``_chunk_by_chars``),而非逐段标准差。

        为何用块间 std(2026-06 校准修正):逐段 std 噪声极大——段落短、且
        paragraph_type 比例指标逐段取 0/1(段级 std 高达 ~0.5)——使
        ``tolerance = max(std×1.25, floor)`` 宽到几乎不拦截(原作互比 26 项零超容差)。
        回测对照的是「整段生成文本(≈一个场景/块)的单值」,故 tolerance 应反映
        **作者自身块到块的自然波动**,即块间 std。这样量化门才真正有区分力,
        同时 floor 防止低波动指标过紧。
        """
        if not paragraphs:
            return {name: (0.0, 0.0) for name in METRIC_NAMES}
        means = self.compute_all(paragraphs)
        chunks = _chunk_by_chars(paragraphs, _VARIANCE_CHUNK_CHARS)
        result: dict[str, tuple[float, float]] = {}
        for name in METRIC_NAMES:
            if len(chunks) > 1:
                chunk_values = [
                    statistics.fmean(self._per_paragraph(name, p) for p in chunk)
                    for chunk in chunks
                ]
                std = statistics.pstdev(chunk_values)
            else:
                # 单块(短语料):无块间样本,std=0 → tolerance 落到 floor
                std = 0.0
            result[name] = (means[name], std)
        return result

    # ------------------------------------------------------------------ private

    def _per_paragraph(self, name: str, p: ParagraphRecord) -> float:
        if name == "avg_sentence_length":
            return _avg_sentence_length(p.text)
        if name == "sentence_length_std":
            return _sentence_length_std(p.text)
        if name == "short_sentence_ratio":
            return _sentence_length_ratio(p.text, lambda L: L <= 10)
        if name == "long_sentence_ratio":
            return _sentence_length_ratio(p.text, lambda L: L >= 30)
        if name == "punctuation_density_per_1k":
            return _density_per_1k_chars(p.text, _PUNCT_CHARS)
        if name == "dash_em_density_per_1k":
            return _density_per_1k_pattern(p.text, r"——|—")
        if name == "ellipsis_density_per_1k":
            return _density_per_1k_pattern(p.text, r"……|…|\.{3,}")
        if name == "semicolon_density_per_1k":
            return _density_per_1k_chars(p.text, ";;")
        if name == "question_density_per_1k":
            return _density_per_1k_chars(p.text, "??")
        if name == "classical_word_ratio":
            return _word_occurrence_ratio(p.text, _CLASSICAL_MARKERS)
        if name == "colloquial_marker_ratio":
            return _word_occurrence_ratio(p.text, _COLLOQUIAL_MARKERS)
        if name == "metaphor_density_per_1k":
            return _density_per_1k_words(p.text, _METAPHOR_MARKERS)
        if name == "personification_density_per_1k":
            return _density_per_1k_words(p.text, _PERSONIFICATION_MARKERS)
        # paragraph_type 比例:按段 0/1 指示
        type_metric_map = {
            "dialogue_ratio": "dialogue",
            "psychology_ratio": "psychology",
            "description_env_ratio": "description_env",
            "description_char_ratio": "description_char",
            "action_ratio": "action",
            "narration_ratio": "narration",
            "transition_ratio": "transition",
            "flashback_ratio": "flashback",
        }
        if name in type_metric_map:
            return 1.0 if p.paragraph_type == type_metric_map[name] else 0.0
        # 感官类
        for sense in ("visual", "auditory", "olfactory", "tactile", "gustatory"):
            if name == f"sensory_{sense}_per_1k":
                words = self._sensory_lexicon.get(sense, [])
                return _density_per_1k_words(p.text, words)
        raise ValueError(f"unknown metric: {name}")


# 块间方差的目标块大小(字符)。≈ 一个场景的长度,与回测对照的「单段生成文本」
# 同粒度;语料按段落累积到该字数即切块,余段并入最后一块。
_VARIANCE_CHUNK_CHARS = 1500


def _chunk_by_chars(
    paragraphs: list[ParagraphRecord], target_chars: int
) -> list[list[ParagraphRecord]]:
    """把段落按累计字数切成 ≈target_chars 的块(块间 std 的样本单位)。

    末尾不足 target_chars 的残块:若已有其它块则并入最后一块(避免短尾块拉偏
    方差),否则自成一块。整体字数 < target_chars 时返回单块。
    """
    chunks: list[list[ParagraphRecord]] = []
    current: list[ParagraphRecord] = []
    current_chars = 0
    for p in paragraphs:
        current.append(p)
        current_chars += p.char_count
        if current_chars >= target_chars:
            chunks.append(current)
            current = []
            current_chars = 0
    if current:
        if chunks:
            chunks[-1].extend(current)  # 残尾并入最后一块
        else:
            chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# 辅助纯函数
# ---------------------------------------------------------------------------


def _avg_sentence_length(text: str) -> float:
    sentences = split_sentences(text)
    if not sentences:
        return 0.0
    return statistics.fmean(len(s) for s in sentences)


def _sentence_length_std(text: str) -> float:
    sentences = split_sentences(text)
    if len(sentences) <= 1:
        return 0.0
    return statistics.pstdev(len(s) for s in sentences)


def _sentence_length_ratio(text: str, predicate: Callable[[int], bool]) -> float:
    sentences = split_sentences(text)
    if not sentences:
        return 0.0
    matched = sum(1 for s in sentences if predicate(len(s)))
    return matched / len(sentences)


def _density_per_1k_chars(text: str, chars: str) -> float:
    if not text:
        return 0.0
    count = sum(text.count(c) for c in chars)
    return count * 1000.0 / len(text)


def _density_per_1k_words(text: str, words: tuple[str, ...] | list[str]) -> float:
    if not text or not words:
        return 0.0
    count = sum(text.count(w) for w in words)
    return count * 1000.0 / len(text)


def _density_per_1k_pattern(text: str, pattern: str) -> float:
    if not text:
        return 0.0
    matches = re.findall(pattern, text)
    return len(matches) * 1000.0 / len(text)


def _word_occurrence_ratio(text: str, words: tuple[str, ...] | list[str]) -> float:
    """命中任一词的句子占比(用于 classical_word_ratio / colloquial_marker_ratio)。"""
    sentences = split_sentences(text)
    if not sentences:
        return 0.0
    matched = sum(1 for s in sentences if any(w in s for w in words))
    return matched / len(sentences)
