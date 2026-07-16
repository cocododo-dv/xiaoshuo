from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sqlite3
import sys
from pathlib import Path
from typing import Any

from novel_system.tools.orphan_quarantine import (
    EvidenceValidationError,
    assess_evidence,
    load_evidence,
    scan_orphans,
)


LEGACY_REQUIRED_TABLES = (
    "evaluation_experiments",
    "evaluation_pairs",
    "evaluation_votes",
    "scene_run_states",
)

LEGACY_REQUIRED_COLUMNS = {
    "scene_run_states": (
        "latest_valid_draft_row_id",
        "run_policy",
        "scene_token_budget",
        "scene_tokens_used",
    ),
}

LEGACY_REVISION = "20260712_0064"
C1B_REVISION = "20260713_0065"
EVIDENCE_GATE_REVISION = "20260715_0066"
PAIR_GENRE_REVISION = "20260715_0067"
NARRATIVE_POSITION_REVISION = "20260715_0068"
AUTHOR_CANONICAL_REVISION = "20260715_0069"
QUALITY_EVIDENCE_REVISION = "20260715_0070"
REVISION_ALIASES = {
    "0064": LEGACY_REVISION,
    LEGACY_REVISION: LEGACY_REVISION,
    "0065": C1B_REVISION,
    C1B_REVISION: C1B_REVISION,
    "0066": EVIDENCE_GATE_REVISION,
    EVIDENCE_GATE_REVISION: EVIDENCE_GATE_REVISION,
    "0067": PAIR_GENRE_REVISION,
    PAIR_GENRE_REVISION: PAIR_GENRE_REVISION,
    "0068": NARRATIVE_POSITION_REVISION,
    NARRATIVE_POSITION_REVISION: NARRATIVE_POSITION_REVISION,
    "0069": AUTHOR_CANONICAL_REVISION,
    AUTHOR_CANONICAL_REVISION: AUTHOR_CANONICAL_REVISION,
    "0070": QUALITY_EVIDENCE_REVISION,
    QUALITY_EVIDENCE_REVISION: QUALITY_EVIDENCE_REVISION,
}
REVISION_SEQUENCE = (
    LEGACY_REVISION,
    C1B_REVISION,
    EVIDENCE_GATE_REVISION,
    PAIR_GENRE_REVISION,
    NARRATIVE_POSITION_REVISION,
    AUTHOR_CANONICAL_REVISION,
    QUALITY_EVIDENCE_REVISION,
)
REVISION_RANK = {
    revision: index for index, revision in enumerate(REVISION_SEQUENCE)
}


def _sqlite_runtime_foreign_key_policy() -> dict[str, Any]:
    """Return the application FK policy that release preflight must enforce.

    ``PRAGMA foreign_keys`` is connection-local.  Turning it on for this audit
    connection proves the schema can be checked, but it says nothing about an
    application engine explicitly configured with the emergency opt-out.  A
    database is therefore never release-ready while that opt-out is active (or
    malformed), even though maintenance tooling may still open it deliberately.
    """

    raw = os.environ.get("NOVEL_SYSTEM_SQLITE_FOREIGN_KEYS_ENABLED")
    if raw is None:
        return {"enabled": True, "valid": True, "source": "default", "raw": None}
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return {"enabled": True, "valid": True, "source": "environment", "raw": raw}
    if normalized in {"0", "false", "no", "off"}:
        return {"enabled": False, "valid": True, "source": "environment", "raw": raw}
    return {"enabled": False, "valid": False, "source": "environment", "raw": raw}
C1B_REQUIRED_TABLES = LEGACY_REQUIRED_TABLES + (
    "llm_calls",
    "llm_call_attempts",
    "chapter_run_jobs",
)
C1B_REQUIRED_COLUMNS = {
    **LEGACY_REQUIRED_COLUMNS,
    "scene_run_states": LEGACY_REQUIRED_COLUMNS["scene_run_states"]
    + (
        "scene_tokens_reserved",
        "scene_budget_basis_json",
        "provider_attempts_used",
        "provider_attempt_budget",
        "active_execution_id",
        "run_execution_status",
        "run_checkpoint",
        "run_checkpoint_json",
        "active_run_job_id",
    ),
    "llm_calls": (
        "scope_type",
        "scope_id",
        "run_job_id",
        "execution_id",
        "execution_step_key",
        "estimated_tokens",
        "reserved_tokens",
        "budget_charged_tokens",
        "usage_is_estimate",
        "accounting_status",
        "request_dispatched_at",
        "settled_at",
    ),
    "llm_call_attempts": (
        "attempt_id",
        "llm_call_id",
        "provider_attempt_no",
        "dispatch_kind",
        "request_max_output_tokens",
        "provider_request_id",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_tokens",
        "reserved_tokens",
        "budget_charged_tokens",
        "usage_is_estimate",
        "accounting_status",
        "request_dispatched_at",
        "settled_at",
        "latency_ms",
        "error_code",
        "error_text",
        "created_at",
    ),
    "chapter_run_jobs": ("scene_id", "created_at"),
}

EVIDENCE_GATE_REQUIRED_TABLES = C1B_REQUIRED_TABLES
EVIDENCE_GATE_REQUIRED_COLUMNS = {
    **C1B_REQUIRED_COLUMNS,
    "evaluation_experiments": (
        "evidence_provenance",
        "frozen_at",
        "frozen_pair_manifest_hash",
    ),
}

PAIR_GENRE_REQUIRED_TABLES = EVIDENCE_GATE_REQUIRED_TABLES
PAIR_GENRE_REQUIRED_COLUMNS = {
    **EVIDENCE_GATE_REQUIRED_COLUMNS,
    "evaluation_pairs": ("genre",),
}

NARRATIVE_POSITION_REQUIRED_TABLES = PAIR_GENRE_REQUIRED_TABLES + (
    "chapter_goals",
    "scene_cards",
    "narrative_events",
)
NARRATIVE_POSITION_REQUIRED_COLUMNS = {
    **PAIR_GENRE_REQUIRED_COLUMNS,
    "chapter_goals": ("project_id", "display_order", "chapter_id"),
    "scene_cards": ("project_id", "chapter_id", "scene_seq", "scene_id"),
    "narrative_events": ("project_id", "chapter_id", "scene_id", "entity_id"),
}

AUTHOR_CANONICAL_REQUIRED_TABLES = NARRATIVE_POSITION_REQUIRED_TABLES + (
    "author_drafts",
    "final_scenes",
)
AUTHOR_CANONICAL_REQUIRED_COLUMNS = {
    **NARRATIVE_POSITION_REQUIRED_COLUMNS,
    "scene_run_states": NARRATIVE_POSITION_REQUIRED_COLUMNS["scene_run_states"]
    + (
        "narrative_sync_status",
        "narrative_sync_final_scene_row_id",
    ),
    "author_drafts": (
        "last_promoted_revision_no",
        "last_promoted_final_scene_row_id",
    ),
    "final_scenes": (
        "content_hash",
        "source_kind",
        "source_author_draft_id",
        "source_author_draft_revision_no",
        "parent_final_scene_row_id",
        "superseded_by_final_scene_row_id",
        "created_by",
    ),
}

