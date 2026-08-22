"""ProfileSynthesizer — 16 sub_dim findings → StyleProfile。

参见《风格参考模块重构执行手册 v1.1》§6.1(`style_ref_synthesize_profile`)与
plans/style-reference-v1-1-fancy-shannon.md §"ProfileSynthesizer 流程"。

profile_json 结构:
  - reference_basis(当前参考语料的动态来源契约，不含固定作者枚举)
  - narrative_summary(可复算精确统计，仅供内部审计/RAG)
  - qualitative_summary(LLM 产出并经过原文重合过滤，供生成提示使用)
  - metrics_baseline(从 book.stats_json.metrics 直读)
  - scene_samples_index({paragraph_type: [quote_id, ...]} 按 quotes 分桶)
  - sub_dimensions({sub_dim_path: {confidence, observation_count, ...}})
  - style_features / narrative_patterns / banned_replication_rules /
    calibration_guidance(LLM 产出,materialization 时分发到 4 集合)
"""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from novel_system.services.llm_accounting import LLMCallContext
from novel_system.services.context_budget import estimate_tokens
from novel_system.services.prompt_builder import PromptTemplate, load_prompt_templates
from novel_system.services.style_reference._llm_helper import LLMNodeError, call_llm_node
from novel_system.services.style_reference.errors import LLMRequiredError, StyleReferenceError
from novel_system.services.style_reference.policy import ensure_cloud_llm_allowed
from novel_system.services.style_reference.profile_fields import REFERENCE_BASIS_VERSION
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import (
    ProfileStatus,
    SynthesizedProfile,
)
from novel_system.services.style_reference.untrusted_data import (
    UntrustedPayload,
    render_untrusted_system_prompt,
    render_untrusted_user_prompt,
)
from novel_system.services.style_reference.validation.plagiarism import (
    check_plagiarism,
)

if TYPE_CHECKING:
    from novel_system.db.models import (
        StyleReferenceEvidence,
        StyleReferenceFinding,
        StyleReferenceProfile,
        StyleReferenceQuote,
    )

logger = logging.getLogger(__name__)

SYNTHESIZE_NODE_ID = "style_ref_synthesize_profile"
_PROFILE_SOURCE_OVERLAP_THRESHOLD = 8
_SYNTHESIS_SCHEMA_SAFETY_TOKENS = 128
_SYNTHESIS_TOKENIZER_SAFETY_MULTIPLIER = 1.25
_SYNTHESIS_STATEMENT_MAX_CHARS = 120
_CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}
_STATUS_RANK = {"approved": 1, "pending": 0}
_SYNTHESIS_METRIC_PRIORITY: tuple[str, ...] = (
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
    "dialogue_ratio",
    "psychology_ratio",
    "description_env_ratio",
    "description_char_ratio",
    "action_ratio",
    "narration_ratio",
    "paragraph_mean_chars",
    "paragraph_length_std_chars",
    "paragraphs_per_1k",
    "single_sentence_paragraph_ratio",
    "quote_led_paragraph_ratio",
)


class SynthesizeError(StyleReferenceError):
    """ProfileSynthesizer 内部错误。"""


