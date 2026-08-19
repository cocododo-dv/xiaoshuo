"""Auditable human feedback for style-candidate calibration.

Candidate selection is intentionally blinded, so machine scores must stay out of
the author-facing picker.  This module stores a compact score snapshot inside the
review gate and joins it with an *explicit* author reason after selection.  The
result is observational calibration evidence only: it can diagnose the scorer,
but it can never activate production reranking by itself.
"""

from __future__ import annotations

import copy
import hashlib
import math
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import select

from novel_system.db.models import HumanReviewEvent
from novel_system.services.hash_engine import canonical_json


STYLE_FEEDBACK_VERSION = "style_candidate_feedback_v1"
STYLE_FEEDBACK_SNAPSHOT_VERSION = "style_candidate_feedback_snapshot_v1"

ALLOWED_PREFERENCE_TAGS = frozenset(
    {
        "style_match",
        "rhythm",
        "voice",
        "imagery",
        "dialogue",
        "overall_quality",
        "plot_fidelity",
    }
)
STYLE_ATTRIBUTION_TAGS = frozenset(
    {"style_match", "rhythm", "voice", "imagery", "dialogue"}
)


def _payload_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(payload)).encode("utf-8")).hexdigest()


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bounded_string(value: Any, *, max_length: int = 200) -> str | None:
    text = str(value or "").strip()
    return text[:max_length] if text else None


def normalize_preference_tags(values: Iterable[Any] | None) -> list[str]:
    tags = [str(value or "").strip() for value in (values or [])]
    return list(dict.fromkeys(tag for tag in tags if tag in ALLOWED_PREFERENCE_TAGS))


def build_candidate_style_snapshot(candidates: Sequence[Any]) -> dict[str, Any]:
    """Freeze score-only diagnostics for a blinded candidate gate.

    No candidate prose, source excerpt, prompt, or matched n-gram is retained.
    """

    rows: list[dict[str, Any]] = []
    common_rerank: Mapping[str, Any] = {}
    for candidate in candidates:
        raw = getattr(candidate, "ranking_audit", None)
        audit = raw if isinstance(raw, Mapping) else {}
        rerank = audit.get("rerank")
        if not common_rerank and isinstance(rerank, Mapping):
            common_rerank = rerank
        row_id = _bounded_string(getattr(candidate, "row_id", None), max_length=255)
        if not row_id:
            continue
        row = {
            "row_id": row_id,
            "quality_score": _finite_number(audit.get("quality_score")),
            "style_score": _finite_number(audit.get("style_score")),
            "style_confidence": _finite_number(audit.get("style_confidence")),
            "metric_count": _optional_int(audit.get("metric_count")),
            "style_eligible": bool(audit.get("style_eligible")),
            "rank": _optional_int(audit.get("rank")),
            "policy_selected": bool(audit.get("selected")),
            "selection_reason": _bounded_string(audit.get("selection_reason")),
        }
        rows.append(row)

    def style_signal(row: Mapping[str, Any]) -> float | None:
        score = _finite_number(row.get("style_score"))
        confidence = _finite_number(row.get("style_confidence"))
        if score is None:
            return None
        return score * max(0.0, min(1.0, confidence if confidence is not None else 0.0))

    scored = [(row, style_signal(row)) for row in rows]
    scored = [(row, signal) for row, signal in scored if signal is not None]
    style_leader = (
        min(
            scored,
            key=lambda item: (
                -float(item[1]),
                -float(item[0].get("style_score") or 0.0),
                str(item[0]["row_id"]),
            ),
        )[0]
        if scored
        else None
    )
    policy_selected = next(
        (row for row in rows if row.get("policy_selected") is True),
        None,
    )
    raw_profile_ids = common_rerank.get("bundle_profile_ids") or common_rerank.get(
        "profile_ids"
    )
    profile_ids = (
        list(
            dict.fromkeys(
                str(value).strip() for value in raw_profile_ids if str(value).strip()
            )
        )
        if isinstance(raw_profile_ids, Sequence)
        and not isinstance(raw_profile_ids, (str, bytes, bytearray))
        else []
    )
    snapshot: dict[str, Any] = {
        "version": STYLE_FEEDBACK_SNAPSHOT_VERSION,
        "candidates": rows,
        "candidate_count": len(rows),
        "profile_ids": profile_ids,
        "runtime_contract_version": _bounded_string(
            common_rerank.get("runtime_contract_version")
        ),
        "runtime_contract_status": _bounded_string(
            common_rerank.get("runtime_contract_status")
        ),
        "runtime_contract_hash": _bounded_string(
            common_rerank.get("runtime_contract_hash"), max_length=64
        ),
        "target_hash": _bounded_string(common_rerank.get("target_hash"), max_length=64),
        "scorer_version": _bounded_string(common_rerank.get("scorer_version")),
        "applied_mode": _bounded_string(common_rerank.get("applied_mode")),
        "machine_style_leader_row_id": (
            style_leader["row_id"] if style_leader is not None else None
        ),
        "machine_policy_selected_row_id": (
            policy_selected["row_id"] if policy_selected is not None else None
        ),
    }
    snapshot["snapshot_hash"] = _payload_hash(snapshot)
    return snapshot