QUALITY_EVIDENCE_REQUIRED_TABLES = AUTHOR_CANONICAL_REQUIRED_TABLES + (
    "quality_benchmark_manifests",
    "quality_strategy_policies",
    "quality_benchmark_runs",
    "quality_benchmark_results",
    "quality_value_observations",
)
QUALITY_EVIDENCE_REQUIRED_COLUMNS = {
    **AUTHOR_CANONICAL_REQUIRED_COLUMNS,
    "evaluation_experiments": AUTHOR_CANONICAL_REQUIRED_COLUMNS[
        "evaluation_experiments"
    ]
    + (
        "benchmark_manifest_id",
        "benchmark_manifest_hash",
        "hidden_rubric_hash",
    ),
    "evaluation_pairs": AUTHOR_CANONICAL_REQUIRED_COLUMNS["evaluation_pairs"]
    + (
        "scene_function",
        "treatment_benchmark_result_id",
        "control_benchmark_result_id",
        "benchmark_case_id_hash",
    ),
    "quality_benchmark_manifests": (
        "manifest_id",
        "schema_version",
        "manifest_version",
        "split_kind",
        "manifest_hash",
        "public_cases_hash",
        "rubric_hash",
        "case_count",
        "isolation_mode",
        "storage_ref",
        "status",
        "created_at",
    ),
    "quality_strategy_policies": (
        "policy_id",
        "policy_version",
        "genre",
        "scene_function",
        "weights_json",
        "thresholds_json",
        "best_of_n_requested",
        "best_of_n_n",
        "evidence_experiment_id",
        "benchmark_manifest_id",
        "status",
        "created_by",
        "created_at",
        "updated_at",
    ),
    "quality_benchmark_runs": (
        "run_id",
        "manifest_id",
        "manifest_hash",
        "rubric_hash",
        "policy_id",
        "generator_ref",
        "generation_policy_hash",
        "generation_arm",
        "status",
        "case_count_expected",
        "case_count_recorded",
        "created_at",
        "completed_at",
    ),
    "quality_benchmark_results": (
        "result_id",
        "run_id",
        "case_id_hash",
        "genre",
        "scene_function",
        "artifact_ref",
        "generation_input_hash",
        "generation_prompt_hash",
        "output_hash",
        "prompt_leakage_check",
        "automated_metrics_json",
        "cost_tokens",
        "cost_micros",
        "cost_currency",
        "cost_basis",
        "latency_ms",
        "created_at",
    ),
    "quality_value_observations": (
        "observation_id",
        "result_id",
        "reviewer_ref",
        "provenance",
        "source_text_hash",
        "edited_text_hash",
        "human_edit_distance",
        "human_edit_distance_ratio",
        "first_usable",
        "follow_read_intent",
        "created_at",
    ),
}

SCHEMA_PROFILES = {
    LEGACY_REVISION: (LEGACY_REQUIRED_TABLES, LEGACY_REQUIRED_COLUMNS),
    C1B_REVISION: (C1B_REQUIRED_TABLES, C1B_REQUIRED_COLUMNS),
    EVIDENCE_GATE_REVISION: (
        EVIDENCE_GATE_REQUIRED_TABLES,
        EVIDENCE_GATE_REQUIRED_COLUMNS,
    ),
    PAIR_GENRE_REVISION: (PAIR_GENRE_REQUIRED_TABLES, PAIR_GENRE_REQUIRED_COLUMNS),
    NARRATIVE_POSITION_REVISION: (
        NARRATIVE_POSITION_REQUIRED_TABLES,
        NARRATIVE_POSITION_REQUIRED_COLUMNS,
    ),
    AUTHOR_CANONICAL_REVISION: (
        AUTHOR_CANONICAL_REQUIRED_TABLES,
        AUTHOR_CANONICAL_REQUIRED_COLUMNS,
    ),
    QUALITY_EVIDENCE_REVISION: (
        QUALITY_EVIDENCE_REQUIRED_TABLES,
        QUALITY_EVIDENCE_REQUIRED_COLUMNS,
    ),
}

C1B_COLUMN_CONTRACTS = {
    "scene_run_states": {
        "scene_tokens_reserved": {"not_null": True, "default": "0"},
        "provider_attempts_used": {"not_null": True, "default": "0"},
        "provider_attempt_budget": {"not_null": True, "default": "32"},
    },
    "llm_calls": {
        "llm_call_id": {"not_null": True, "default": None},
        "scope_type": {"not_null": True, "default": None},
        "scope_id": {"not_null": True, "default": None},
        "estimated_tokens": {"not_null": True, "default": "0"},
        "reserved_tokens": {"not_null": True, "default": "0"},
        "budget_charged_tokens": {"not_null": True, "default": "0"},
        "usage_is_estimate": {"not_null": True, "default": "1"},
        "accounting_status": {"not_null": True, "default": "reserved"},
    },
    "llm_call_attempts": {
        "attempt_id": {"not_null": True, "default": None},
        "llm_call_id": {"not_null": True, "default": None},
        "provider_attempt_no": {"not_null": True, "default": None},
        "dispatch_kind": {"not_null": True, "default": None},
        "request_max_output_tokens": {"not_null": True, "default": "0"},
        "prompt_tokens": {"not_null": True, "default": "0"},
        "completion_tokens": {"not_null": True, "default": "0"},
        "total_tokens": {"not_null": True, "default": "0"},
        "estimated_tokens": {"not_null": True, "default": "0"},
        "reserved_tokens": {"not_null": True, "default": "0"},
        "budget_charged_tokens": {"not_null": True, "default": "0"},
        "usage_is_estimate": {"not_null": True, "default": "1"},
        "accounting_status": {"not_null": True, "default": None},
        "latency_ms": {"not_null": True, "default": "0"},
        "created_at": {"not_null": True, "default": None},
    },
}

C1B_PRIMARY_KEY_CONTRACTS = {
    "llm_calls": ("llm_call_id",),
    "llm_call_attempts": ("attempt_id",),
}

