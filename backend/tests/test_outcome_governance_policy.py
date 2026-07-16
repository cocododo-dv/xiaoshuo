from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from novel_system.services.outcome_governance_policy import (
    apply_evaluation_report,
    load_outcome_governance_policy,
)


def _eligible_report(*, decision: str = "upgrade_to_default") -> dict:
    return {
        "experiment_id": "exp_human_1",
        "evidence_provenance": "human",
        "frozen_manifest_verified": True,
        "frozen_pair_manifest_hash": "abc123",
        "policy_evidence_eligible": True,
        "decision": decision,
        "requires_fresh_replication": False,
        "non_tie_n": 30,
        "treatment_wins": 21,
        "control_wins": 9,
        "p_value": 0.042774,
    }


def test_policy_loader_fails_closed_for_missing_or_unverified_enabled_file(tmp_path) -> None:
    assert load_outcome_governance_policy(tmp_path / "missing.json").best_of_n_default_enabled is False
    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text(
        json.dumps({"schema_version": 1, "best_of_n_default_enabled": True, "decision": "upgrade_to_default"}),
        encoding="utf-8",
    )
    assert load_outcome_governance_policy(unsafe).best_of_n_default_enabled is False


def test_apply_report_refuses_synthetic_or_replication_pending_evidence(tmp_path) -> None:
    synthetic = _eligible_report()
    synthetic["policy_evidence_eligible"] = False
    with pytest.raises(ValueError):
        apply_evaluation_report(synthetic, path=tmp_path / "policy.json")

    replication = _eligible_report()
    replication["requires_fresh_replication"] = True
    with pytest.raises(ValueError):
        apply_evaluation_report(replication, path=tmp_path / "policy.json")


def test_apply_verified_human_report_enables_default_atomically(tmp_path) -> None:
    path = tmp_path / "policy.json"

    applied = apply_evaluation_report(_eligible_report(), path=path)
    loaded = load_outcome_governance_policy(path)

    assert applied["best_of_n_default_enabled"] is True
    assert loaded.best_of_n_default_enabled is True
    assert loaded.evidence["experiment_id"] == "exp_human_1"


def test_keep_optional_report_disables_default(tmp_path) -> None:
    path = tmp_path / "policy.json"
    apply_evaluation_report(_eligible_report(decision="keep_optional"), path=path)
    assert load_outcome_governance_policy(path).best_of_n_default_enabled is False


def test_best_of_n_is_optional_by_default_and_full_rigor_cannot_bypass_evidence() -> None:
    from novel_system.services.orchestrator import Orchestrator

    contract = SimpleNamespace(payload_json={"scene_crucible": "x" * 50})
    automatic = SimpleNamespace(reasons=["golden_chapter"], initial_best_of_n=3)
    explicit = SimpleNamespace(reasons=["constraint_intensity_full_rigor"], initial_best_of_n=3)
    orchestrator = SimpleNamespace(
        scene_generation_service=SimpleNamespace(
            _llm_runner=SimpleNamespace(provider_execution_mode="online")
        )
    )

    assert Orchestrator._best_of_n_count(orchestrator, contract, criticality=automatic) == 1
    assert Orchestrator._best_of_n_count(orchestrator, contract, criticality=explicit) == 1
