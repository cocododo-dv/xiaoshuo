"""ProfileSynthesizer — 8 sub_dim findings → StyleProfile。

参见《风格参考模块重构执行手册 v1.1》§6.1(`style_ref_synthesize_profile`)与
plans/style-reference-v1-1-fancy-shannon.md §"ProfileSynthesizer 流程"。

profile_json 结构:
  - narrative_summary(LLM 产出)
  - metrics_baseline(从 book.stats_json.metrics 直读)
  - scene_samples_index({paragraph_type: [quote_id, ...]} 按 quotes 分桶)
  - sub_dimensions({sub_dim_path: {confidence, observation_count, ...}})
  - style_features / narrative_patterns / banned_replication_rules /
    calibration_guidance(LLM 产出,materialization 时分发到 4 集合)
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from novel_system.services.llm_client import LLMRequest, load_model_routing_config
from novel_system.services.prompt_builder import load_prompt_templates
from novel_system.services.style_reference.errors import LLMRequiredError, StyleReferenceError
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import (
    ProfileStatus,
    SynthesizedProfile,
)

if TYPE_CHECKING:
    from novel_system.db.models import (
        StyleReferenceFinding,
        StyleReferenceProfile,
        StyleReferenceQuote,
    )

logger = logging.getLogger(__name__)

SYNTHESIZE_NODE_ID = "style_ref_synthesize_profile"


class SynthesizeError(StyleReferenceError):
    """ProfileSynthesizer 内部错误。"""


class ProfileSynthesizer:
    """聚合 8 sub_dim findings → StyleReferenceProfile。"""

    def __init__(
        self,
        session: Session,
        *,
        llm_client: Any | None = None,
        llm_enabled: bool | None = None,
    ) -> None:
        self.session = session
        self.repo = StyleReferenceRepository(session)
        self._llm_client = llm_client
        if llm_enabled is None:
            from novel_system.settings import get_settings

            llm_enabled = bool(get_settings().llm_enabled)
        self._llm_enabled = llm_enabled

    def synthesize(self, book_id: str, run_id: str) -> "StyleReferenceProfile":
        if not self._llm_enabled or self._llm_client is None:
            raise LLMRequiredError(operation="synthesize_profile")

        book = self.repo.get_book(book_id)
        if book is None:
            raise SynthesizeError(f"book {book_id!r} not found")

        findings = self.repo.list_findings(book_id=book_id, run_id=run_id)
        quotes = self.repo.list_quotes(book_id)

        sub_dim_summaries = _aggregate_sub_dim_stats(findings, quotes)
        metrics_baseline = (book.stats_json or {}).get("metrics", {})
        scene_samples_index = _build_scene_samples_index(quotes)
        sample_quotes_payload = _build_sample_quotes_payload(findings, quotes)

        payload = {
            "book_title": book.title,
            "sub_dimensions": sub_dim_summaries,
            "metrics_baseline": _prune_metrics_for_prompt(metrics_baseline),
            "sample_quotes": sample_quotes_payload,
        }

        structured = self._call_llm(SYNTHESIZE_NODE_ID, payload)
        try:
            synthesized = SynthesizedProfile.model_validate(structured)
        except ValidationError as exc:
            raise SynthesizeError(
                f"LLM response failed Pydantic validation: {exc}"
            ) from exc

        profile_json: dict[str, Any] = {
            "narrative_summary": synthesized.narrative_summary,
            "metrics_baseline": metrics_baseline,
            "scene_samples_index": scene_samples_index,
            "sub_dimensions": sub_dim_summaries,
            "style_features": synthesized.style_features,
            "narrative_patterns": synthesized.narrative_patterns,
            "banned_replication_rules": synthesized.banned_replication_rules,
            "calibration_guidance": synthesized.calibration_guidance,
        }

        profile = self.repo.create_profile(
            profile_id=f"sr_profile_{uuid.uuid4().hex[:12]}",
            book_id=book_id,
            run_id=run_id,
            title=synthesized.profile_title,
            status=ProfileStatus.DRAFT.value,
            profile_json=profile_json,
            coverage_json={
                "sub_dim_count": len(sub_dim_summaries),
                "findings_count": len(findings),
                "quotes_count": len(quotes),
            },
            source_finding_ids_json=[f.finding_id for f in findings],
        )
        return profile

    # ------------------------------------------------------------------ LLM

    def _call_llm(self, node_id: str, payload: dict) -> dict[str, Any]:
        try:
            routing = load_model_routing_config()
            task_config = getattr(routing, "task_routing", {})[node_id]
            template = load_prompt_templates()[node_id]
        except KeyError as exc:
            raise SynthesizeError(
                f"task routing / prompt template missing for {node_id!r}: {exc}"
            ) from exc

        user_prompt = template.task_prompt + "\n\n" + json.dumps(
            payload, ensure_ascii=False
        )
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
            response = self._llm_client.generate(request)
        except Exception as exc:  # pylint: disable=broad-except
            raise SynthesizeError(
                f"LLMClient.generate failed for {node_id!r}: {exc}"
            ) from exc
        return getattr(response, "structured_output", None) or {}


# ---------------------------------------------------------------------------
# 聚合辅助函数
# ---------------------------------------------------------------------------


def _aggregate_sub_dim_stats(
    findings: list["StyleReferenceFinding"],
    quotes: list["StyleReferenceQuote"],
) -> dict[str, dict[str, Any]]:
    """按 sub_dimension 分桶,统计 obs / forbid / quote 数量与置信度概要。"""
    by_sub_dim: dict[str, dict[str, int]] = defaultdict(
        lambda: {"observation_count": 0, "forbidden_pattern_count": 0, "quote_count": 0}
    )
    confidence_counter: dict[str, Counter] = defaultdict(Counter)

    for f in findings:
        key = f.sub_dimension
        if f.finding_kind == "observation":
            by_sub_dim[key]["observation_count"] += 1
        elif f.finding_kind == "forbidden_pattern":
            by_sub_dim[key]["forbidden_pattern_count"] += 1
        confidence_counter[key][f.confidence or "medium"] += 1

    # quote_count 按 illustrates_dims 分桶
    for q in quotes:
        for dim in q.illustrates_dims or []:
            if dim in by_sub_dim:
                by_sub_dim[dim]["quote_count"] += 1

    result: dict[str, dict[str, Any]] = {}
    for sub_dim, counts in by_sub_dim.items():
        conf = confidence_counter[sub_dim].most_common(1)
        result[sub_dim] = {
            **counts,
            "confidence": conf[0][0] if conf else "medium",
        }
    return result


def _build_scene_samples_index(
    quotes: list["StyleReferenceQuote"],
) -> dict[str, list[str]]:
    """按 paragraph_type 把 quote_id 分桶。

    `quote.paragraph_id` 关联回 paragraph,这里只用 quote_id 作为索引值;
    Few-shot 调用方按 paragraph_type 拉对应 quote_id list 再 fetch quote_text。
    quote.extracted_features.paragraph_type(若提供)优先;否则按 illustrates_dims
    第一个分类前缀粗推断。
    """
    index: dict[str, list[str]] = defaultdict(list)
    for q in quotes:
        # 简化:优先用 extracted_features.paragraph_type,否则归 "narration"
        ptype = (q.extracted_features or {}).get("paragraph_type", "narration")
        index[ptype].append(q.quote_id)
    return dict(index)


def _build_sample_quotes_payload(
    findings: list["StyleReferenceFinding"],
    quotes: list["StyleReferenceQuote"],
) -> list[dict[str, str]]:
    """按 sub_dim 取每条 finding 的 statement(截断 120 字)+ 1 个代表性 quote 文本(截断 200 字)。

    控制 prompt token 在合理范围(每 finding < 400 字)。
    """
    quote_by_id = {q.quote_id: q for q in quotes}
    quotes_used: set[str] = set()
    payload: list[dict[str, str]] = []
    for f in findings:
        repr_quote: str = ""
        for q in quotes:
            if q.quote_id in quotes_used:
                continue
            if f.sub_dimension in (q.illustrates_dims or []):
                repr_quote = (q.quote_text or "")[:200]
                quotes_used.add(q.quote_id)
                break
        payload.append(
            {
                "sub_dimension": f.sub_dimension,
                "finding_kind": f.finding_kind,
                "statement": (f.statement or "")[:120],
                "representative_quote": repr_quote,
            }
        )
    return payload


def _prune_metrics_for_prompt(metrics: dict[str, Any]) -> dict[str, dict[str, float]]:
    """只取每项 metric 的 mean / std(去掉 sample_count 等),控制 prompt 体积。"""
    pruned: dict[str, dict[str, float]] = {}
    for name, val in (metrics or {}).items():
        if isinstance(val, dict):
            pruned[name] = {
                "mean": float(val.get("mean", 0.0)),
                "std": float(val.get("std", 0.0)),
            }
    return pruned
