"""启发式段落分类(无 LLM)。

NOVEL_SYSTEM_LLM_ENABLED=false 默认下的 fallback 路径。8 类 ParagraphType:
- dialogue / narration / psychology / description_env / description_char
- action / transition / flashback

按设计文档 §6.2 与 plan,本启发式 confidence=0.5,calibration 中标
`fallback_to_heuristic=true`;PR-5 前端在 books detail 显示降级横幅。
"""

from __future__ import annotations

from novel_system.services.style_reference.segmentation.types import (
    ParagraphClassification,
    SegmentationResult,
)

# 启发式标记词
_DIALOGUE_QUOTES = ("“", "”", '"', "「", "」", "『", "』")
_FLASHBACK_MARKERS = ("记得", "那年", "从前", "昔日", "旧时", "想起", "回忆", "当年")
_PSYCHOLOGY_MARKERS = ("想着", "觉得", "暗忖", "恍惚", "心里", "心中", "暗想", "想到")
_ACTION_VERBS = ("走", "跑", "推", "拉", "握", "扑", "转身", "起身", "蹲", "迈", "撞")
_ENV_MARKERS = ("屋", "山", "天", "路", "院", "墙", "树", "河", "雪", "雾", "云", "风", "雨")
_CHAR_MARKERS = ("脸", "眼", "眉", "嘴", "手", "穿着", "身上", "头发", "胡子", "皱纹")


def _heuristic_classify_one(body: str) -> tuple[str, float]:
    """对单段返回 (paragraph_type, confidence)。confidence 固定 0.5。

    规则优先级(高 → 低,确保语义特征压过纯字数判断):
    1. dialogue        含任一种引号
    2. flashback       时间追忆标记词
    3. psychology      心理动词
    4. action          ≥3 个动作动词
    5. description_env ≥4 个环境名词
    6. description_char≥3 个人物描写名词
    7. transition      上述均无特征 + 段较短(<30 字)
    8. narration       兜底
    """
    # 1. dialogue:含引号(任一种)
    if any(q in body for q in _DIALOGUE_QUOTES):
        return "dialogue", 0.5
    # 2. flashback:时间追忆标记
    if any(w in body for w in _FLASHBACK_MARKERS):
        return "flashback", 0.5
    # 3. psychology:心理动词
    if any(w in body for w in _PSYCHOLOGY_MARKERS):
        return "psychology", 0.5
    # 4. action:多个动作动词
    action_hits = sum(body.count(v) for v in _ACTION_VERBS)
    if action_hits >= 3:
        return "action", 0.5
    # 5. description_env:多个环境名词
    env_hits = sum(body.count(m) for m in _ENV_MARKERS)
    if env_hits >= 4:
        return "description_env", 0.5
    # 6. description_char:多个人物描写名词
    char_hits = sum(body.count(m) for m in _CHAR_MARKERS)
    if char_hits >= 3:
        return "description_char", 0.5
    # 7. transition:很短的段且无其他特征
    if len(body) < 30:
        return "transition", 0.5
    # 8. 兜底:narration
    return "narration", 0.5


def classify_heuristic(
    paragraphs: list[tuple[int, int, str]],
) -> SegmentationResult:
    """对全部段执行启发式分类。"""
    classifications: list[ParagraphClassification] = []
    for idx, (_start, _end, body) in enumerate(paragraphs):
        ptype, conf = _heuristic_classify_one(body)
        classifications.append(
            ParagraphClassification(
                paragraph_index=idx,
                paragraph_type=ptype,
                confidence=conf,
                classifier_confidence_level="low",
            )
        )

    calibration = {
        "fallback_to_heuristic": True,
        "anchor_size": 0,
        "fast_model_agreement": None,
        "fallback_to_strong": False,
    }
    return SegmentationResult(classifications=classifications, calibration=calibration)