class ProfileTextIntegrityError(SynthesizeError):
    """画像文本含编码替换符或控制字符，不能进入运行时提示。"""

    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__("profile text integrity validation failed")


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
        finding_ids = [f.finding_id for f in findings]
        evidences = self.repo.list_evidences_for_findings(finding_ids)
        evidences.sort(key=lambda ev: (ev.created_at or "", ev.evidence_id))
        quotes = self._run_scoped_quotes(findings, evidences=evidences)

        sub_dim_summaries = _aggregate_sub_dim_stats(findings, quotes)
        book_stats = book.stats_json or {}
        metrics_baseline = {
            **(book_stats.get("metrics", {}) or {}),
            **(book_stats.get("prose_shape_metrics", {}) or {}),
        }
        paragraphs = self.repo.list_paragraphs(book_id)
        paragraph_types = {
            p.paragraph_id: p.paragraph_type
            for p in paragraphs
        }
        scene_samples_index = _build_scene_samples_index(quotes, paragraph_types)
        finding_summaries = _build_finding_summaries_payload(findings, evidences)

        raw_payload = {
            "book_title": book.title,
            "sub_dimensions": sub_dim_summaries,
            "metrics_baseline": _prune_metrics_for_prompt(metrics_baseline),
            "finding_summaries": finding_summaries,
        }
        template = load_prompt_templates()[SYNTHESIZE_NODE_ID]
        payload, input_budget_audit = _fit_synthesis_payload_to_budget(
            raw_payload,
            template,
        )

        corpus_texts = [str(p.text or "") for p in paragraphs if str(p.text or "")]
        (
            synthesized,
            safe_profile,
            overlap_audit,
            synthesis_attempt_audit,
        ) = self._synthesize_validated_profile(
            payload,
            template=template,
            corpus_texts=corpus_texts,
            book_id=book_id,
            run_id=run_id,
        )
        safe_forbidden_findings = [
            {
                "finding_id": str(f.finding_id),
                "sub_dimension": str(f.sub_dimension or ""),
                "statement": str(f.statement or "").strip(),
                "status": str(f.status or ""),
            }
            for f in findings
            if f.finding_kind == "forbidden_pattern"
            and str(f.statement or "").strip()
            and not _contains_source_overlap(str(f.statement), corpus_texts)
        ]
        overlap_audit["dropped_forbidden_finding_count"] = sum(
            1 for f in findings if f.finding_kind == "forbidden_pattern"
        ) - len(safe_forbidden_findings)

        metric_summary = _deterministic_metric_summary(metrics_baseline)
        profile_json: dict[str, Any] = {
            # 生产画像始终由当前用户导入的参考语料派生；作者名不是路由键，
            # 也不存在任何固定作者 allow-list。内置作者样本仅属于隔离基准。
            "reference_basis": {
                "version": REFERENCE_BASIS_VERSION,
                "mode": "reference_derived",
                "scope": "work_or_collection",
                "fixed_author_allowlist": False,
                "book_id": str(book.book_id),
                "source_kind": str(book.source_kind),
                "text_checksum": str(book.text_checksum),
                "source_char_count": int(book.total_chars or 0),
                "paragraph_count": len(paragraphs),
            },
            # 稳定、可复算的量化摘要留作内部审计/RAG；LLM 的安全定性概述
            # 单独保存给生成提示，并会在注入侧剔除频率/配额断言，避免同一
            # 语料两次合成出的漂移标签覆盖软分布真源。
            "narrative_summary": metric_summary
            or safe_profile["narrative_summary"],
            "qualitative_summary": safe_profile["narrative_summary"],
            "metrics_baseline": metrics_baseline,
            "scene_samples_index": scene_samples_index,
            "sub_dimensions": sub_dim_summaries,
            "style_features": safe_profile["style_features"],
            "narrative_patterns": safe_profile["narrative_patterns"],
            "banned_replication_rules": safe_profile["banned_replication_rules"],
            "calibration_guidance": safe_profile["calibration_guidance"],
            "generation_safe_forbidden_findings": safe_forbidden_findings,
            "source_overlap_filter": overlap_audit,
            "synthesis_input_budget": input_budget_audit,
            "synthesis_attempts": synthesis_attempt_audit,
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

    def _run_scoped_quotes(
        self,
        findings: list["StyleReferenceFinding"],
        *,
        evidences: list["StyleReferenceEvidence"] | None = None,
    ) -> list["StyleReferenceQuote"]:
        """本 run findings 经 evidence 关联的 quotes(排序确定:created_at, quote_id)。"""
        finding_ids = [f.finding_id for f in findings]
        if evidences is None:
            evidences = self.repo.list_evidences_for_findings(finding_ids)
            evidences.sort(key=lambda ev: (ev.created_at or "", ev.evidence_id))
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
        attempt_no: int = 1,
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
                    step=(
                        f"synthesize:{run_id}"
                        if attempt_no == 1
                        else f"synthesize:{run_id}:validation_retry"
                    ),
                ),
            )
        except LLMNodeError as exc:
            raise SynthesizeError(str(exc)) from exc

    def _synthesize_validated_profile(
        self,
        payload: dict[str, Any],
        *,
        template: PromptTemplate,
        corpus_texts: list[str],
        book_id: str,
        run_id: str,
    ) -> tuple[SynthesizedProfile, dict[str, Any], dict[str, Any], dict[str, Any]]:
        """校验聚合结果；只对结构/安全内容失败做一次有界业务重试。"""

        attempt_payload = payload
        first_failure: dict[str, Any] | None = None
        retry_budget_audit: dict[str, Any] | None = None
        for attempt_no in (1, 2):
            structured = self._call_llm(
                SYNTHESIZE_NODE_ID,
                attempt_payload,
                book_id=book_id,
                run_id=run_id,
                attempt_no=attempt_no,
            )
            try:
                synthesized = SynthesizedProfile.model_validate(structured)
                safe_profile, overlap_audit = _sanitize_synthesized_profile(
                    synthesized,
                    corpus_texts,
                )
            except ValidationError as exc:
                failure = _profile_validation_failure(exc)
                failure_message = f"LLM response failed Pydantic validation: {exc}"
            except ProfileTextIntegrityError as exc:
                failure = {
                    "reason_code": "profile_text_integrity_invalid",
                    "violations": exc.violations[:12],
                }
                failure_message = str(exc)
            except SynthesizeError as exc:
                failure = {
                    "reason_code": "source_overlap_removed_required_content",
                    "violations": ["style_features_or_narrative_patterns_not_generation_safe"],
                }
                failure_message = str(exc)
            else:
                return (
                    synthesized,
                    safe_profile,
                    overlap_audit,
                    {
                        "attempt_count": attempt_no,
                        "retried": attempt_no > 1,
                        "first_failure": first_failure,
                        "retry_input_budget": retry_budget_audit,
                    },
                )

            if attempt_no == 2:
                raise SynthesizeError(failure_message)

            first_failure = failure
            logger.warning(
                "profile synthesis validation failed; retrying once: %s",
                failure["reason_code"],
            )
            retry_payload = {
                **payload,
                "validation_retry": {
                    **failure,
                    "attempt": 2,
                    "required_action": (
                        "重新聚合；profile_title、narrative_summary、style_features、"
                        "narrative_patterns 必须非空，输出必须是有效 Unicode，"
                        "且只写不复用原文字词的抽象机制"
                    ),
                },
            }
            attempt_payload, retry_budget_audit = _fit_synthesis_payload_to_budget(
                retry_payload,
                template,
            )

        raise AssertionError("unreachable")


