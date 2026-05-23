"""LLM 段落分类器(锚定集校准)。

依据《风格参考模块重构执行手册 v1.1》§6.2:
- 前 200 段走 `style_ref_paragraph_classify_anchor`(quality_balanced)做锚定
- 余下走 `style_ref_paragraph_classify_bulk`(local_fast)
- agreement >= 0.85 用 fast 路径;< 0.85 整本 fallback 到 strong

LLM 调用直接走 `LLMClient.generate(LLMRequest)`,
参照 `reference_learning.py:974-1027` _call_llm_node 的契约,但简化:
- scene_id / chapter_id / bundle_id 这些 LLMRequest 不需要(它们是 LLMTaskRunner.run 入参)
- 直接构造 LLMRequest 给 client.generate(...) 即可
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from novel_system.services.llm_client import LLMRequest, load_model_routing_config
from novel_system.services.prompt_builder import load_prompt_templates
from novel_system.services.style_reference.text_utils import compact_ws

if TYPE_CHECKING:
    from novel_system.services.style_reference.segmentation import (
        ParagraphClassification,
        SegmentationResult,
    )

logger = logging.getLogger(__name__)

NODE_ANCHOR = "style_ref_paragraph_classify_anchor"
NODE_BULK = "style_ref_paragraph_classify_bulk"

ANCHOR_SIZE = 200
AGREEMENT_THRESHOLD = 0.85

# 一次 LLM 调用分类多少段(避免 prompt 过长)
BATCH_SIZE = 25


class SegmentationLLMError(Exception):
    """段落分类 LLM 调用失败。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def classify_with_llm(
    paragraphs: list[tuple[int, int, str]],
    llm_client: Any,
) -> SegmentationResult:
    """锚定集校准的 LLM 段落分类。"""
    from novel_system.services.style_reference.segmentation import (
        ParagraphClassification,
        SegmentationResult,
    )

    total = len(paragraphs)
    anchor_size = min(ANCHOR_SIZE, total)
    anchor_paras = paragraphs[:anchor_size]

    # Step 1: 锚定集走强模型
    anchor_strong = _classify_via_node(anchor_paras, NODE_ANCHOR, llm_client)

    # Step 2: 锚定集再走快模型,校准一致性
    anchor_fast = _classify_via_node(anchor_paras, NODE_BULK, llm_client)
    agreement = _compute_agreement(anchor_strong, anchor_fast)

    fallback_to_strong = agreement < AGREEMENT_THRESHOLD

    # Step 3: 余下段落按选定路径
    rest = paragraphs[anchor_size:]
    if fallback_to_strong:
        rest_classified = _classify_via_node(rest, NODE_ANCHOR, llm_client) if rest else []
    else:
        rest_classified = _classify_via_node(rest, NODE_BULK, llm_client) if rest else []

    # 合并(锚定段以 strong 结果为准)
    merged: list[ParagraphClassification] = []
    for idx, (ptype, conf) in enumerate(anchor_strong):
        merged.append(
            ParagraphClassification(
                paragraph_index=idx,
                paragraph_type=ptype,
                confidence=conf,
                classifier_confidence_level=_confidence_level(conf),
            )
        )
    for offset, (ptype, conf) in enumerate(rest_classified):
        merged.append(
            ParagraphClassification(
                paragraph_index=anchor_size + offset,
                paragraph_type=ptype,
                confidence=conf,
                classifier_confidence_level=_confidence_level(conf),
            )
        )

    calibration = {
        "anchor_size": anchor_size,
        "fast_model_agreement": agreement,
        "fallback_to_strong": fallback_to_strong,
        "fallback_to_heuristic": False,
    }
    return SegmentationResult(classifications=merged, calibration=calibration)


def _confidence_level(conf: float) -> str:
    if conf >= 0.8:
        return "high"
    if conf >= 0.5:
        return "medium"
    return "low"


def _compute_agreement(
    a: list[tuple[str, float]], b: list[tuple[str, float]]
) -> float:
    """两个 paragraph_type 序列的一致性比例。"""
    if not a or not b:
        return 0.0
    pairs = min(len(a), len(b))
    matched = sum(1 for i in range(pairs) if a[i][0] == b[i][0])
    return matched / pairs