def validate_candidate_style_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = copy.deepcopy(dict(payload))
    supplied_hash = str(snapshot.pop("snapshot_hash", "") or "")
    if snapshot.get("version") != STYLE_FEEDBACK_SNAPSHOT_VERSION:
        raise ValueError("unsupported style feedback snapshot")
    rows = snapshot.get("candidates")
    if not isinstance(rows, list) or int(snapshot.get("candidate_count", -1)) != len(
        rows
    ):
        raise ValueError("style feedback snapshot candidate count mismatch")
    row_ids = [str(row.get("row_id") or "") for row in rows if isinstance(row, Mapping)]
    if (
        len(row_ids) != len(rows)
        or len(set(row_ids)) != len(row_ids)
        or not all(row_ids)
    ):
        raise ValueError("style feedback snapshot candidate ids are invalid")
    if not supplied_hash or _payload_hash(snapshot) != supplied_hash:
        raise ValueError("style feedback snapshot hash mismatch")
    snapshot["snapshot_hash"] = supplied_hash
    return snapshot


def build_candidate_selection_feedback(
    gate_details: Mapping[str, Any],
    *,
    scene_id: str,
    selected_row_id: str,
    preference_tags: Iterable[Any] | None,
    no_clear_difference: bool,
    observed_at: str,
) -> dict[str, Any] | None:
    raw_snapshot = gate_details.get("style_feedback_snapshot")
    if not isinstance(raw_snapshot, Mapping):
        return None
    snapshot = validate_candidate_style_snapshot(raw_snapshot)
    by_row = {
        str(row["row_id"]): row
        for row in snapshot["candidates"]
        if isinstance(row, Mapping)
    }
    selected = by_row.get(str(selected_row_id))
    if selected is None:
        raise ValueError("selected candidate is missing from style feedback snapshot")
    tags = normalize_preference_tags(preference_tags)
    style_attributed = any(tag in STYLE_ATTRIBUTION_TAGS for tag in tags)
    style_leader_id = snapshot.get("machine_style_leader_row_id")
    selected_signal = None
    style_score = _finite_number(selected.get("style_score"))
    style_confidence = _finite_number(selected.get("style_confidence"))
    if style_score is not None and style_confidence is not None:
        selected_signal = style_score * max(0.0, min(1.0, style_confidence))
    leader = by_row.get(str(style_leader_id)) if style_leader_id else None
    leader_signal = None
    if leader is not None:
        leader_score = _finite_number(leader.get("style_score"))
        leader_confidence = _finite_number(leader.get("style_confidence"))
        if leader_score is not None and leader_confidence is not None:
            leader_signal = leader_score * max(0.0, min(1.0, leader_confidence))

    agreement = (
        str(selected_row_id) == str(style_leader_id)
        if style_attributed and style_leader_id
        else None
    )
    feedback: dict[str, Any] = {
        "version": STYLE_FEEDBACK_VERSION,
        "scene_id": str(scene_id),
        "observed_at": str(observed_at),
        "selected_row_id": str(selected_row_id),
        "preference_tags": tags,
        "style_attributed": style_attributed,
        "no_clear_difference": bool(no_clear_difference),
        "machine_style_leader_row_id": style_leader_id,
        "machine_policy_selected_row_id": snapshot.get(
            "machine_policy_selected_row_id"
        ),
        "agrees_with_machine_style_leader": agreement,
        "selected_style_score": style_score,
        "selected_style_confidence": style_confidence,
        "selected_style_eligible": selected.get("style_eligible") is True,
        "style_leader_eligible": (
            leader.get("style_eligible") is True if leader is not None else False
        ),
        "selected_style_signal": selected_signal,
        "style_leader_signal": leader_signal,
        "style_signal_margin_from_leader": (
            selected_signal - leader_signal
            if selected_signal is not None and leader_signal is not None
            else None
        ),
        "profile_ids": list(snapshot.get("profile_ids") or []),
        "runtime_contract_version": snapshot.get("runtime_contract_version"),
        "runtime_contract_status": snapshot.get("runtime_contract_status"),
        "runtime_contract_hash": snapshot.get("runtime_contract_hash"),
        "target_hash": snapshot.get("target_hash"),
        "scorer_version": snapshot.get("scorer_version"),
        "source_snapshot_hash": snapshot.get("snapshot_hash"),
        "observational_calibration_eligible": bool(
            style_attributed
            and not no_clear_difference
            and agreement is not None
            and selected_signal is not None
            and selected.get("style_eligible") is True
            and leader is not None
            and leader.get("style_eligible") is True
        ),
        # A production policy still requires a separately frozen, human-verified
        # blind evaluation report. Incidental product choices cannot self-train or
        # silently switch the reranker to active mode.
        "policy_evidence_eligible": False,
        "policy_evidence_reason": "requires_frozen_human_verified_blind_evaluation",
    }
    feedback["feedback_id"] = _payload_hash(feedback)
    return feedback