def _profile_validation_failure(exc: ValidationError) -> dict[str, Any]:
    violations = [
        f"{'.'.join(str(part) for part in error.get('loc', ())) or 'profile'}:"
        f"{error.get('type', 'invalid')}"
        for error in exc.errors(include_url=False, include_input=False)
    ]
    return {
        "reason_code": "invalid_or_empty_profile",
        "violations": violations[:12],
    }


def _estimate_synthesis_input_tokens(
    template: PromptTemplate,
    payload: dict[str, Any],
) -> int:
    system_prompt = render_untrusted_system_prompt(template.system_prompt)
    user_prompt = render_untrusted_user_prompt(
        template.task_prompt,
        UntrustedPayload(payload),
        kind=SYNTHESIZE_NODE_ID,
    )
    schema_text = json.dumps(
        template.structured_schema,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    deterministic_estimate = (
        estimate_tokens(system_prompt)
        + estimate_tokens(user_prompt)
        + estimate_tokens(schema_text)
    )
    return (
        math.ceil(deterministic_estimate * _SYNTHESIS_TOKENIZER_SAFETY_MULTIPLIER)
        + _SYNTHESIS_SCHEMA_SAFETY_TOKENS
    )


def _fit_synthesis_payload_to_budget(
    payload: dict[str, Any],
    template: PromptTemplate,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """按子维覆盖优先级把画像聚合输入真正压进模板预算。"""

    target = int(template.input_token_budget)
    before = _estimate_synthesis_input_tokens(template, payload)
    raw_rows = payload.get("finding_summaries") or []
    rows = [dict(row) for row in raw_rows if isinstance(row, dict)]
    ordered_rows, required_indices = _coverage_first_finding_summaries(rows)

    fitted = {
        key: value
        for key, value in payload.items()
        if key not in {"finding_summaries", "metrics_baseline"}
    }
    metrics = dict(payload.get("metrics_baseline") or {})
    fitted["metrics_baseline"] = metrics
    fitted["finding_summaries"] = []

    metric_drop_order = _synthesis_metric_drop_order(metrics)
    while _estimate_synthesis_input_tokens(template, fitted) > target and metric_drop_order:
        metrics.pop(metric_drop_order.pop(0), None)
    if _estimate_synthesis_input_tokens(template, fitted) > target:
        raise SynthesizeError(
            "style profile synthesis template and fixed payload exceed input_token_budget"
        )

    selected: list[dict[str, Any]] = []
    skipped_required: list[str] = []
    for source_index, row in ordered_rows:
        is_required = source_index in required_indices
        statement_limits = (
            (_SYNTHESIS_STATEMENT_MAX_CHARS, 80, 56, 36)
            if is_required
            else (_SYNTHESIS_STATEMENT_MAX_CHARS,)
        )
        candidate = _compact_finding_summary(
            row,
            statement_limit=statement_limits[0],
        )
        trial = {**fitted, "finding_summaries": [*selected, candidate]}
        for statement_limit in statement_limits:
            candidate = _compact_finding_summary(
                row,
                statement_limit=statement_limit,
            )
            trial = {**fitted, "finding_summaries": [*selected, candidate]}
            while (
                _estimate_synthesis_input_tokens(template, trial) > target
                and is_required
                and metric_drop_order
            ):
                metrics.pop(metric_drop_order.pop(0), None)
                trial["metrics_baseline"] = metrics
            if _estimate_synthesis_input_tokens(template, trial) <= target:
                break
        if _estimate_synthesis_input_tokens(template, trial) <= target:
            selected.append(candidate)
        elif is_required:
            skipped_required.append(str(row.get("sub_dimension") or "unknown"))

    if skipped_required:
        raise SynthesizeError(
            "style profile synthesis budget cannot preserve one finding for dimensions: "
            + ", ".join(sorted(set(skipped_required)))
        )

    fitted["finding_summaries"] = selected
    after = _estimate_synthesis_input_tokens(template, fitted)
    if after > target:
        raise SynthesizeError(
            f"style profile synthesis input budget fit failed: {after}>{target}"
        )

    selected_by_dimension = Counter(
        str(row.get("sub_dimension") or "unknown") for row in selected
    )
    audit = {
        "applied": before > after,
        "target_input_tokens": target,
        "estimated_before": before,
        "estimated_after": after,
        "schema_safety_tokens": _SYNTHESIS_SCHEMA_SAFETY_TOKENS,
        "tokenizer_safety_multiplier": _SYNTHESIS_TOKENIZER_SAFETY_MULTIPLIER,
        "finding_count_before": len(rows),
        "finding_count_after": len(selected),
        "metric_count_before": len(payload.get("metrics_baseline") or {}),
        "metric_count_after": len(metrics),
        "covered_sub_dimensions": sorted(selected_by_dimension),
        "selected_by_dimension": dict(sorted(selected_by_dimension.items())),
    }
    return fitted, audit


def _coverage_first_finding_summaries(
    rows: list[dict[str, Any]],
) -> tuple[list[tuple[int, dict[str, Any]]], set[int]]:
    indexed = list(enumerate(rows))
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for item in indexed:
        grouped[str(item[1].get("sub_dimension") or "unknown")].append(item)

    def rank(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int, str, int]:
        index, row = item
        return (
            -_STATUS_RANK.get(str(row.get("status") or "pending"), 0),
            -_CONFIDENCE_RANK.get(str(row.get("confidence") or "medium"), 1),
            -int(row.get("evidence_count") or 0),
            str(row.get("statement") or ""),
            index,
        )

    ordered: list[tuple[int, dict[str, Any]]] = []
    used: set[int] = set()
    required: set[int] = set()
    for sub_dimension in sorted(grouped):
        candidates = sorted(grouped[sub_dimension], key=rank)
        observations = [
            item
            for item in candidates
            if str(item[1].get("finding_kind")) == "observation"
        ]
        chosen = observations[0] if observations else candidates[0]
        ordered.append(chosen)
        used.add(chosen[0])
        required.add(chosen[0])

    for sub_dimension in sorted(grouped):
        candidates = sorted(grouped[sub_dimension], key=rank)
        forbidden = [
            item
            for item in candidates
            if item[0] not in used
            and str(item[1].get("finding_kind")) == "forbidden_pattern"
        ]
        if forbidden:
            ordered.append(forbidden[0])
            used.add(forbidden[0][0])

    remaining_by_dimension: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for sub_dimension in sorted(grouped):
        remaining_by_dimension[sub_dimension] = sorted(
            (item for item in grouped[sub_dimension] if item[0] not in used),
            key=lambda item: (str(item[1].get("finding_kind") or ""), *rank(item)),
        )
    while any(remaining_by_dimension.values()):
        for sub_dimension in sorted(remaining_by_dimension):
            candidates = remaining_by_dimension[sub_dimension]
            if candidates:
                ordered.append(candidates.pop(0))
    return ordered, required


def _compact_finding_summary(
    row: dict[str, Any],
    *,
    statement_limit: int,
) -> dict[str, Any]:
    try:
        evidence_count = max(0, int(row.get("evidence_count") or 0))
    except (TypeError, ValueError):
        evidence_count = 0
    return {
        "sub_dimension": str(row.get("sub_dimension") or "unknown"),
        "finding_kind": str(row.get("finding_kind") or "observation"),
        "statement": str(row.get("statement") or "").strip()[:statement_limit],
        # 这些字段参与 coverage-first 排序，也必须真正送到合成模型。
        # 旧实现排序后把它们丢掉，模型无法区分“2 条 pending 证据”和
        # “多条 approved/high 证据”，容易把偶发样例夸成高频规律。
        "confidence": str(row.get("confidence") or "medium"),
        "status": str(row.get("status") or "pending"),
        "evidence_count": evidence_count,
    }


def _synthesis_metric_drop_order(metrics: dict[str, Any]) -> list[str]:
    priority = [name for name in _SYNTHESIS_METRIC_PRIORITY if name in metrics]
    nonpriority = sorted(name for name in metrics if name not in priority)
    return [*nonpriority, *reversed(priority)]


def _contains_source_overlap(text: str, corpus_texts: list[str]) -> bool:
    if not text.strip() or not corpus_texts:
        return False
    return not check_plagiarism(
        text,
        corpus_texts,
        ngram_size=6,
        threshold_chars=_PROFILE_SOURCE_OVERLAP_THRESHOLD,
    ).passed


def _sanitize_synthesized_profile(
    synthesized: SynthesizedProfile,
    corpus_texts: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """阻止聚合模型把参考原句伪装成抽象风格指令带入生成提示。"""

    integrity_violations = _profile_text_integrity_violations(synthesized)
    if integrity_violations:
        raise ProfileTextIntegrityError(integrity_violations)

    dropped_counts: dict[str, int] = {}

    def safe_items(field: str, items: list[str]) -> list[str]:
        safe = [
            str(item).strip()
            for item in items
            if str(item).strip()
            and not _contains_source_overlap(str(item), corpus_texts)
        ]
        dropped_counts[field] = len(items) - len(safe)
        return safe

    style_features = safe_items("style_features", synthesized.style_features)
    narrative_patterns = safe_items(
        "narrative_patterns", synthesized.narrative_patterns
    )
    banned_rules = safe_items(
        "banned_replication_rules", synthesized.banned_replication_rules
    )
    calibration = safe_items(
        "calibration_guidance", synthesized.calibration_guidance
    )
    if not style_features or not narrative_patterns:
        raise SynthesizeError(
            "profile source-overlap filter removed every required style feature or narrative pattern"
        )

    summary = synthesized.narrative_summary.strip()
    summary_replaced = _contains_source_overlap(summary, corpus_texts)
    if summary_replaced:
        summary = "；".join([*style_features[:2], *narrative_patterns[:2]])[:200]

    return (
        {
            "narrative_summary": summary,
            "style_features": style_features,
            "narrative_patterns": narrative_patterns,
            "banned_replication_rules": banned_rules,
            "calibration_guidance": calibration,
        },
        {
            "applied": True,
            "threshold_chars": _PROFILE_SOURCE_OVERLAP_THRESHOLD,
            "summary_replaced": summary_replaced,
            "dropped_counts": dropped_counts,
        },
    )


def _deterministic_metric_summary(metrics_baseline: dict[str, Any]) -> str:
    """把冻结基线渲染成稳定概述；不使用作者名、主题词或 LLM 判断。"""

    def mean(name: str) -> float | None:
        stats = metrics_baseline.get(name)
        if not isinstance(stats, dict):
            return None
        try:
            value = float(stats.get("mean"))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    parts: list[str] = []
    sentence = mean("avg_sentence_length")
    short = mean("short_sentence_ratio")
    long = mean("long_sentence_ratio")
    if sentence is not None:
        sentence_part = f"句均约{sentence:.1f}字"
        if short is not None:
            sentence_part += f"、短句约{short * 100:.0f}%"
        if long is not None:
            sentence_part += f"、长句约{long * 100:.0f}%"
        parts.append(sentence_part)

    paragraph_mean = mean("paragraph_mean_chars")
    paragraph_rate = mean("paragraphs_per_1k")
    if paragraph_mean is not None or paragraph_rate is not None:
        paragraph_parts: list[str] = []
        if paragraph_mean is not None:
            paragraph_parts.append(f"段均约{paragraph_mean:.1f}字")
        if paragraph_rate is not None:
            paragraph_parts.append(f"每千字约{paragraph_rate:.1f}段")
        parts.append("、".join(paragraph_parts))

    punctuation = mean("punctuation_density_per_1k")
    semicolon = mean("semicolon_density_per_1k")
    ellipsis = mean("ellipsis_density_per_1k")
    if punctuation is not None or semicolon is not None or ellipsis is not None:
        punctuation_parts: list[str] = []
        if punctuation is not None:
            punctuation_parts.append(f"每千字标点约{punctuation:.1f}")
        if semicolon is not None:
            punctuation_parts.append(f"分号约{semicolon:.1f}")
        if ellipsis is not None:
            punctuation_parts.append(f"省略号约{ellipsis:.1f}")
        parts.append("、".join(punctuation_parts))

    if not parts:
        return ""
    return "量化基线（与定性描述冲突时以此为准）：" + "；".join(parts) + "。"


_PROFILE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _profile_text_integrity_violations(
    synthesized: SynthesizedProfile,
) -> list[str]:
    """只返回字段/标记，不把可能含参考内容的画像正文写入审计。"""

    violations: list[str] = []
    fields: dict[str, list[str]] = {
        "profile_title": [synthesized.profile_title],
        "narrative_summary": [synthesized.narrative_summary],
        "style_features": list(synthesized.style_features),
        "narrative_patterns": list(synthesized.narrative_patterns),
        "banned_replication_rules": list(synthesized.banned_replication_rules),
        "calibration_guidance": list(synthesized.calibration_guidance),
    }
    for field, values in fields.items():
        for value in values:
            markers: list[str] = []
            if "\ufffd" in str(value):
                markers.append("replacement_character")
            if _PROFILE_CONTROL_RE.search(str(value)):
                markers.append("control_character")
            for marker in markers:
                violation = f"{field}:{marker}"
                if violation not in violations:
                    violations.append(violation)
    return violations


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


def _build_finding_summaries_payload(
    findings: list["StyleReferenceFinding"],
    evidences: list["StyleReferenceEvidence"],
) -> list[dict[str, Any]]:
    """画像聚合只消费已验证的抽象 finding，不重复发送参考原文。"""

    evidence_counts = Counter(evidence.finding_id for evidence in evidences)
    return [
        {
            "sub_dimension": str(finding.sub_dimension or ""),
            "finding_kind": str(finding.finding_kind or "observation"),
            "statement": str(finding.statement or "").strip()[
                :_SYNTHESIS_STATEMENT_MAX_CHARS
            ],
            "confidence": str(finding.confidence or "medium"),
            "status": str(finding.status or "pending"),
            "evidence_count": int(evidence_counts.get(finding.finding_id, 0)),
        }
        for finding in findings
        if str(finding.statement or "").strip()
    ]


def _build_sample_quotes_payload(
    findings: list["StyleReferenceFinding"],
    quotes: list["StyleReferenceQuote"],
    evidences: list["StyleReferenceEvidence"],
) -> list[dict[str, str]]:
    """每条 finding 配自己的 evidence quote，而不是同维度的任意 quote。

    evidence 优先真实 paragraph_quote，再取其它真实证据，最后才取合成证据。
    同一 quote 可以合法支撑多个 finding，不因全局去重而改配无关引文。控制
    prompt token 在合理范围(每 finding < 400 字)。
    """
    quote_by_id = {q.quote_id: q for q in quotes}
    evidence_by_finding: dict[str, list["StyleReferenceEvidence"]] = defaultdict(list)
    for evidence in evidences:
        evidence_by_finding[evidence.finding_id].append(evidence)
    for rows in evidence_by_finding.values():
        rows.sort(
            key=lambda ev: (
                bool(ev.is_synthetic),
                ev.anchor_kind != "paragraph_quote",
                ev.created_at or "",
                ev.evidence_id,
            )
        )

    payload: list[dict[str, str]] = []
    for f in findings:
        repr_quote: str = ""
        for evidence in evidence_by_finding.get(f.finding_id, []):
            q = quote_by_id.get(evidence.quote_id)
            if q is not None and (q.quote_text or "").strip():
                repr_quote = (q.quote_text or "")[:200]
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
