from __future__ import annotations

import hashlib
import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import ReviewItem
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import normalize
from novel_system.services.human_review_support import structured_target
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.style_profile import StyleProfileExtractionService, StyleProfileService

router = APIRouter(tags=["style_profile"])


class StyleProfileExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_texts: list[str] = Field(default_factory=list)
    style_rules: list[str] = Field(default_factory=list)
    style_observations: list[str] = Field(default_factory=list)
    calibration_lines: list[str] = Field(default_factory=list)
    banned_moves: list[str] = Field(default_factory=list)


class StyleProfileReviewCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: dict[str, Any] | None = None
    profile_yaml: str | None = None
    scope: str = "global"
    scope_ref_id: str = "global"
    lineage_key: str | None = None
    active_on_approve: int = Field(default=0, ge=0, le=1)


@router.get("/api/v1/style-profile/contract")
def style_profile_contract(request: Request):
    return ok(
        StyleProfileService.contract_payload(),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/style-profile/review-candidate")
def create_style_profile_review_candidate(
    payload: StyleProfileReviewCandidateRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/style-profile/review-candidate",
        payload=payload.model_dump(mode="json", exclude_none=True),
        action=lambda: _upsert_style_profile_review_candidate(session, payload),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


def _upsert_style_profile_review_candidate(
    session: Session,
    payload: StyleProfileReviewCandidateRequest,
) -> dict[str, Any]:
    profile_yaml, profile = _candidate_yaml_and_profile(payload)
    scope = _required_text(payload.scope, field="scope")
    scope_ref_id = _required_text(payload.scope_ref_id, field="scope_ref_id")
    lineage_key = _required_text(
        payload.lineage_key or f"style_profile_{_safe_fragment(scope)}_{_safe_fragment(scope_ref_id)}",
        field="lineage_key",
    )
    digest = hashlib.sha256(profile_yaml.encode("utf-8")).hexdigest()[:12]
    review_id = f"review_style_profile_{_safe_fragment(scope)}_{_safe_fragment(scope_ref_id)}_{digest}"
    contract_version = profile.get("contract_version") if isinstance(profile, dict) else None

    candidate_payload = {
        "scope": scope,
        "scope_ref_id": scope_ref_id,
        "lineage_key": lineage_key,
        "content": profile_yaml,
        "source": "style_profile_extract",
        "contract_version": contract_version,
    }
    if isinstance(profile, dict):
        candidate_payload["style_profile"] = profile

    item = session.get(ReviewItem, review_id)
    if item is None:
        item = ReviewItem(
            review_id=review_id,
            item_type="style_rule_set",
            status="pending",
            candidate_text=profile_yaml,
            candidate_payload_json=candidate_payload,
            active_on_approve=payload.active_on_approve,
        )
        session.add(item)
    else:
        item.item_type = "style_rule_set"
        item.status = "pending"
        item.candidate_text = profile_yaml
        item.candidate_payload_json = candidate_payload
        item.active_on_approve = payload.active_on_approve
    session.flush()
    session.refresh(item)

    return {
        "review": _serialize_style_profile_review(item),
        "target": structured_target("review_item", item.review_id),
    }


def _candidate_yaml_and_profile(payload: StyleProfileReviewCandidateRequest) -> tuple[str, dict[str, Any]]:
    profile = payload.profile
    if profile is not None:
        profile_yaml = StyleProfileService.render_profile_yaml(profile)
        return _normalize_profile_yaml(profile_yaml), dict(profile)
    if isinstance(payload.profile_yaml, str) and payload.profile_yaml.strip():
        profile_yaml = _normalize_profile_yaml(payload.profile_yaml)
        parsed_profile = StyleProfileService.parse_profile_yaml(profile_yaml)
        return profile_yaml, dict(parsed_profile or {})
    raise DomainError("STYLE_PROFILE_CANDIDATE_REQUIRED", "missing style profile YAML", status_code=400)


def _normalize_profile_yaml(value: str) -> str:
    normalized = normalize(value)
    if not isinstance(normalized, str) or not normalized.strip():
        raise DomainError("STYLE_PROFILE_CANDIDATE_REQUIRED", "missing style profile YAML", status_code=400)
    return normalized


def _required_text(value: str | None, *, field: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise DomainError("STYLE_PROFILE_CANDIDATE_INVALID", f"missing {field}", status_code=400)


def _safe_fragment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "global"


def _serialize_style_profile_review(item: ReviewItem) -> dict[str, Any]:
    return {
        "review_id": item.review_id,
        "scene_id": item.scene_id,
        "chapter_id": item.chapter_id,
        "item_type": item.item_type,
        "target_collection": item.target_collection,
        "status": item.status,
        "candidate_text": item.candidate_text,
        "candidate_payload_json": item.candidate_payload_json,
        "active_on_approve": item.active_on_approve,
        "materialize_status": item.materialize_status,
        "approved_item_row_id": item.approved_item_row_id,
    }


@router.post("/api/v1/style-profile/extract")
def extract_style_profile(
    payload: StyleProfileExtractRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    return ok(
        StyleProfileExtractionService(session).extract(payload.model_dump()),
        req_id=getattr(request.state, "request_id", None),
    )