C1B_CHECK_CONTRACTS = {
    "scene_run_states": {
        "ck_scene_run_states_tokens_reserved_nonnegative": "scene_tokens_reserved >= 0",
        "ck_scene_run_states_provider_attempts_used_nonnegative": "provider_attempts_used >= 0",
        "ck_scene_run_states_provider_attempt_budget_nonnegative": "provider_attempt_budget >= 0",
    },
    "llm_calls": {
        "ck_llm_calls_estimated_tokens_nonnegative": "estimated_tokens >= 0",
        "ck_llm_calls_reserved_tokens_nonnegative": "reserved_tokens >= 0",
        "ck_llm_calls_budget_charged_tokens_nonnegative": "budget_charged_tokens >= 0",
        "ck_llm_calls_budget_charged_within_reservation": (
            "budget_charged_tokens <= reserved_tokens"
        ),
        "ck_llm_calls_accounting_status": (
            "accounting_status IN "
            "('reserved','settled','failed','released','rejected','usage_exceeds_reservation')"
        ),
    },
    "llm_call_attempts": {
        "ck_llm_call_attempts_provider_attempt_no_nonnegative": (
            "provider_attempt_no >= 0"
        ),
        "ck_llm_call_attempts_request_max_output_tokens_nonnegative": (
            "request_max_output_tokens >= 0"
        ),
        "ck_llm_call_attempts_prompt_tokens_nonnegative": "prompt_tokens >= 0",
        "ck_llm_call_attempts_completion_tokens_nonnegative": "completion_tokens >= 0",
        "ck_llm_call_attempts_total_tokens_nonnegative": "total_tokens >= 0",
        "ck_llm_call_attempts_estimated_tokens_nonnegative": "estimated_tokens >= 0",
        "ck_llm_call_attempts_reserved_tokens_nonnegative": "reserved_tokens >= 0",
        "ck_llm_call_attempts_budget_charged_tokens_nonnegative": (
            "budget_charged_tokens >= 0"
        ),
        "ck_llm_call_attempts_budget_charged_within_reservation": (
            "budget_charged_tokens <= reserved_tokens"
        ),
        "ck_llm_call_attempts_latency_ms_nonnegative": "latency_ms >= 0",
        "ck_llm_call_attempts_accounting_status": (
            "accounting_status IN "
            "('reserved','settled','failed','released','rejected','usage_exceeds_reservation')"
        ),
        "ck_llm_call_attempts_dispatch_kind": (
            "dispatch_kind IN "
            "('initial','transport_retry','response_parse_retry','api_mode_degrade',"
            "'structured_output_degrade','missing_text_degrade','system_probe')"
        ),
    },
}

C1B_INDEX_CONTRACTS = {
    "ix_llm_calls_scope_created": ("llm_calls", ("scope_type", "scope_id", "created_at")),
    "ix_llm_calls_run_job": ("llm_calls", ("run_job_id",)),
    "ix_llm_calls_execution_step": ("llm_calls", ("execution_id", "execution_step_key")),
    "ix_llm_calls_accounting_status": ("llm_calls", ("accounting_status",)),
    "ix_llm_call_attempts_call_status": (
        "llm_call_attempts",
        ("llm_call_id", "accounting_status"),
    ),
    "ix_chapter_run_jobs_scene_created": (
        "chapter_run_jobs",
        ("scene_id", "created_at"),
    ),
}

EVIDENCE_GATE_COLUMN_CONTRACTS = {
    "evaluation_experiments": {
        "evidence_provenance": {
            "type": "VARCHAR",
            "not_null": True,
        },
        "frozen_at": {"type": "VARCHAR", "not_null": False, "default": None},
        "frozen_pair_manifest_hash": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
    },
}

PAIR_GENRE_COLUMN_CONTRACTS = {
    "evaluation_pairs": {
        "genre": {"type": "VARCHAR", "not_null": False, "default": None},
    },
}

NARRATIVE_POSITION_INDEX_CONTRACTS = {
    "ix_chapter_goals_project_display_order": (
        "chapter_goals",
        ("project_id", "display_order", "chapter_id"),
    ),
    "ix_scene_cards_project_chapter_seq": (
        "scene_cards",
        ("project_id", "chapter_id", "scene_seq", "scene_id"),
    ),
    "ix_narrative_events_project_chapter_scene": (
        "narrative_events",
        ("project_id", "chapter_id", "scene_id"),
    ),
    "ix_narrative_events_project_entity_scene": (
        "narrative_events",
        ("project_id", "entity_id", "scene_id"),
    ),
}

AUTHOR_CANONICAL_COLUMN_CONTRACTS = {
    "author_drafts": {
        "last_promoted_revision_no": {
            "type": "INTEGER",
            "not_null": False,
            "default": None,
        },
        "last_promoted_final_scene_row_id": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
    },
    "final_scenes": {
        "content_hash": {"type": "VARCHAR", "not_null": False, "default": None},
        "source_kind": {
            "type": "VARCHAR",
            "not_null": True,
        },
        "source_author_draft_id": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
        "source_author_draft_revision_no": {
            "type": "INTEGER",
            "not_null": False,
            "default": None,
        },
        "parent_final_scene_row_id": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
        "superseded_by_final_scene_row_id": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
        "created_by": {
            "type": "VARCHAR",
            "not_null": True,
        },
    },
    "scene_run_states": {
        "narrative_sync_status": {
            "type": "VARCHAR",
            "not_null": True,
        },
        "narrative_sync_final_scene_row_id": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
    },
}

