"""MetricsEngine 单测:26 项 MetricName 纯函数计算 + 方差 + 边界。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。
"""

from __future__ import annotations

from novel_system.services.style_reference.metrics import (
    METRIC_NAMES,
    MetricsEngine,
    ParagraphRecord,
)


def _engine() -> MetricsEngine:
    return MetricsEngine()


def test_metric_names_count() -> None:
    assert len(METRIC_NAMES) == 26


def test_compute_all_returns_all_metrics() -> None:
    paragraphs = [ParagraphRecord(text="天气晴朗。", paragraph_type="narration")]
    result = _engine().compute_all(paragraphs)
    assert set(result.keys()) == set(METRIC_NAMES)


def test_compute_all_empty_returns_zeros() -> None:
    result = _engine().compute_all([])
    assert all(v == 0.0 for v in result.values())


def test_compute_with_variance_returns_tuples() -> None:
    paragraphs = [
        ParagraphRecord(text="天气很好。", paragraph_type="narration"),
        ParagraphRecord(text="今天下雨了!", paragraph_type="narration"),
    ]
    result = _engine().compute_with_variance(paragraphs)
    assert all(isinstance(v, tuple) and len(v) == 2 for v in result.values())


def test_avg_sentence_length() -> None:
    paragraphs = [ParagraphRecord(text="一句话。两句话。", paragraph_type="narration")]
    result = _engine().compute_all(paragraphs)
    # 两个句子各 3 字
    assert result["avg_sentence_length"] == 3.0


def test_short_long_sentence_ratio() -> None:
    short_text = "短。短。短。"
    # 长句 long_sentence_ratio 阈值是 >=30 字
    long_text = "这是一个明显超过三十字门槛的中文长句用来测试长句指标的计算逻辑确认覆盖无误。"
    paragraphs = [
        ParagraphRecord(text=short_text, paragraph_type="narration"),
        ParagraphRecord(text=long_text, paragraph_type="narration"),
    ]
    result = _engine().compute_all(paragraphs)
    assert result["short_sentence_ratio"] > 0
    assert result["long_sentence_ratio"] > 0


def test_punctuation_density() -> None:
    text = "天气好,真的很好,实在是好。"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="narration")]
    result = _engine().compute_all(paragraphs)
    assert result["punctuation_density_per_1k"] > 0


def test_ellipsis_density() -> None:
    text = "他说……然后……走了。"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="narration")]
    result = _engine().compute_all(paragraphs)
    assert result["ellipsis_density_per_1k"] > 0


def test_dash_em_density() -> None:
    text = "他说——好的——走了。"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="narration")]
    result = _engine().compute_all(paragraphs)
    assert result["dash_em_density_per_1k"] > 0


def test_classical_word_ratio() -> None:
    classical = "学而时习之,不亦说乎?有朋自远方来,不亦乐乎?"
    modern = "天气很好。我出门去。"
    paragraphs_c = [ParagraphRecord(text=classical, paragraph_type="narration")]
    paragraphs_m = [ParagraphRecord(text=modern, paragraph_type="narration")]
    r_c = _engine().compute_all(paragraphs_c)["classical_word_ratio"]
    r_m = _engine().compute_all(paragraphs_m)["classical_word_ratio"]
    assert r_c > r_m


def test_colloquial_marker_ratio() -> None:
    colloq = "走吧。来呢。好啊。嗯。"
    formal = "他向门口走去,看见院子里的雪。"
    r_c = _engine().compute_all(
        [ParagraphRecord(text=colloq, paragraph_type="narration")]
    )["colloquial_marker_ratio"]
    r_f = _engine().compute_all(
        [ParagraphRecord(text=formal, paragraph_type="narration")]
    )["colloquial_marker_ratio"]
    assert r_c > r_f


def test_metaphor_density() -> None:
    text = "她像一朵花,仿佛一颗星,犹如清晨的露珠。"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="narration")]
    result = _engine().compute_all(paragraphs)
    assert result["metaphor_density_per_1k"] > 0


def test_personification_placeholder() -> None:
    """PR-2 占位实现:personification 词表为空,density 应为 0。"""
    text = "风在哭,树在笑,云在叹息。"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="narration")]
    result = _engine().compute_all(paragraphs)
    assert result["personification_density_per_1k"] == 0.0


def test_dialogue_ratio_by_paragraph_type() -> None:
    paragraphs = [
        ParagraphRecord(text="他说:你好。", paragraph_type="dialogue"),
        ParagraphRecord(text="他点点头。", paragraph_type="dialogue"),
        ParagraphRecord(text="天气很好。", paragraph_type="narration"),
        ParagraphRecord(text="他想着昨天。", paragraph_type="psychology"),
    ]
    result = _engine().compute_all(paragraphs)
    assert result["dialogue_ratio"] == 0.5
    assert result["psychology_ratio"] == 0.25
    assert result["narration_ratio"] == 0.25


