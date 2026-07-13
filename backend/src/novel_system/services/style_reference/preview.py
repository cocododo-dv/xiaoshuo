"""PreviewService — apply 前的预览面板(PR-4)。

参见《风格参考模块重构执行手册 v1.1》§5 / §8 与 plans/style-reference-v1-1-fancy-shannon.md
§"Preview 流程"。

流程:
  1. 从 profile.profile_json.scene_samples_index 选 3 种 paragraph_type
     (dialogue / description_env / psychology)
  2. 各调 `style_ref_preview_generate` LLM 生成 1 段 ≤500 字示例
  3. 跑 `validation.run_sync_validate`(plagiarism + 字面 banned_terms 双层)
  4. 落 `style_reference_validation_reports` 行
  5. 返回 list[PreviewSampleResult]

LLM 调用失败时,该 sample 标 `error="llm_call_failed"`,verdict 留空,
不阻塞其他 sample。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from novel_system.services.llm_client import LLMRequest, load_model_routing_config
from novel_system.services.prompt_builder import load_prompt_templates
from novel_system.services.style_reference._llm_helper import LLMNodeError, call_llm_node
from novel_system.services.style_reference.errors import (
    LLMRequiredError,
    StyleReferenceError,
)
from novel_system.services.style_reference.policy import ensure_cloud_llm_allowed
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import (
    PreviewGeneratedSample,
    PreviewSampleResult,
    ValidationMode,
    ValidationTargetKind,
)
from novel_system.services.style_reference.validation import run_sync_validate
from novel_system.services.style_reference.untrusted_data import UntrustedPayload

logger = logging.getLogger(__name__)

PREVIEW_NODE_ID = "style_ref_preview_generate"

DEFAULT_TARGET_TYPES: tuple[str, ...] = ("dialogue", "description_env", "psychology")


class PreviewError(StyleReferenceError):
    """PreviewService 内部错误。"""


class PreviewService:
    """3 段示例生成 + sync_only validate + 落 validation_reports。"""

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

    def generate(
        self,
        profile_id: str,
        *,
        target_types: tuple[str, ...] | None = None,
    ) -> list[PreviewSampleResult]:
        if not self._llm_enabled or self._llm_client is None:
            raise LLMRequiredError(operation="generate_preview")

        profile = self.repo.get_profile(profile_id)
        if profile is None:
            raise PreviewError(f"profile {profile_id!r} not found")
        # 附录 B — local_only 的书禁止把种子引文送往云端 LLM
        ensure_cloud_llm_allowed(
            self.repo.get_book(profile.book_id), operation="generate_preview"
        )

        profile_json = profile.profile_json or {}
        samples_index: dict[str, list[str]] = profile_json.get("scene_samples_index") or {}
        narrative_summary = profile_json.get("narrative_summary", "")
        style_features = (profile_json.get("style_features") or [])[:5]

        target_types = target_types or DEFAULT_TARGET_TYPES
        profile_quotes = [q.quote_text for q in self.repo.list_quotes(profile.book_id)]

        results: list[PreviewSampleResult] = []
        for ptype in target_types:
            candidate_ids = samples_index.get(ptype, [])
            seed_quote_text = ""
            if candidate_ids:
                seed = self.repo.get_quote(candidate_ids[0])
                if seed is not None:
                    seed_quote_text = (seed.quote_text or "")[:200]

            try:
                generated = self._call_llm(
                    {
                        "profile_summary": narrative_summary,
                        "paragraph_type": ptype,
                        "seed_quote": seed_quote_text,
                        "style_features": style_features,
                    }
                )
                sample = PreviewGeneratedSample.model_validate(generated)
            except (ValidationError, PreviewError) as exc:
                logger.warning("preview LLM failed for %s: %s", ptype, exc)
                results.append(
                    PreviewSampleResult(
                        paragraph_type=ptype,
                        sample_text="",
                        report_id=None,
                        verdict=None,
                        error="llm_call_failed",
                    )
                )
                continue

            sample_text = sample.sample_text
            report = run_sync_validate(
                sample_text, profile, self.session, profile_quotes=profile_quotes
            )
            report_row = self.repo.create_validation_report(
                report_id=f"sr_rep_{uuid.uuid4().hex[:12]}",
                profile_id=profile_id,
                target_kind=ValidationTargetKind.MANUAL.value,
                target_ref_id=None,
                verdict=report.verdict.value,
                quantitative_json=report.quantitative_json,
                semantic_json=[],
                plagiarism_json=report.plagiarism_json,
                forbidden_hits_json=report.forbidden_hits_json,
                mode_executed=ValidationMode.SYNC_ONLY.value,
            )
            results.append(
                PreviewSampleResult(
                    paragraph_type=ptype,
                    sample_text=sample_text,
                    report_id=report_row.report_id,
                    verdict=report.verdict.value,
                )
            )

        return results

    # ------------------------------------------------------------------ LLM

    def _call_llm(self, payload: dict) -> dict[str, Any]:
        # PR-8 §"_call_llm 统一" — 复用 _llm_helper.call_llm_node
        try:
            return call_llm_node(
                PREVIEW_NODE_ID,
                UntrustedPayload(payload),
                self._llm_client,
            )
        except LLMNodeError as exc:
            raise PreviewError(str(exc)) from exc