QUALITY_EVIDENCE_COLUMN_CONTRACTS = {
    "evaluation_experiments": {
        "benchmark_manifest_id": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
        "benchmark_manifest_hash": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
        "hidden_rubric_hash": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
    },
    "evaluation_pairs": {
        "scene_function": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
        "treatment_benchmark_result_id": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
        "control_benchmark_result_id": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
        "benchmark_case_id_hash": {
            "type": "VARCHAR",
            "not_null": False,
            "default": None,
        },
    },
    "quality_benchmark_manifests": {
        "manifest_id": {"type": "VARCHAR", "not_null": True, "default": None},
        "schema_version": {"type": "INTEGER", "not_null": True, "default": "1"},
        "manifest_version": {"type": "VARCHAR", "not_null": True, "default": None},
        "split_kind": {"type": "VARCHAR", "not_null": True, "default": "hidden"},
        "manifest_hash": {"type": "VARCHAR", "not_null": True, "default": None},
        "public_cases_hash": {"type": "VARCHAR", "not_null": True, "default": None},
        "rubric_hash": {"type": "VARCHAR", "not_null": True, "default": None},
        "case_count": {"type": "INTEGER", "not_null": True, "default": None},
        "isolation_mode": {"type": "VARCHAR", "not_null": True, "default": None},
        "storage_ref": {"type": "TEXT", "not_null": True, "default": None},
        "status": {"type": "VARCHAR", "not_null": True, "default": "frozen"},
        "created_at": {"type": "VARCHAR", "not_null": True, "default": None},
    },
    "quality_strategy_policies": {
        "policy_id": {"type": "VARCHAR", "not_null": True, "default": None},
        "policy_version": {"type": "INTEGER", "not_null": True, "default": "1"},
        "genre": {"type": "VARCHAR", "not_null": True, "default": "*"},
        "scene_function": {"type": "VARCHAR", "not_null": True, "default": "*"},
        "weights_json": {"type": "JSON", "not_null": True, "default": None},
        "thresholds_json": {"type": "JSON", "not_null": True, "default": None},
        "best_of_n_requested": {"type": "BOOLEAN", "not_null": True, "default": "0"},
        "best_of_n_n": {"type": "INTEGER", "not_null": True, "default": "1"},
        "evidence_experiment_id": {"type": "VARCHAR", "not_null": False, "default": None},
        "benchmark_manifest_id": {"type": "VARCHAR", "not_null": False, "default": None},
        "status": {"type": "VARCHAR", "not_null": True, "default": "active"},
        "created_by": {"type": "VARCHAR", "not_null": True, "default": "operator"},
        "created_at": {"type": "VARCHAR", "not_null": True, "default": None},
        "updated_at": {"type": "VARCHAR", "not_null": True, "default": None},
    },
    "quality_benchmark_runs": {
        "run_id": {"type": "VARCHAR", "not_null": True, "default": None},
        "manifest_id": {"type": "VARCHAR", "not_null": True, "default": None},
        "manifest_hash": {"type": "VARCHAR", "not_null": True, "default": None},
        "rubric_hash": {"type": "VARCHAR", "not_null": True, "default": None},
        "policy_id": {"type": "VARCHAR", "not_null": False, "default": None},
        "generator_ref": {"type": "VARCHAR", "not_null": True, "default": None},
        "generation_policy_hash": {
            "type": "VARCHAR",
            "not_null": True,
            "default": None,
        },
        "generation_arm": {
            "type": "VARCHAR",
            "not_null": True,
            "default": "unassigned",
        },
        "status": {"type": "VARCHAR", "not_null": True, "default": "collecting"},
        "case_count_expected": {"type": "INTEGER", "not_null": True, "default": None},
        "case_count_recorded": {"type": "INTEGER", "not_null": True, "default": "0"},
        "created_at": {"type": "VARCHAR", "not_null": True, "default": None},
        "completed_at": {"type": "VARCHAR", "not_null": False, "default": None},
    },
    "quality_benchmark_results": {
        "result_id": {"type": "VARCHAR", "not_null": True, "default": None},
        "run_id": {"type": "VARCHAR", "not_null": True, "default": None},
        "case_id_hash": {"type": "VARCHAR", "not_null": True, "default": None},
        "genre": {"type": "VARCHAR", "not_null": True, "default": None},
        "scene_function": {"type": "VARCHAR", "not_null": True, "default": None},
        "artifact_ref": {"type": "VARCHAR", "not_null": True, "default": None},
        "generation_input_hash": {"type": "VARCHAR", "not_null": True, "default": None},
        "generation_prompt_hash": {"type": "VARCHAR", "not_null": True, "default": None},
        "output_hash": {"type": "VARCHAR", "not_null": True, "default": None},
        "prompt_leakage_check": {"type": "VARCHAR", "not_null": True, "default": "passed"},
        "automated_metrics_json": {"type": "JSON", "not_null": True, "default": None},
        "cost_tokens": {"type": "INTEGER", "not_null": False, "default": None},
        "cost_micros": {"type": "INTEGER", "not_null": False, "default": None},
        "cost_currency": {"type": "VARCHAR", "not_null": False, "default": None},
        "cost_basis": {"type": "VARCHAR", "not_null": False, "default": None},
        "latency_ms": {"type": "INTEGER", "not_null": False, "default": None},
        "created_at": {"type": "VARCHAR", "not_null": True, "default": None},
    },
    "quality_value_observations": {
        "observation_id": {"type": "VARCHAR", "not_null": True, "default": None},
        "result_id": {"type": "VARCHAR", "not_null": True, "default": None},
        "reviewer_ref": {"type": "VARCHAR", "not_null": True, "default": None},
        "provenance": {"type": "VARCHAR", "not_null": True, "default": None},
        "source_text_hash": {"type": "VARCHAR", "not_null": False, "default": None},
        "edited_text_hash": {"type": "VARCHAR", "not_null": False, "default": None},
        "human_edit_distance": {"type": "INTEGER", "not_null": False, "default": None},
        "human_edit_distance_ratio": {"type": "FLOAT", "not_null": False, "default": None},
        "first_usable": {"type": "BOOLEAN", "not_null": False, "default": None},
        "follow_read_intent": {"type": "INTEGER", "not_null": False, "default": None},
        "created_at": {"type": "VARCHAR", "not_null": True, "default": None},
    },
}

QUALITY_EVIDENCE_PRIMARY_KEY_CONTRACTS = {
    "quality_benchmark_manifests": ("manifest_id",),
    "quality_strategy_policies": ("policy_id",),
    "quality_benchmark_runs": ("run_id",),
    "quality_benchmark_results": ("result_id",),
    "quality_value_observations": ("observation_id",),
}

QUALITY_EVIDENCE_CHECK_CONTRACTS = {
    "quality_benchmark_manifests": {
        "ck_quality_benchmark_manifests_case_count_positive": "case_count > 0",
        "ck_quality_benchmark_manifests_hidden_split": "split_kind = 'hidden'",
        "ck_quality_benchmark_manifests_status": "status IN ('frozen','retired')",
    },
    "quality_strategy_policies": {
        "ck_quality_strategy_policies_best_of_n_positive": (
            "best_of_n_n >= 1 AND best_of_n_n <= 5"
        ),
        "ck_quality_strategy_policies_version_positive": "policy_version >= 1",
        "ck_quality_strategy_policies_best_of_n_boolean": (
            "best_of_n_requested IN (0,1)"
        ),
        "ck_quality_strategy_policies_status": "status IN ('active','retired')",
    },
    "quality_benchmark_runs": {
        "ck_quality_benchmark_runs_expected_positive": "case_count_expected > 0",
        "ck_quality_benchmark_runs_recorded_nonnegative": "case_count_recorded >= 0",
        "ck_quality_benchmark_runs_status": "status IN ('collecting','completed','invalid')",
        "ck_quality_benchmark_runs_generation_arm": (
            "generation_arm IN ('treatment','control','unassigned')"
        ),
    },
    "quality_benchmark_results": {
        "ck_quality_benchmark_results_cost_nonnegative": (
            "cost_tokens IS NULL OR cost_tokens >= 0"
        ),
        "ck_quality_benchmark_results_latency_nonnegative": (
            "latency_ms IS NULL OR latency_ms >= 0"
        ),
        "ck_quality_benchmark_results_cost_micros_nonnegative": (
            "cost_micros IS NULL OR cost_micros >= 0"
        ),
        "ck_quality_benchmark_results_cost_tuple_complete": (
            "((cost_micros IS NULL AND cost_currency IS NULL AND cost_basis IS NULL) OR "
            "(cost_micros IS NOT NULL AND cost_currency IS NOT NULL AND cost_basis IS NOT NULL))"
        ),
        "ck_quality_benchmark_results_cost_basis": (
            "cost_basis IS NULL OR cost_basis IN ('estimated','actual','billed')"
        ),
        "ck_quality_benchmark_results_prompt_leakage_passed": (
            "prompt_leakage_check = 'passed'"
        ),
    },
    "quality_value_observations": {
        "ck_quality_value_observations_human_only": "provenance = 'human'",
        "ck_quality_value_observations_edit_distance_nonnegative": (
            "human_edit_distance IS NULL OR human_edit_distance >= 0"
        ),
        "ck_quality_value_observations_edit_ratio_range": (
            "human_edit_distance_ratio IS NULL OR "
            "(human_edit_distance_ratio >= 0 AND human_edit_distance_ratio <= 1)"
        ),
        "ck_quality_value_observations_follow_read_range": (
            "follow_read_intent IS NULL OR "
            "(follow_read_intent >= 1 AND follow_read_intent <= 5)"
        ),
    },
}