def _classify_via_node(
    paragraphs: list[tuple[int, int, str]],
    node_id: str,
    llm_client: Any,
) -> list[tuple[str, float]]:
    """对一批段落调指定 LLM 节点,返回 [(paragraph_type, confidence), ...]。

    内部按 BATCH_SIZE 分批调用以避免 prompt 过长。
    """
    if not paragraphs:
        return []

    try:
        routing = load_model_routing_config()
        task_routing = getattr(routing, "task_routing", {})
        node_routing = getattr(routing, "node_routing", None)
        if isinstance(node_routing, dict) and node_id in node_routing:
            task_config = node_routing[node_id]
        elif node_id in task_routing:
            task_config = task_routing[node_id]
        else:
            raise SegmentationLLMError(
                "STYLE_REF_LLM_ROUTE_MISSING",
                f"task routing not configured for node {node_id!r}",
            )
        templates = load_prompt_templates()
        if node_id not in templates:
            raise SegmentationLLMError(
                "STYLE_REF_LLM_PROMPT_MISSING",
                f"prompt template not configured for node {node_id!r}",
            )
        template = templates[node_id]
    except SegmentationLLMError:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise SegmentationLLMError(
            "STYLE_REF_LLM_CONFIG_LOAD_FAILED",
            f"failed to load routing or prompt: {exc}",
        ) from exc

    results: list[tuple[str, float]] = []
    for batch_start in range(0, len(paragraphs), BATCH_SIZE):
        batch = paragraphs[batch_start : batch_start + BATCH_SIZE]
        batch_payload = {
            "paragraphs": [
                {"paragraph_index": batch_start + i, "text": compact_ws(body)[:600]}
                for i, (_s, _e, body) in enumerate(batch)
            ]
        }
        user_prompt = _format_user_prompt(template.task_prompt, batch_payload)
        request = LLMRequest(
            model=task_config.model,
            messages=[
                {"role": "system", "content": template.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=task_config.temperature,
            max_output_tokens=task_config.max_output_tokens,
            response_format=task_config.response_format,
            provider=task_config.provider,
            node_id=node_id,
            provider_id=getattr(task_config, "provider_id", None),
            account_id=getattr(task_config, "account_id", None),
            reasoning_level=getattr(task_config, "reasoning_level", "medium"),
            api_mode=getattr(task_config, "api_mode", "responses"),
            credential_mode=getattr(task_config, "credential_mode", None),
            provider_options=getattr(task_config, "provider_options", {}),
            response_schema=template.structured_schema,
        )
        try:
            response = llm_client.generate(request)
        except Exception as exc:  # pylint: disable=broad-except
            raise SegmentationLLMError(
                "STYLE_REF_LLM_GENERATE_FAILED",
                f"LLMClient.generate failed for node {node_id!r}: {exc}",
            ) from exc

        parsed = _parse_response(response)
        if len(parsed) != len(batch):
            logger.warning(
                "segmentation LLM returned %d classifications for batch of %d; padding with narration",
                len(parsed),
                len(batch),
            )
            while len(parsed) < len(batch):
                parsed.append(("narration", 0.3))
            parsed = parsed[: len(batch)]
        results.extend(parsed)
    return results


def _format_user_prompt(task_prompt: str, payload: dict[str, Any]) -> str:
    """简单模板填充。如果 task_prompt 含 `{paragraphs}` 占位符则替换;否则追加。"""
    import json

    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    if "{paragraphs}" in task_prompt:
        return task_prompt.replace("{paragraphs}", payload_json)
    return f"{task_prompt}\n\n{payload_json}"


def _parse_response(response: Any) -> list[tuple[str, float]]:
    """从 LLMResponse.structured_output 解析 [(paragraph_type, confidence), ...]。"""
    structured = getattr(response, "structured_output", None) or {}
    classifications = structured.get("classifications") or []
    if not isinstance(classifications, list):
        return []
    parsed: list[tuple[str, float]] = []
    confidence_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
    for item in classifications:
        if not isinstance(item, dict):
            continue
        ptype = str(item.get("paragraph_type") or "narration")
        conf_label = str(item.get("confidence") or "medium")
        conf = confidence_map.get(conf_label, 0.5)
        parsed.append((ptype, conf))
    return parsed