def validate_candidate_selection_feedback(payload: Mapping[str, Any]) -> dict[str, Any]:
    feedback = copy.deepcopy(dict(payload))
    supplied_id = str(feedback.pop("feedback_id", "") or "")
    tags = feedback.get("preference_tags")
    if feedback.get("version") != STYLE_FEEDBACK_VERSION:
        raise ValueError("unsupported style candidate feedback")
    if (
        not str(feedback.get("scene_id") or "")
        or not str(feedback.get("selected_row_id") or "")
        or not isinstance(tags, list)
        or normalize_preference_tags(tags) != tags
        or feedback.get("policy_evidence_eligible") is not False
    ):
        raise ValueError("style candidate feedback shape is invalid")
    if not supplied_id or supplied_id != _payload_hash(feedback):
        raise ValueError("style candidate feedback hash mismatch")
    feedback["feedback_id"] = supplied_id
    return feedback


def summarize_profile_candidate_feedback(
    session: Any, profile_id: str
) -> dict[str, Any]:
    events = session.scalars(
        select(HumanReviewEvent).where(
            HumanReviewEvent.event_source == "candidate_selection"
        )
    ).all()
    observations: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    invalid_observations = 0
    for event in events:
        details = event.details_json or {}
        history = details.get("style_feedback_history")
        if not isinstance(history, list):
            current = details.get("style_feedback")
            history = [current] if isinstance(current, Mapping) else []
        for item in history:
            if not isinstance(item, Mapping):
                invalid_observations += 1
                continue
            try:
                feedback = validate_candidate_selection_feedback(item)
            except ValueError:
                invalid_observations += 1
                continue
            if profile_id not in (feedback.get("profile_ids") or []):
                continue
            feedback_id = str(feedback.get("feedback_id") or "")
            if feedback_id and feedback_id in seen_ids:
                continue
            if feedback_id:
                seen_ids.add(feedback_id)
            observations.append(feedback)

    attributed = [item for item in observations if item.get("style_attributed") is True]
    calibration = [
        item
        for item in attributed
        if item.get("observational_calibration_eligible") is True
    ]
    agreements = [
        item
        for item in calibration
        if item.get("agrees_with_machine_style_leader") is True
    ]
    disagreements = [
        item
        for item in calibration
        if item.get("agrees_with_machine_style_leader") is False
    ]
    return {
        "version": STYLE_FEEDBACK_VERSION,
        "profile_id": str(profile_id),
        "total_observations": len(observations),
        "invalid_observations": invalid_observations,
        "style_attributed_observations": len(attributed),
        "calibration_observations": len(calibration),
        "no_clear_difference_observations": sum(
            item.get("no_clear_difference") is True for item in observations
        ),
        "machine_style_agreements": len(agreements),
        "machine_style_disagreements": len(disagreements),
        "machine_style_agreement_rate": (
            len(agreements) / len(calibration) if calibration else None
        ),
        "scorer_versions": sorted(
            {
                str(item["scorer_version"])
                for item in observations
                if item.get("scorer_version")
            }
        ),
        "policy_evidence_eligible": False,
        "policy_evidence_reason": "observational_feedback_requires_separate_blind_evaluation",
    }


__all__ = [
    "ALLOWED_PREFERENCE_TAGS",
    "STYLE_ATTRIBUTION_TAGS",
    "STYLE_FEEDBACK_SNAPSHOT_VERSION",
    "STYLE_FEEDBACK_VERSION",
    "build_candidate_selection_feedback",
    "build_candidate_style_snapshot",
    "normalize_preference_tags",
    "summarize_profile_candidate_feedback",
    "validate_candidate_style_snapshot",
    "validate_candidate_selection_feedback",
]