def test_all_paragraph_type_ratios_covered() -> None:
    paragraphs = [
        ParagraphRecord(text="对话。", paragraph_type="dialogue"),
        ParagraphRecord(text="心理。", paragraph_type="psychology"),
        ParagraphRecord(text="环境。", paragraph_type="description_env"),
        ParagraphRecord(text="人物。", paragraph_type="description_char"),
        ParagraphRecord(text="动作。", paragraph_type="action"),
        ParagraphRecord(text="叙述。", paragraph_type="narration"),
        ParagraphRecord(text="过渡。", paragraph_type="transition"),
        ParagraphRecord(text="闪回。", paragraph_type="flashback"),
    ]
    result = _engine().compute_all(paragraphs)
    # 每个 type 各 1 段,占比 1/8 = 0.125
    for metric in (
        "dialogue_ratio",
        "psychology_ratio",
        "description_env_ratio",
        "description_char_ratio",
        "action_ratio",
        "narration_ratio",
        "transition_ratio",
        "flashback_ratio",
    ):
        assert result[metric] == 0.125, f"{metric} 期望 0.125,实际 {result[metric]}"


def test_sensory_visual() -> None:
    text = "他看见光,望着雪,瞧着影子。蓝的山,红的衣裳。"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="description_env")]
    result = _engine().compute_all(paragraphs)
    assert result["sensory_visual_per_1k"] > 0


def test_sensory_auditory() -> None:
    text = "他听见声音,闻到响动,嘈杂的喧嚣。"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="description_env")]
    result = _engine().compute_all(paragraphs)
    assert result["sensory_auditory_per_1k"] > 0


def test_sensory_olfactory() -> None:
    text = "屋里弥漫着香味,刺鼻的气味,馥郁的芬芳。"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="description_env")]
    result = _engine().compute_all(paragraphs)
    assert result["sensory_olfactory_per_1k"] > 0


def test_sensory_tactile() -> None:
    text = "他摸到冷,碰到热,抚着柔软的皮毛。"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="description_env")]
    result = _engine().compute_all(paragraphs)
    assert result["sensory_tactile_per_1k"] > 0


def test_sensory_gustatory() -> None:
    text = "她尝了尝,甜的咸的酸的,品着茶。"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="description_env")]
    result = _engine().compute_all(paragraphs)
    assert result["sensory_gustatory_per_1k"] > 0


def test_question_density() -> None:
    text = "你是谁?为什么在这里?要去哪儿?"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="dialogue")]
    result = _engine().compute_all(paragraphs)
    assert result["question_density_per_1k"] > 0


def test_semicolon_density() -> None:
    text = "天气好;心情好;一切都好。"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="narration")]
    result = _engine().compute_all(paragraphs)
    assert result["semicolon_density_per_1k"] > 0


def test_sentence_length_std_zero_for_single_sentence() -> None:
    text = "只有一句话"
    paragraphs = [ParagraphRecord(text=text, paragraph_type="narration")]
    result = _engine().compute_all(paragraphs)
    assert result["sentence_length_std"] == 0.0


def test_compute_with_variance_std_is_chunk_level() -> None:
    """std 现为块间标准差(块 ≈1500 字),非逐段 std。

    校准修正(2026-06):逐段 0/1 的段级 std 噪声过大(~0.5)使
    tolerance=max(std×1.25, floor) 宽到几乎不拦截;改用块间 std。
    两块 dialogue 占比 [1.0, 0.0] → std=0.5;mean 仍为全文逐段均值。
    paragraph_type 比例与文本内容无关,只用 char_count 控分块、type 定占比。
    """
    long = "话" * 800  # 单段 800 字;两段累计 ≥1500 切一块
    paragraphs = [
        ParagraphRecord(text=long, paragraph_type="dialogue"),
        ParagraphRecord(text=long, paragraph_type="dialogue"),   # 块1:全对话 → 1.0
        ParagraphRecord(text=long, paragraph_type="narration"),
        ParagraphRecord(text=long, paragraph_type="narration"),  # 块2:全叙述 → 0.0
    ]
    mean, std = _engine().compute_with_variance(paragraphs)["dialogue_ratio"]
    assert mean == pytest.approx(0.5, rel=1e-3)
    assert std == pytest.approx(0.5, rel=1e-3)


def test_compute_with_variance_single_chunk_std_zero() -> None:
    """短语料(不足一块)无块间样本 → std=0,由 tolerance floor 兜底。"""
    paragraphs = [
        ParagraphRecord(text="对话。", paragraph_type="dialogue"),
        ParagraphRecord(text="叙述文字。", paragraph_type="narration"),
        ParagraphRecord(text="对话。", paragraph_type="dialogue"),
    ]
    mean, std = _engine().compute_with_variance(paragraphs)["dialogue_ratio"]
    assert mean == pytest.approx(2 / 3, rel=1e-3)  # mean 不受分块影响
    assert std == 0.0


def test_explicit_sensory_lexicon_injected() -> None:
    """允许测试注入自定义词表(便于隔离 yaml 文件依赖)。"""
    engine = MetricsEngine(sensory_lexicon={"visual": ["蓝"], "auditory": [], "olfactory": [], "tactile": [], "gustatory": []})
    paragraphs = [ParagraphRecord(text="蓝天蓝海蓝", paragraph_type="description_env")]
    result = engine.compute_all(paragraphs)
    assert result["sensory_visual_per_1k"] > 0
    assert result["sensory_auditory_per_1k"] == 0


import pytest  # noqa: E402  (avoid circular if any)
