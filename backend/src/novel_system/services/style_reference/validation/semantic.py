"""Semantic validation:critic LLM 评分 + 强制 quote 引用(PR-7 §7)。

`check_semantic(generated_text, profile, llm_client)`:
- 调 `style_ref_validate_semantic`,传 generated_text / style_features /
  narrative_summary
- LLM 返 `{dimension_scores: [{dimension, score, explanation}]}`
- 强制 explanation 含「...」(中文弯引号);否则 score 截至 ≤4
- LLM 失败 raise LLMNodeError(caller 决定降级:semantic_json=[])
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from novel_system.services.llm_accounting import LLMCallContext
from novel_system.services.style_reference._llm_helper import LLMNodeError, call_llm_node
from novel_system.services.style_reference.profile_fields import generation_safe_summary
from novel_system.services.style_reference.schemas import SemanticReportItem
from novel_system.services.style_reference.untrusted_data import UntrustedPayload

if TYPE_CHECKING:
    from novel_system.db.models import StyleReferenceProfile


SEMANTIC_NODE_ID = "style_ref_validate_semantic"
SCORE_CAP_NO_QUOTE = 4.0
QUOTE_PATTERN = re.compile(r"「[^」]+」")


def check_semantic(
    generated_text: str,
    profile: "StyleReferenceProfile",
    session: Session,
    llm_client: Any,
    *,
    report_id: str,
) -> list[SemanticReportItem]:
    """对 generated_text 调 critic LLM,返 list[SemanticReportItem]。

    LLM 失败时 raise LLMNodeError(caller 在 runner.py 中 try/except 降级)。
    """
    if not generated_text or llm_client is None:
        return []

    profile_json = profile.profile_json or {}
    style_features = list(profile_json.get("style_features") or [])[:5]
    narrative_summary = generation_safe_summary(profile_json)

    payload = {
        "generated_text": generated_text[:3000],
        "style_features": style_features,
        "narrative_summary": narrative_summary,
    }
    raw = call_llm_node(
        SEMANTIC_NODE_ID,
        UntrustedPayload(payload),
        llm_client,
        session=session,
        context=LLMCallContext(
            scope_type="style_reference_validation",
            scope_id=report_id,
            node_id=SEMANTIC_NODE_ID,
            step=f"semantic:{profile.profile_id}",
        ),
    )
    dimension_scores = raw.get("dimension_scores") or []

    reports: list[SemanticReportItem] = []
    for item in dimension_scores:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        if not dimension:
            continue
        try:
            score = float(item.get("score", 0))
        except (TypeError, ValueError):
            continue
        explanation = str(item.get("explanation") or "")
        quotes_found = bool(QUOTE_PATTERN.search(explanation))
        if not quotes_found:
            score = min(score, SCORE_CAP_NO_QUOTE)
        # clip to [0, 10]
        score = max(0.0, min(10.0, score))
        reports.append(
            SemanticReportItem(
                dimension=dimension,
                score=score,
                explanation=explanation,
                quotes_found=quotes_found,
            )
        )
    return reports
