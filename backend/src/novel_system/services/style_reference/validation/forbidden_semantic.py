"""Forbidden pattern semantic 检查(PR-7 §7.4)。

`check_forbidden_semantic(generated_text, profile, session, llm_client)`:
- 从 profile.source_finding_ids_json 拉 finding_kind=forbidden_pattern 的 finding
- 对每条 forbidden_pattern 调一次 `style_ref_validate_forbidden` LLM
- LLM 返 `{triggered: bool, excerpt, reasoning}`
- 单条 LLM 失败不阻塞其他;triggered=True 的进 ForbiddenHit
- 与 PR-4 `forbidden_local`(字面词扫描)互补:sync_only 只跑 local,
  async_full 同时跑 local + semantic
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from novel_system.services.style_reference._llm_helper import LLMNodeError, call_llm_node
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import ForbiddenHit

if TYPE_CHECKING:
    from novel_system.db.models import StyleReferenceProfile

logger = logging.getLogger(__name__)

FORBIDDEN_SEMANTIC_NODE_ID = "style_ref_validate_forbidden"


def check_forbidden_semantic(
    generated_text: str,
    profile: "StyleReferenceProfile",
    session: Session,
    llm_client: Any,
) -> list[ForbiddenHit]:
    """对 profile 关联的 forbidden_pattern findings 逐条调 LLM 检查触发。"""
    if not generated_text or llm_client is None:
        return []

    finding_ids = list(profile.source_finding_ids_json or [])
    if not finding_ids:
        return []

    repo = StyleReferenceRepository(session)
    forbidden_findings = []
    for fid in finding_ids:
        finding = repo.get_finding(fid)
        if finding is None:
            continue
        if finding.finding_kind == "forbidden_pattern":
            forbidden_findings.append(finding)

    hits: list[ForbiddenHit] = []
    for f in forbidden_findings:
        payload = {
            "generated_text": generated_text[:2000],
            "forbidden_statement": f.statement,
            "sub_dimension": f.sub_dimension,
        }
        try:
            raw = call_llm_node(FORBIDDEN_SEMANTIC_NODE_ID, payload, llm_client)
        except LLMNodeError as exc:
            logger.warning(
                "forbidden_semantic check for %s skipped: %s", f.finding_id, exc
            )
            continue
        if not raw.get("triggered"):
            continue
        excerpt = str(raw.get("excerpt") or "")[:200]
        hits.append(
            ForbiddenHit(
                pattern_statement=f.statement,
                matched_excerpt=excerpt,
                severity="error",
            )
        )
    return hits