QUALITY_EVIDENCE_FOREIGN_KEY_CONTRACTS = {
    "quality_strategy_policies": (
        ("benchmark_manifest_id", "quality_benchmark_manifests", "manifest_id"),
        ("evidence_experiment_id", "evaluation_experiments", "experiment_id"),
    ),
    "quality_benchmark_runs": (
        ("manifest_id", "quality_benchmark_manifests", "manifest_id"),
        ("policy_id", "quality_strategy_policies", "policy_id"),
    ),
    "quality_benchmark_results": (
        ("run_id", "quality_benchmark_runs", "run_id"),
    ),
    "quality_value_observations": (
        ("result_id", "quality_benchmark_results", "result_id"),
    ),
}

QUALITY_EVIDENCE_UNIQUE_CONTRACTS = {
    "quality_strategy_policies": (("genre", "scene_function", "policy_version"),),
    "quality_benchmark_results": (("run_id", "case_id_hash"),),
    "quality_value_observations": (("result_id", "reviewer_ref"),),
}

QUALITY_EVIDENCE_INDEX_CONTRACTS = {
    "ix_quality_benchmark_manifests_hash": (
        "quality_benchmark_manifests",
        ("manifest_hash",),
        True,
    ),
    "ix_quality_strategy_policies_scope_status": (
        "quality_strategy_policies",
        ("genre", "scene_function", "status"),
        False,
    ),
    "ix_quality_benchmark_runs_manifest_status": (
        "quality_benchmark_runs",
        ("manifest_id", "status"),
        False,
    ),
    "ix_quality_benchmark_results_strategy_cell": (
        "quality_benchmark_results",
        ("genre", "scene_function", "run_id"),
        False,
    ),
    "ix_quality_value_observations_result": (
        "quality_value_observations",
        ("result_id",),
        False,
    ),
}


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _normalized_default(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    return normalized.strip("'\"").lower()


def _normalized_sql(value: str) -> str:
    return re.sub(r'[\s"`\[\]\(\)]', "", value).lower()


def _table_sql(connection: sqlite3.Connection, table_name: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return str(row[0] or "") if row else ""


def _blank_sql_range(mask: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if mask[index] not in {"\r", "\n"}:
            mask[index] = " "


def _quoted_token_end(sql: str, start: int, closing: str) -> int:
    index = start + 1
    while index < len(sql):
        if sql[index] == closing:
            if index + 1 < len(sql) and sql[index + 1] == closing:
                index += 2
                continue
            return index + 1
        index += 1
    return len(sql)


def _sql_code_mask(sql: str) -> str:
    mask = list(sql)
    index = 0
    while index < len(sql):
        if sql.startswith("--", index):
            end = sql.find("\n", index + 2)
            end = len(sql) if end < 0 else end
            _blank_sql_range(mask, index, end)
            index = end
            continue
        if sql.startswith("/*", index):
            closing = sql.find("*/", index + 2)
            end = len(sql) if closing < 0 else closing + 2
            _blank_sql_range(mask, index, end)
            index = end
            continue

        character = sql[index]
        if character == "'":
            end = _quoted_token_end(sql, index, "'")
            _blank_sql_range(mask, index, end)
            index = end
            continue
        if character in {'"', "`", "["}:
            closing = "]" if character == "[" else character
            end = _quoted_token_end(sql, index, closing)
            interior_end = end - 1 if end > index and sql[end - 1] == closing else end
            _blank_sql_range(mask, index + 1, interior_end)
            index = end
            continue
        index += 1
    return "".join(mask)


def _sql_tokens(sql: str) -> list[tuple[str, str, int, int]]:
    mask = _sql_code_mask(sql)
    tokens: list[tuple[str, str, int, int]] = []
    index = 0
    while index < len(mask):
        character = mask[index]
        if character.isspace():
            index += 1
            continue
        if character in {'"', "`", "["}:
            closing = "]" if character == "[" else character
            end = _quoted_token_end(sql, index, closing)
            value_end = end - 1 if end > index and sql[end - 1] == closing else end
            value = sql[index + 1 : value_end].replace(closing * 2, closing)
            tokens.append(("quoted_identifier", value, index, end))
            index = end
            continue
        if character.isalpha() or character == "_":
            end = index + 1
            while end < len(mask) and (mask[end].isalnum() or mask[end] in {"_", "$"}):
                end += 1
            tokens.append(("word", sql[index:end], index, end))
            index = end
            continue
        tokens.append(("symbol", character, index, index + 1))
        index += 1
    return tokens


def _named_check_expressions(sql: str, constraint_name: str) -> list[str]:
    tokens = _sql_tokens(sql)
    expressions: list[str] = []
    for index in range(len(tokens) - 3):
        keyword, name, check, opening = tokens[index : index + 4]
        if keyword[0] != "word" or keyword[1].casefold() != "constraint":
            continue
        if name[0] not in {"word", "quoted_identifier"}:
            continue
        if name[1].casefold() != constraint_name.casefold():
            continue
        if check[0] != "word" or check[1].casefold() != "check":
            continue
        if opening[0] != "symbol" or opening[1] != "(":
            continue

        depth = 0
        for token in tokens[index + 3 :]:
            if token[0] != "symbol":
                continue
            if token[1] == "(":
                depth += 1
            elif token[1] == ")":
                depth -= 1
                if depth == 0:
                    expressions.append(sql[opening[3] : token[2]].strip())
                    break
    return expressions


def _index_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> dict[str, dict[str, Any]]:
    indexes: dict[str, dict[str, Any]] = {}
    for row in connection.execute(f"PRAGMA index_list({_quote_identifier(table_name)})"):
        name = str(row[1])
        columns = [
            None if column[2] is None else str(column[2])
            for column in connection.execute(f"PRAGMA index_info({_quote_identifier(name)})")
        ]
        indexes[name] = {
            "columns": columns,
            "unique": bool(row[2]),
            "origin": str(row[3]),
            "partial": bool(row[4]),
        }
    return indexes


def _revision_at_least(
    canonical_revision: str | None,
    minimum_revision: str,
) -> bool:
    if canonical_revision not in REVISION_RANK:
        return False
    return REVISION_RANK[canonical_revision] >= REVISION_RANK[minimum_revision]


def _inspect_column_contracts(
    connection: sqlite3.Connection,
    tables: set[str],
    contracts_by_table: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for table_name, contracts in contracts_by_table.items():
        if table_name not in tables:
            continue
        columns = {
            str(row[1]): {
                "type": str(row[2] or "").strip().upper(),
                "not_null": bool(row[3]),
                "default": _normalized_default(row[4]),
            }
            for row in connection.execute(
                f"PRAGMA table_info({_quote_identifier(table_name)})"
            )
        }
        for column_name, expected in contracts.items():
            metadata = columns.get(column_name)
            if metadata is None:
                continue
            actual = {key: metadata[key] for key in expected}
            if actual != expected:
                errors.append(
                    {
                        "kind": "column_contract",
                        "table": table_name,
                        "column": column_name,
                        "expected": expected,
                        "actual": actual,
                    }
                )
    return errors


def _inspect_index_contracts(
    connection: sqlite3.Connection,
    tables: set[str],
    contracts: dict[str, tuple[str, tuple[str, ...]]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    index_cache: dict[str, dict[str, dict[str, Any]]] = {}
    for name, (table_name, expected_columns) in contracts.items():
        if table_name not in tables:
            continue
        if table_name not in index_cache:
            index_cache[table_name] = _index_columns(connection, table_name)
        actual = index_cache[table_name].get(name)
        expected = {
            "columns": list(expected_columns),
            "unique": False,
            "origin": "c",
            "partial": False,
        }
        if actual != expected:
            errors.append(
                {
                    "kind": "index",
                    "table": table_name,
                    "name": name,
                    "expected": expected,
                    "actual": actual,
                }
            )
    return errors


def _inspect_primary_key_contracts(
    connection: sqlite3.Connection,
    tables: set[str],
    contracts: dict[str, tuple[str, ...]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for table_name, expected_columns in contracts.items():
        if table_name not in tables:
            continue
        primary_key_columns = sorted(
            (
                (int(row[5]), str(row[1]))
                for row in connection.execute(
                    f"PRAGMA table_info({_quote_identifier(table_name)})"
                )
                if int(row[5]) > 0
            ),
            key=lambda item: item[0],
        )
        actual = [column_name for _, column_name in primary_key_columns]
        if actual != list(expected_columns):
            errors.append(
                {
                    "kind": "primary_key",
                    "table": table_name,
                    "expected": list(expected_columns),
                    "actual": actual,
                }
            )
    return errors


def _inspect_check_contracts(
    connection: sqlite3.Connection,
    tables: set[str],
    contracts_by_table: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for table_name, constraints in contracts_by_table.items():
        if table_name not in tables:
            continue
        table_sql = _table_sql(connection, table_name)
        for constraint_name, expected in constraints.items():
            actual_expressions = _named_check_expressions(table_sql, constraint_name)
            matches = (
                len(actual_expressions) == 1
                and _normalized_sql(actual_expressions[0]) == _normalized_sql(expected)
            )
            if matches:
                continue
            actual: str | list[str] = (
                actual_expressions[0]
                if len(actual_expressions) == 1
                else actual_expressions
            )
            errors.append(
                {
                    "kind": "check_constraint",
                    "table": table_name,
                    "name": constraint_name,
                    "expected": expected,
                    "actual": actual,
                }
            )
    return errors


def _inspect_foreign_key_contracts(
    connection: sqlite3.Connection,
    tables: set[str],
    contracts_by_table: dict[str, tuple[tuple[str, str, str], ...]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for table_name, contracts in contracts_by_table.items():
        if table_name not in tables:
            continue
        expected = sorted(
            (
                {
                    "table": parent_table,
                    "from": child_column,
                    "to": parent_column,
                    "on_update": "NO ACTION",
                    "on_delete": "NO ACTION",
                }
                for child_column, parent_table, parent_column in contracts
            ),
            key=lambda item: (item["from"], item["table"], item["to"]),
        )
        actual = sorted(
            (
                {
                    "table": str(row[2]),
                    "from": str(row[3]),
                    "to": str(row[4]),
                    "on_update": str(row[5]).upper(),
                    "on_delete": str(row[6]).upper(),
                }
                for row in connection.execute(
                    f"PRAGMA foreign_key_list({_quote_identifier(table_name)})"
                )
            ),
            key=lambda item: (item["from"], item["table"], item["to"]),
        )
        if actual != expected:
            errors.append(
                {
                    "kind": "foreign_key",
                    "table": table_name,
                    "expected": expected,
                    "actual": actual,
                }
            )
    return errors


def _inspect_unique_contracts(
    connection: sqlite3.Connection,
    tables: set[str],
    contracts_by_table: dict[str, tuple[tuple[str, ...], ...]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for table_name, contracts in contracts_by_table.items():
        if table_name not in tables:
            continue
        indexes = _index_columns(connection, table_name)
        for expected_columns in contracts:
            expected = {
                "columns": list(expected_columns),
                "unique": True,
                "origin": "u",
                "partial": False,
            }
            candidates = [
                metadata
                for _, metadata in sorted(indexes.items())
                if metadata["columns"] == list(expected_columns)
            ]
            if expected not in candidates:
                errors.append(
                    {
                        "kind": "unique_constraint",
                        "table": table_name,
                        "expected": expected,
                        "actual": candidates,
                    }
                )
    return errors


def _inspect_explicit_index_contracts(
    connection: sqlite3.Connection,
    tables: set[str],
    contracts: dict[str, tuple[str, tuple[str, ...], bool]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    index_cache: dict[str, dict[str, dict[str, Any]]] = {}
    for name, (table_name, expected_columns, unique) in contracts.items():
        if table_name not in tables:
            continue
        if table_name not in index_cache:
            index_cache[table_name] = _index_columns(connection, table_name)
        actual = index_cache[table_name].get(name)
        expected = {
            "columns": list(expected_columns),
            "unique": unique,
            "origin": "c",
            "partial": False,
        }
        if actual != expected:
            errors.append(
                {
                    "kind": "index",
                    "table": table_name,
                    "name": name,
                    "expected": expected,
                    "actual": actual,
                }
            )
    return errors


def _inspect_quality_evidence_schema(
    connection: sqlite3.Connection,
    tables: set[str],
) -> list[dict[str, Any]]:
    errors = _inspect_column_contracts(
        connection,
        tables,
        QUALITY_EVIDENCE_COLUMN_CONTRACTS,
    )
    errors.extend(
        _inspect_primary_key_contracts(
            connection,
            tables,
            QUALITY_EVIDENCE_PRIMARY_KEY_CONTRACTS,
        )
    )
    errors.extend(
        _inspect_check_contracts(
            connection,
            tables,
            QUALITY_EVIDENCE_CHECK_CONTRACTS,
        )
    )
    errors.extend(
        _inspect_foreign_key_contracts(
            connection,
            tables,
            QUALITY_EVIDENCE_FOREIGN_KEY_CONTRACTS,
        )
    )
    errors.extend(
        _inspect_unique_contracts(
            connection,
            tables,
            QUALITY_EVIDENCE_UNIQUE_CONTRACTS,
        )
    )
    errors.extend(
        _inspect_explicit_index_contracts(
            connection,
            tables,
            QUALITY_EVIDENCE_INDEX_CONTRACTS,
        )
    )
    return errors


def _inspect_c1b_schema(
    connection: sqlite3.Connection,
    tables: set[str],
) -> list[dict[str, Any]]:
    errors = _inspect_column_contracts(connection, tables, C1B_COLUMN_CONTRACTS)

    for table_name, expected_columns in C1B_PRIMARY_KEY_CONTRACTS.items():
        if table_name not in tables:
            continue
        primary_key_columns = sorted(
            (
                (int(row[5]), str(row[1]))
                for row in connection.execute(
                    f"PRAGMA table_info({_quote_identifier(table_name)})"
                )
                if int(row[5]) > 0
            ),
            key=lambda item: item[0],
        )
        actual = [column_name for _, column_name in primary_key_columns]
        if actual != list(expected_columns):
            errors.append(
                {
                    "kind": "primary_key",
                    "table": table_name,
                    "expected": list(expected_columns),
                    "actual": actual,
                }
            )

    for table_name, constraints in C1B_CHECK_CONTRACTS.items():
        if table_name not in tables:
            continue
        table_sql = _table_sql(connection, table_name)
        for constraint_name, expected in constraints.items():
            actual_expressions = _named_check_expressions(table_sql, constraint_name)
            matches = (
                len(actual_expressions) == 1
                and _normalized_sql(actual_expressions[0]) == _normalized_sql(expected)
            )
            if not matches:
                actual: str | list[str]
                actual = (
                    actual_expressions[0]
                    if len(actual_expressions) == 1
                    else actual_expressions
                )
                errors.append(
                    {
                        "kind": "check_constraint",
                        "table": table_name,
                        "name": constraint_name,
                        "expected": expected,
                        "actual": actual,
                    }
                )

    if "llm_call_attempts" in tables:
        expected_fk = {
            "table": "llm_calls",
            "from": "llm_call_id",
            "to": "llm_call_id",
            "on_update": "NO ACTION",
            "on_delete": "NO ACTION",
        }
        actual_fks = [
            {
                "table": str(row[2]),
                "from": str(row[3]),
                "to": str(row[4]),
                "on_update": str(row[5]).upper(),
                "on_delete": str(row[6]).upper(),
            }
            for row in connection.execute("PRAGMA foreign_key_list(llm_call_attempts)")
        ]
        if actual_fks != [expected_fk]:
            errors.append(
                {
                    "kind": "foreign_key",
                    "table": "llm_call_attempts",
                    "expected": expected_fk,
                    "actual": actual_fks,
                }
            )

        attempt_indexes = _index_columns(connection, "llm_call_attempts")
        expected_unique = {
            "columns": ["llm_call_id", "provider_attempt_no"],
            "unique": True,
            "origin": "u",
            "partial": False,
        }
        ordinal_candidates = [
            metadata
            for _, metadata in sorted(attempt_indexes.items())
            if metadata["columns"] == expected_unique["columns"]
        ]
        if expected_unique not in ordinal_candidates:
            errors.append(
                {
                    "kind": "unique_constraint",
                    "table": "llm_call_attempts",
                    "expected": expected_unique,
                    "actual": ordinal_candidates,
                }
            )

    errors.extend(
        _inspect_index_contracts(connection, tables, C1B_INDEX_CONTRACTS)
    )
    return errors


def _inspect_revision_schema(
    connection: sqlite3.Connection,
    tables: set[str],
    canonical_revision: str | None,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if _revision_at_least(canonical_revision, C1B_REVISION):
        errors.extend(_inspect_c1b_schema(connection, tables))
    if _revision_at_least(canonical_revision, EVIDENCE_GATE_REVISION):
        errors.extend(
            _inspect_column_contracts(
                connection,
                tables,
                EVIDENCE_GATE_COLUMN_CONTRACTS,
            )
        )
    if _revision_at_least(canonical_revision, PAIR_GENRE_REVISION):
        errors.extend(
            _inspect_column_contracts(
                connection,
                tables,
                PAIR_GENRE_COLUMN_CONTRACTS,
            )
        )
    if _revision_at_least(canonical_revision, NARRATIVE_POSITION_REVISION):
        errors.extend(
            _inspect_index_contracts(
                connection,
                tables,
                NARRATIVE_POSITION_INDEX_CONTRACTS,
            )
        )
    if _revision_at_least(canonical_revision, AUTHOR_CANONICAL_REVISION):
        errors.extend(
            _inspect_column_contracts(
                connection,
                tables,
                AUTHOR_CANONICAL_COLUMN_CONTRACTS,
            )
        )
    if _revision_at_least(canonical_revision, QUALITY_EVIDENCE_REVISION):
        errors.extend(_inspect_quality_evidence_schema(connection, tables))
    return errors


def _schema_profile(
    canonical_revision: str | None,
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    return SCHEMA_PROFILES.get(
        canonical_revision,
        (LEGACY_REQUIRED_TABLES, LEGACY_REQUIRED_COLUMNS),
    )


def _inspect_foreign_key_violations(
    connection: sqlite3.Connection,
    *,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Inspect every declared FK even when SQLite enforcement is disabled."""

    by_child_table: dict[str, int] = {}
    by_parent_table: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    count = 0
    for row in connection.execute("PRAGMA foreign_key_check"):
        count += 1
        child_table = str(row[0])
        parent_table = str(row[2])
        by_child_table[child_table] = by_child_table.get(child_table, 0) + 1
        by_parent_table[parent_table] = by_parent_table.get(parent_table, 0) + 1
        if len(samples) < sample_limit:
            samples.append(
                {
                    "child_table": child_table,
                    "rowid": row[1],
                    "parent_table": parent_table,
                    "foreign_key_index": int(row[3]),
                }
            )
    return {
        "count": count,
        "by_child_table": dict(sorted(by_child_table.items())),
        "by_parent_table": dict(sorted(by_parent_table.items())),
        "samples": samples,
        "samples_truncated": count > sample_limit,
    }


def inspect_database(
    path: str | os.PathLike[str],
    expected_revision: str,
    orphan_evidence_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    database_path = Path(path).expanduser().resolve()
    canonical_revision = REVISION_ALIASES.get(expected_revision)
    runtime_foreign_key_policy = _sqlite_runtime_foreign_key_policy()
    result: dict[str, Any] = {
        "path": str(database_path),
        "ready": False,
        "integrity": None,
        "revision": None,
        "expected_revision": expected_revision,
        "expected_revision_canonical": canonical_revision,
        "foreign_keys": None,
        "runtime_foreign_key_policy": runtime_foreign_key_policy,
        "missing_tables": [],
        "missing_columns": {},
        "schema_errors": [],
        "orphan_integrity": None,
    }
    if canonical_revision is None:
        result["error"] = f"unsupported_expected_revision={expected_revision}"
    if not runtime_foreign_key_policy["valid"] and "error" not in result:
        result["error"] = "sqlite_foreign_key_runtime_policy_invalid"
    elif not runtime_foreign_key_policy["enabled"] and "error" not in result:
        result["error"] = "sqlite_foreign_key_runtime_policy_disabled"
    required_tables, required_columns = _schema_profile(canonical_revision)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
        # This is a connection-local runtime safety property, not a database
        # file mutation.  A preflight that merely observes SQLite's default
        # OFF value can otherwise report ready=true for a connection that will
        # not enforce the schema's declared foreign keys.
        connection.execute("PRAGMA foreign_keys=ON")
        foreign_keys_row = connection.execute("PRAGMA foreign_keys").fetchone()
        foreign_keys = int(foreign_keys_row[0]) if foreign_keys_row else 0
        result["foreign_keys"] = foreign_keys
        if foreign_keys != 1 and "error" not in result:
            result["error"] = "foreign_keys_not_enabled"
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row else "unknown"
        result["integrity"] = integrity
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        if "alembic_version" in tables:
            revision_rows = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchall()
            if len(revision_rows) == 1:
                result["revision"] = str(revision_rows[0][0])
            elif "error" not in result:
                result["error"] = f"alembic_version_row_count={len(revision_rows)}"

        missing_tables = sorted(set(required_tables) - tables)
        result["missing_tables"] = missing_tables
        missing_columns: dict[str, list[str]] = {}
        for table, table_required_columns in required_columns.items():
            if table not in tables:
                continue
            columns = {
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            missing = sorted(set(table_required_columns) - columns)
            if missing:
                missing_columns[table] = missing
        result["missing_columns"] = missing_columns
        schema_errors = _inspect_revision_schema(
            connection,
            tables,
            canonical_revision,
        )
        result["schema_errors"] = schema_errors

        orphan_scan = scan_orphans(connection)
        blocking_missing_dependencies = dict(orphan_scan["missing_dependencies"])
        # llm_call_attempts was introduced by 0065.  Its absence is expected
        # when explicitly validating the supported 0064 profile; every other
        # missing scanner dependency means the audit was incomplete.
        if not _revision_at_least(canonical_revision, C1B_REVISION):
            blocking_missing_dependencies.pop("llm_call_attempts", None)
        orphan_counts = orphan_scan["counts_by_table"]
        attempt_orphan_count: int | None = None
        snowflake_orphan_count: int | None = None
        if "llm_call_attempts" not in orphan_scan["missing_dependencies"]:
            attempt_orphan_count = int(orphan_counts["llm_call_attempts"])
            result["llm_call_attempt_orphan_count"] = attempt_orphan_count
        if "snowflake_revision_links" not in orphan_scan["missing_dependencies"]:
            snowflake_orphan_count = int(orphan_counts["snowflake_revision_links"])
            result["snowflake_revision_link_orphan_count"] = snowflake_orphan_count

        active_orphan_count = int(orphan_scan["record_count"])
        orphan_integrity: dict[str, Any] = {
            "status": "unhandled" if active_orphan_count else "clean",
            "active_record_count": active_orphan_count,
            "active_counts_by_table": orphan_counts,
            "active_counts_by_reason": orphan_scan["counts_by_reason"],
            "missing_dependencies": orphan_scan["missing_dependencies"],
            "blocking_missing_dependencies": blocking_missing_dependencies,
            "evidence": None,
        }
        evidence_valid = True
        if orphan_evidence_path is not None:
            try:
                evidence = load_evidence(orphan_evidence_path)
                assessment = assess_evidence(
                    connection,
                    evidence,
                    database_path=database_path,
                )
                orphan_integrity["status"] = assessment["status"]
                orphan_integrity["evidence"] = assessment
                evidence_valid = assessment["status"] not in {
                    "database_path_mismatch",
                    "evidence_mismatch",
                }
            except (OSError, EvidenceValidationError) as exc:
                evidence_valid = False
                orphan_integrity["status"] = "evidence_invalid"
                orphan_integrity["evidence"] = {
                    "path": str(Path(orphan_evidence_path).expanduser().resolve()),
                    "valid": False,
                    "error": str(exc),
                }
        result["orphan_integrity"] = orphan_integrity

        foreign_key_violations = _inspect_foreign_key_violations(connection)
        foreign_key_violation_count = int(foreign_key_violations["count"])
        result["foreign_key_violations"] = foreign_key_violations
        orphan_integrity["foreign_key_violations"] = foreign_key_violations

        if active_orphan_count and "error" not in result:
            if attempt_orphan_count and not snowflake_orphan_count:
                result["error"] = f"llm_call_attempt_orphans={attempt_orphan_count}"
            elif snowflake_orphan_count and not attempt_orphan_count:
                result["error"] = (
                    f"snowflake_revision_link_orphans={snowflake_orphan_count}"
                )
            else:
                result["error"] = f"active_orphans={active_orphan_count}"
        if blocking_missing_dependencies and "error" not in result:
            missing_relations = ",".join(sorted(blocking_missing_dependencies))
            result["error"] = f"orphan_scan_missing_dependencies={missing_relations}"
        if (
            orphan_evidence_path is not None
            and not evidence_valid
            and "error" not in result
        ):
            result["error"] = "orphan_evidence_invalid"
        if foreign_key_violation_count and "error" not in result:
            result["error"] = f"foreign_key_violations={foreign_key_violation_count}"

        # Verify the setting again after all read-only checks; readiness is
        # explicitly bound to this connection still enforcing foreign keys.
        foreign_keys_row = connection.execute("PRAGMA foreign_keys").fetchone()
        foreign_keys = int(foreign_keys_row[0]) if foreign_keys_row else 0
        result["foreign_keys"] = foreign_keys
        if foreign_keys != 1 and "error" not in result:
            result["error"] = "foreign_keys_not_enabled"
        result["ready"] = (
            integrity == "ok"
            and canonical_revision is not None
            and result["revision"] == canonical_revision
            and not missing_tables
            and not missing_columns
            and not schema_errors
            and not blocking_missing_dependencies
            and active_orphan_count == 0
            and foreign_key_violation_count == 0
            and foreign_keys == 1
            and runtime_foreign_key_policy["valid"]
            and runtime_foreign_key_policy["enabled"]
            and evidence_valid
            and "error" not in result
        )
    except sqlite3.Error as exc:
        result["error"] = str(exc)
    finally:
        if connection is not None:
            connection.close()
    return result


def _write_json_atomic(path: str | os.PathLike[str], payload: str) -> None:
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.parent / (
        f".{output_path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    )
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 SQLite 数据库是否已可供运行")
    parser.add_argument("path")
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument(
        "--orphan-evidence",
        help="可选：验证 orphan_quarantine 导出的 JSONL 证据及其处置状态",
    )
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    result = inspect_database(
        args.path,
        args.expected_revision,
        orphan_evidence_path=args.orphan_evidence,
    )
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        _write_json_atomic(args.output, payload)
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
