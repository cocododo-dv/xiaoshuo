"""segmentation 单测:启发式 8 类 + LLM 模式 + 锚定校准。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。
"""

from __future__ import annotations

import pytest

from novel_system.services.style_reference.segmentation import (
    ParagraphClassification,
    SegmentationResult,
    classify_paragraphs,
)
from novel_system.services.style_reference.segmentation.heuristic import (
    _heuristic_classify_one,
)


# ---------------------------------------------------------------------------
# 启发式 8 类逐一覆盖
# ---------------------------------------------------------------------------


def test_heuristic_dialogue() -> None:
    body = "他说:\"你好。\""
    ptype, conf = _heuristic_classify_one(body)
    assert ptype == "dialogue"
    assert conf == 0.5


def test_heuristic_dialogue_chinese_quotes() -> None:
    body = "他说:“你好,真高兴见到你,这是一段比较长的对话。”"
    ptype, _conf = _heuristic_classify_one(body)
    assert ptype == "dialogue"


def test_heuristic_transition_short() -> None:
    body = "几日后。"
    ptype, _ = _heuristic_classify_one(body)
    assert ptype == "transition"


def test_heuristic_flashback() -> None:
    body = "我记得那年她穿着蓝裙子,坐在台阶上等我,我们一起去了田野。"
    ptype, _ = _heuristic_classify_one(body)
    assert ptype == "flashback"


def test_heuristic_psychology() -> None:
    body = "他心里想着昨天的事情,觉得有些不安,暗忖该如何回应。"
    ptype, _ = _heuristic_classify_one(body)
    assert ptype == "psychology"


def test_heuristic_action() -> None:
    body = "他走出门,推开栅栏,转身关上,然后跑向远处的山,握紧了手中的信。"
    ptype, _ = _heuristic_classify_one(body)
    assert ptype == "action"


def test_heuristic_description_env() -> None:
    body = "山脚下的院子里,屋顶覆盖着雪,墙角的树枝在风中摇晃,天色阴沉。"
    ptype, _ = _heuristic_classify_one(body)
    assert ptype == "description_env"


def test_heuristic_description_char() -> None:
    body = "他的脸色苍白,眼神疲倦,眉头紧锁,嘴角带着一丝苦笑,身上穿着旧棉袄。"
    ptype, _ = _heuristic_classify_one(body)
    assert ptype == "description_char"


def test_heuristic_narration_fallback() -> None:
    body = "故事从一个平凡的午后开始,看起来一切都和往常一样,没有什么特别。"
    ptype, _ = _heuristic_classify_one(body)
    assert ptype == "narration"


# ---------------------------------------------------------------------------
# 调度入口
# ---------------------------------------------------------------------------


def test_classify_paragraphs_offline_uses_heuristic() -> None:
    paragraphs = [(0, 5, "几日后。"), (5, 30, "他心里想着,觉得不安。"), (30, 60, "故事从一个平凡的午后开始。")]
    result = classify_paragraphs(paragraphs, llm_enabled=False)
    assert isinstance(result, SegmentationResult)
    assert len(result.classifications) == 3
    assert result.calibration["fallback_to_heuristic"] is True


def test_classify_paragraphs_empty_input() -> None:
    result = classify_paragraphs([], llm_enabled=False)
    assert result.classifications == []
    assert result.calibration["input_empty"] is True


def test_classify_paragraphs_llm_disabled_ignores_client(fake_paragraph_classifier) -> None:
    """llm_enabled=False 即使传入 llm_client 也不会触发 LLM 调用。"""
    client = fake_paragraph_classifier()
    paragraphs = [(0, 10, "他说:“你好。”"), (10, 20, "几日后。")]
    result = classify_paragraphs(paragraphs, llm_enabled=False, llm_client=client)
    assert client.call_count == 0
    assert result.calibration["fallback_to_heuristic"] is True


# ---------------------------------------------------------------------------
# LLM 锚定校准
# ---------------------------------------------------------------------------


def test_classify_paragraphs_llm_agreement_high(fake_paragraph_classifier) -> None:
    """默认 fake classifier 在 anchor/bulk 上返回相同结果,agreement=1.0 → 用 fast 路径。"""
    client = fake_paragraph_classifier()
    paragraphs = [
        (0, 10, "他说:“你好。”"),
        (10, 30, "我心里想着昨天的事,觉得有些不安。"),
        (30, 60, "故事从一个平凡的午后开始,一切都和往常一样。"),
    ]
    result = classify_paragraphs(paragraphs, llm_enabled=True, llm_client=client)
    # anchor + bulk 都被调过
    assert client.call_count >= 2
    assert result.calibration["fallback_to_strong"] is False
    assert result.calibration["fast_model_agreement"] >= 0.85


def test_classify_paragraphs_llm_agreement_low_falls_back_to_strong(
    fake_paragraph_classifier,
) -> None:
    """rule=disagree_after_anchor 使 bulk 返回全 transition,与 anchor 大量不一致 → fallback to strong。"""
    client = fake_paragraph_classifier(rule="disagree_after_anchor")
    paragraphs = [
        (0, 10, "他说:“你好。”"),
        (10, 30, "我心里想着昨天的事,觉得有些不安。"),
        (30, 60, "故事从一个平凡的午后开始,一切都和往常一样。"),
    ]
    result = classify_paragraphs(paragraphs, llm_enabled=True, llm_client=client)
    assert result.calibration["fallback_to_strong"] is True
    assert result.calibration["fast_model_agreement"] < 0.85


def test_classify_paragraphs_llm_failure_falls_back_to_heuristic() -> None:
    """LLM 调用 raise 任意异常 → 降级到启发式,calibration 标 fallback_reason。"""

    class FailingClient:
        def generate(self, _request):
            raise RuntimeError("network down")

    paragraphs = [(0, 5, "几日后。"), (5, 30, "他心里想着,觉得不安。")]
    result = classify_paragraphs(paragraphs, llm_enabled=True, llm_client=FailingClient())
    assert result.calibration["fallback_to_heuristic"] is True
    assert "fallback_reason" in result.calibration


# ---------------------------------------------------------------------------
# ParagraphClassification 结构
# ---------------------------------------------------------------------------


def test_paragraph_classification_fields() -> None:
    paragraphs = [(0, 10, "他说:“你好。”")]
    result = classify_paragraphs(paragraphs, llm_enabled=False)
    c = result.classifications[0]
    assert isinstance(c, ParagraphClassification)
    assert c.paragraph_index == 0
    assert c.paragraph_type == "dialogue"
    assert 0.0 <= c.confidence <= 1.0
    assert c.classifier_confidence_level in {"high", "medium", "low"}
