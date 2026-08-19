"""Frozen synthetic A/B for content-independent StyleReference RAG retrieval."""

from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Any, Mapping

from novel_system.services.hash_engine import canonical_json
from novel_system.services.style_reference.rag import (
    content_restrained_style_score,
    legacy_content_coverage_score,
)
from novel_system.services.style_reference.style_signature import (
    STYLE_SIGNATURE_VERSION,
)


RAG_AB_EVALUATOR_VERSION = "style_reference_rag_ab_v1"


def default_rag_ab_manifest_path() -> Path:
    return (
        Path(__file__).resolve().parents[5]
        / "config"
        / "evals"
        / "style_reference"
        / "rag_content_independence_v1.json"
    )


def load_rag_ab_manifest(path: str | Path | None = None) -> dict[str, Any]:
    manifest_path = Path(path) if path is not None else default_rag_ab_manifest_path()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("RAG A/B manifest schema_version must be 1")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) < 3:
        raise ValueError("RAG A/B manifest requires at least three cases")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            raise ValueError("RAG A/B case must be an object")
        case_id = str(case.get("case_id") or "").strip()
        if not case_id or case_id in seen:
            raise ValueError("RAG A/B case_id must be non-empty and unique")
        seen.add(case_id)
        if case.get("granularity") not in {"sentence", "paragraph", "scene"}:
            raise ValueError(f"RAG A/B case {case_id} has invalid granularity")
        if not str(case.get("query") or "").strip():
            raise ValueError(f"RAG A/B case {case_id} has empty query")
        for arm in ("style_target", "content_distractor"):
            candidate = case.get(arm)
            if not isinstance(candidate, Mapping):
                raise ValueError(f"RAG A/B case {case_id} lacks {arm}")
            if (
                not str(candidate.get("id") or "").strip()
                or not str(candidate.get("text") or "").strip()
            ):
                raise ValueError(f"RAG A/B case {case_id} has invalid {arm}")
    return payload


def evaluate_rag_content_independence(
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    cases = list(manifest.get("cases") or [])
    case_reports: list[dict[str, Any]] = []
    control_hits = 0
    treatment_hits = 0
    treatment_margins: list[float] = []
    for case in cases:
        case_id = str(case["case_id"])
        granularity = str(case["granularity"])
        query = str(case["query"])
        target = dict(case["style_target"])
        distractor = dict(case["content_distractor"])

        control_scores = {
            str(target["id"]): legacy_content_coverage_score(
                str(target["text"]), set(query)
            ),
            str(distractor["id"]): legacy_content_coverage_score(
                str(distractor["text"]), set(query)
            ),
        }
        treatment_details = {
            str(target["id"]): content_restrained_style_score(
                query,
                str(target["text"]),
                granularity=granularity,
            ),
            str(distractor["id"]): content_restrained_style_score(
                query,
                str(distractor["text"]),
                granularity=granularity,
            ),
        }
        treatment_scores = {
            candidate_id: details["final_score"]
            for candidate_id, details in treatment_details.items()
        }
        control_winner = max(
            control_scores, key=lambda item: (control_scores[item], item)
        )
        treatment_winner = max(
            treatment_scores,
            key=lambda item: (treatment_scores[item], item),
        )
        target_id = str(target["id"])
        distractor_id = str(distractor["id"])
        control_hit = control_winner == target_id
        treatment_hit = treatment_winner == target_id
        control_hits += int(control_hit)
        treatment_hits += int(treatment_hit)
        margin = treatment_scores[target_id] - treatment_scores[distractor_id]
        treatment_margins.append(margin)
        case_reports.append(
            {
                "case_id": case_id,
                "granularity": granularity,
                "control_winner": control_winner,
                "treatment_winner": treatment_winner,
                "control_style_hit_at_1": control_hit,
                "treatment_style_hit_at_1": treatment_hit,
                "control_scores": {
                    key: round(value, 6)
                    for key, value in sorted(control_scores.items())
                },
                "treatment_scores": {
                    key: round(value, 6)
                    for key, value in sorted(treatment_scores.items())
                },
                "treatment_style_components": {
                    key: {
                        name: round(value, 6) for name, value in sorted(details.items())
                    }
                    for key, details in sorted(treatment_details.items())
                },
                "treatment_style_margin": round(margin, 6),
            }
        )

    count = len(cases)
    control_rate = control_hits / max(1, count)
    treatment_rate = treatment_hits / max(1, count)
    mean_margin = statistics.fmean(treatment_margins) if treatment_margins else 0.0
    manifest_projection = dict(manifest)
    manifest_hash = hashlib.sha256(
        canonical_json(manifest_projection).encode("utf-8")
    ).hexdigest()
    passed = bool(
        count >= 3
        and treatment_rate == 1.0
        and treatment_rate > control_rate
        and mean_margin >= 0.05
    )
    return {
        "schema_version": 1,
        "evaluator_version": RAG_AB_EVALUATOR_VERSION,
        "style_signature_version": STYLE_SIGNATURE_VERSION,
        "manifest_id": manifest.get("manifest_id"),
        "manifest_hash": manifest_hash,
        "case_count": count,
        "control": {
            "strategy": "raw_query_character_coverage_v1",
            "style_hit_at_1": round(control_rate, 4),
            "content_distractor_rate": round(1.0 - control_rate, 4),
        },
        "treatment": {
            "strategy": "content_restrained_style_signature_v2",
            "style_hit_at_1": round(treatment_rate, 4),
            "content_distractor_rate": round(1.0 - treatment_rate, 4),
            "mean_style_margin": round(mean_margin, 6),
        },
        "passed": passed,
        "human_verified": False,
        "policy_evidence_eligible": False,
        "evidence_scope": "synthetic_controlled_diagnostic",
        "cases": case_reports,
    }


def run_rag_content_independence_ab(path: str | Path | None = None) -> dict[str, Any]:
    return evaluate_rag_content_independence(load_rag_ab_manifest(path))


__all__ = [
    "RAG_AB_EVALUATOR_VERSION",
    "default_rag_ab_manifest_path",
    "evaluate_rag_content_independence",
    "load_rag_ab_manifest",
    "run_rag_content_independence_ab",
]
