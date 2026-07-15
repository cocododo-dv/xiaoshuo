"""Evidence-backed production defaults for expensive quality strategies.

The repository policy is deliberately fail-closed: a missing or malformed file keeps
Best-of-N optional. A human-evidence report must pass the evaluation service's policy
gate before :func:`apply_evaluation_report` can change the default.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novel_system.db.models import utcnow


@dataclass(frozen=True, slots=True)
class OutcomeGovernancePolicy:
    best_of_n_default_enabled: bool = False
    decision: str = "keep_optional"
    evidence: dict[str, Any] | None = None


def default_policy_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "outcome-governance-policy.json"


def load_outcome_governance_policy(path: str | Path | None = None) -> OutcomeGovernancePolicy:
    policy_path = Path(path) if path is not None else default_policy_path()
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return OutcomeGovernancePolicy()
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return OutcomeGovernancePolicy()
    enabled = payload.get("best_of_n_default_enabled") is True
    decision = str(payload.get("decision") or "keep_optional")
    if decision not in {"upgrade_to_default", "keep_optional", "disable"}:
        return OutcomeGovernancePolicy()
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    if enabled and (
        decision != "upgrade_to_default"
        or evidence.get("provenance") != "human"
        or not evidence.get("experiment_id")
        or not evidence.get("manifest_hash")
    ):
        return OutcomeGovernancePolicy()
    return OutcomeGovernancePolicy(
        best_of_n_default_enabled=enabled,
        decision=decision,
        evidence=dict(evidence),
    )


def apply_evaluation_report(report: dict[str, Any], *, path: str | Path | None = None) -> dict[str, Any]:
    """Apply an eligible human report atomically; reject synthetic/incomplete evidence."""
    if report.get("policy_evidence_eligible") is not True:
        raise ValueError("evaluation report is not eligible to change production policy")
    decision = str(report.get("decision") or "")
    if decision not in {"upgrade_to_default", "keep_optional", "disable"}:
        raise ValueError(f"evaluation decision {decision!r} is not actionable")
    if decision == "upgrade_to_default" and report.get("requires_fresh_replication") is True:
        raise ValueError("fresh replication is required before enabling the default")
    if report.get("evidence_provenance") != "human" or report.get("frozen_manifest_verified") is not True:
        raise ValueError("verified human provenance and a frozen manifest are required")

    payload = {
        "schema_version": 1,
        "best_of_n_default_enabled": decision == "upgrade_to_default",
        "decision": decision,
        "evidence": {
            "experiment_id": report.get("experiment_id"),
            "provenance": "human",
            "manifest_hash": report.get("frozen_pair_manifest_hash"),
            "non_tie_n": report.get("non_tie_n"),
            "treatment_wins": report.get("treatment_wins"),
            "control_wins": report.get("control_wins"),
            "p_value": report.get("p_value"),
            "applied_at": utcnow(),
        },
    }
    policy_path = Path(path) if path is not None else default_policy_path()
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{policy_path.name}.", dir=policy_path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, policy_path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return payload
