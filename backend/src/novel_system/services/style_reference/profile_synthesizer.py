"""ProfileSynthesizer — 16 sub_dim findings → StyleProfile。

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
from novel_system.services.llm_accounting import LLMCallContext
from novel_system.services.prompt_builder import load_prompt_templates
from novel_system.services.style_reference._llm_helper import LLMNodeError, call_llm_node
from novel_system.services.style_reference.errors import LLMRequiredError, StyleReferenceError
from novel_system.services.style_reference.policy import ensure_cloud_llm_allowed
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import (
    ProfileStatus,
    SynthesizedProfile,
)
from novel_system.services.style_reference.untrusted_data import UntrustedPayload

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
    """聚合 16 sub_dim findings → StyleReferenceProfile。"""

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
        # 附录 B — local_only 的书禁止把 finding/quote 派生内容送往云端 LLM
        ensure_cloud_llm_allowed(book, operation="synthesize_profile")

        findings = self.repo.list_findings(book_id=book_id, run_id=run_id)
        # PR-23 — 被驳回的 finding 不进聚合 payload / source_finding_ids_json;
        # pending + approved 保留(审阅是可选环节,与 review 端点三态语义一致)
        findings = [f for f in findings if f.status != "rejected"]
        # 2026-07 勘误:quotes 原为 list_quotes(book_id) 全书跨 run——同书重复抽取
        # (未 reclassify)时,旧 run 的引文会混进本 profile 的 scene_samples_index /
        # quote_count / few-shot 池。改为 **run-scoped**:仅取本 run findings 经
        # evidence 关联的 quotes(与 source_finding_ids_json 同一物料来源)。
        quotes = self._run_scoped_quotes(findings)

        sub_dim_summaries = _aggregate_sub_dim_stats(findings, quotes)
        metrics_baseline = (book.stats_json or {}).get("metrics", {})
        paragraph_types = {
            p.paragraph_id: p.paragraph_type
            for p in self.repo.list_paragraphs(book_id)
        }
        scene_samples_index = _build_scene_samples_index(quotes, paragraph_types)
        sample_quotes_payload = _build_sample_quotes_payload(findings, quotes)

        payload = {
            "book_title": book.title,
            "sub_dimensions": sub_dim_summaries,
            "metrics_baseline": _prune_metrics_for_prompt(metrics_baseline),
            "sample_quotes": sample_quotes_payload,
        }

        structured = self._call_llm(
            SYNTHESIZE_NODE_ID,
            payload,
            book_id=book_id,
            run_id=run_id,
        )
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
        # 立项 C — profile 就绪即建三粒度 RAG 索引(Strategy C 召回的数据底座)。
        # 容错:向量后端不可用(如 Windows 原生 chroma)或失败均不阻断 synthesize。
        try:
            from novel_system.services.style_reference.rag import build_rag_index

            build_rag_index(self.session, profile, book_id=book_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "rag index build failed for profile %s", profile.profile_id, exc_info=True
            )
        return profile

    def _run_scoped_quotes(self, findings: list["StyleReferenceFinding"]) -> list["StyleReferenceQuote"]:
        """本 run findings 经 evidence 关联的 quotes(排序确定:created_at, quote_id)。"""
        finding_ids = [f.finding_id for f in findings]
        evidences = self.repo.list_evidences_for_findings(finding_ids)
        quote_ids: list[str] = []
        seen: set[str] = set()
        for ev in evidences:
            if ev.quote_id and ev.quote_id not in seen:
                seen.add(ev.quote_id)
                quote_ids.append(ev.quote_id)
        quotes = self.repo.list_quotes_by_ids(quote_ids)
        quotes.sort(key=lambda q: (q.created_at or "", q.quote_id))
        return quotes

    # ------------------------------------------------------------------ LLM

    def _call_llm(
        self,
        node_id: str,
        payload: dict,
        *,
        book_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        # PR-8 §"_call_llm 统一" — 复用 _llm_helper.call_llm_node
        try:
            return call_llm_node(
                node_id,
                UntrustedPayload(payload),
                self._llm_client,
                session=self.session,
                context=LLMCallContext(
                    scope_type="style_reference_book",
                    scope_id=book_id,
                    node_id=node_id,
                    step=f"synthesize:{run_id}",
                ),
            )
        except LLMNodeError as exc:
            raise SynthesizeError(str(exc)) from exc


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
    paragraph_types: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """按 paragraph_type 把 quote_id 分桶。

    `quote.paragraph_id` 关联回 paragraph,这里只用 quote_id 作为索引值;
    Few-shot 调用方按 paragraph_type 拉对应 quote_id list 再 fetch quote_text。

    只收 anchor_kind=paragraph_quote 的真实原文引文:counter_example 是与原作
    风格**相悖**的合成反例,author_avoidance 是统计说明文本,二者进样例索引会被
    few-shot 当作风格范例注入。段落类型优先用段落表实测(`paragraph_types`),
    其次 quote 落库时冗余的 extracted_features.paragraph_type,最后回退 "narration"。
    """
    paragraph_types = paragraph_types or {}
    index: dict[str, list[str]] = defaultdict(list)
    for q in quotes:
        feats = q.extracted_features or {}
        if feats.get("anchor_kind", "paragraph_quote") != "paragraph_quote":
            continue
        if not q.paragraph_id:
            continue
        ptype = (
            paragraph_types.get(q.paragraph_id)
            or feats.get("paragraph_type")
            or "narration"
        )
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
