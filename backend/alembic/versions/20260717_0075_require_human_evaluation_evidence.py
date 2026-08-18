"""Require real human evidence for production evaluation experiments.

Revision ID: 20260717_0075
Revises: 20260717_0074
Create Date: 2026-07-17

Non-human experiment rows and their ballots cannot be converted into human
evidence.  They are deleted, while any strategy policy that referenced them is
retired and detached.  The database then enforces the human-only contract.
"""

from __future__ import annotations

import json
import re
from typing import Any

import sqlalchemy as sa
from alembic import op


revision = "20260717_0075"
down_revision = "20260717_0074"
branch_labels = None
depends_on = None


_HUMAN_PROVENANCE_CHECK = "ck_evaluation_experiments_human_provenance"
_HUMAN_PROVENANCE_EXPRESSION = "evidence_provenance = 'human'"
_PAIR_EXPERIMENT_FK = "fk_evaluation_pairs_experiment_id"
_VOTE_PAIR_FK = "fk_evaluation_votes_pair_id"


def _normalized_sql(value: object) -> str:
    return re.sub(r'[\s"`\[\]\(\)]', "", str(value or "")).lower()


def _has_foreign_key(
    inspector: sa.Inspector,
    table_name: str,
    *,
    local_column: str,
    referred_table: str,
    referred_column: str,
) -> bool:
    return any(
        tuple(foreign_key.get("constrained_columns") or ()) == (local_column,)
        and str(foreign_key.get("referred_table") or "") == referred_table
        and tuple(foreign_key.get("referred_columns") or ())
        == (referred_column,)
        for foreign_key in inspector.get_foreign_keys(table_name)
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _evaluation_identity_references(
    value: Any,
) -> tuple[set[str], set[str], set[str]]:
    value = _json_value(value)
    experiment_ids: set[str] = set()
    pair_ids: set[str] = set()
    vote_ids: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key)
            normalized_value = str(item) if isinstance(item, str) else None
            if normalized_value is not None:
                if normalized_key == "experiment_id":
                    experiment_ids.add(normalized_value)
                elif normalized_key == "pair_id":
                    pair_ids.add(normalized_value)
                elif normalized_key == "vote_id":
                    vote_ids.add(normalized_value)
            child_experiments, child_pairs, child_votes = (
                _evaluation_identity_references(item)
            )
            experiment_ids.update(child_experiments)
            pair_ids.update(child_pairs)
            vote_ids.update(child_votes)
    elif isinstance(value, list):
        for item in value:
            child_experiments, child_pairs, child_votes = (
                _evaluation_identity_references(item)
            )
            experiment_ids.update(child_experiments)
            pair_ids.update(child_pairs)
            vote_ids.update(child_votes)
    return experiment_ids, pair_ids, vote_ids


def _ensure_idempotency_table(inspector: sa.Inspector) -> None:
    """Repair historical Alembic-only databases before scrubbing cached receipts.

    The original bootstrap migration used ``Base.metadata.create_all``.  A
    database first created by an old checkout can therefore legitimately reach
    this revision without the later ``idempotency_keys`` model table.  There are
    no receipts to preserve when the table is absent, so creating the current
    durable lease shape is the only lossless repair.
    """

    if "idempotency_keys" in inspector.get_table_names():
        return
    op.create_table(
        "idempotency_keys",
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="started"),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("heartbeat_at", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.String(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.String(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _ensure_idempotency_table(inspector)
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required_tables = {
        "evaluation_experiments",
        "evaluation_pairs",
        "evaluation_votes",
        "quality_strategy_policies",
        "idempotency_keys",
    }
    missing_tables = sorted(required_tables - tables)
    if missing_tables:
        raise RuntimeError(
            "cannot enforce the real-only evidence contract; missing tables: "
            + ", ".join(missing_tables)
        )
    required_columns = {
        "evaluation_experiments": {"experiment_id", "evidence_provenance"},
        "evaluation_pairs": {"pair_id", "experiment_id"},
        "evaluation_votes": {"vote_id", "pair_id"},
        "quality_strategy_policies": {
            "evidence_experiment_id",
            "status",
            "updated_at",
        },
        "idempotency_keys": {"idempotency_key", "response_json"},
    }
    missing_columns = {
        table_name: sorted(
            column_names
            - {
                str(column["name"])
                for column in inspector.get_columns(table_name)
            }
        )
        for table_name, column_names in required_columns.items()
    }
    missing_columns = {
        table_name: column_names
        for table_name, column_names in missing_columns.items()
        if column_names
    }
    if missing_columns:
        raise RuntimeError(
            "cannot enforce the real-only evidence contract; missing columns: "
            + "; ".join(
                f"{table_name}={','.join(column_names)}"
                for table_name, column_names in sorted(missing_columns.items())
            )
        )

    valid_experiment_ids = {
        str(value)
        for value in bind.execute(
            sa.text(
                "SELECT experiment_id FROM evaluation_experiments "
                "WHERE evidence_provenance = 'human'"
            )
        ).scalars()
    }
    valid_pair_ids = {
        str(value)
        for value in bind.execute(
            sa.text(
                "SELECT evidence_pair.pair_id "
                "FROM evaluation_pairs AS evidence_pair "
                "JOIN evaluation_experiments AS evidence_exp "
                "ON evidence_exp.experiment_id = evidence_pair.experiment_id "
                "WHERE evidence_exp.evidence_provenance = 'human'"
            )
        ).scalars()
    }
    valid_vote_ids = {
        str(value)
        for value in bind.execute(
            sa.text(
                "SELECT evidence_vote.vote_id "
                "FROM evaluation_votes AS evidence_vote "
                "JOIN evaluation_pairs AS evidence_pair "
                "ON evidence_pair.pair_id = evidence_vote.pair_id "
                "JOIN evaluation_experiments AS evidence_exp "
                "ON evidence_exp.experiment_id = evidence_pair.experiment_id "
                "WHERE evidence_exp.evidence_provenance = 'human'"
            )
        ).scalars()
    }
    idempotency_rows = bind.execute(
        sa.text(
            "SELECT idempotency_key, response_json FROM idempotency_keys "
            "WHERE response_json IS NOT NULL"
        )
    ).mappings().all()
    for row in idempotency_rows:
        experiment_refs, pair_refs, vote_refs = _evaluation_identity_references(
            row["response_json"]
        )
        stale = (
            not experiment_refs.issubset(valid_experiment_ids)
            or not pair_refs.issubset(valid_pair_ids)
            or not vote_refs.issubset(valid_vote_ids)
        )
        if stale:
            bind.execute(
                sa.text(
                    "DELETE FROM idempotency_keys "
                    "WHERE idempotency_key = :idempotency_key"
                ),
                {"idempotency_key": row["idempotency_key"]},
            )

    bind.execute(
        sa.text(
            "UPDATE quality_strategy_policies "
            "SET status = 'retired', evidence_experiment_id = NULL, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE evidence_experiment_id IS NOT NULL AND NOT EXISTS ("
            "SELECT 1 FROM evaluation_experiments AS evidence_exp "
            "WHERE evidence_exp.experiment_id = "
            "quality_strategy_policies.evidence_experiment_id "
            "AND evidence_exp.evidence_provenance = 'human')"
        )
    )
    bind.execute(
        sa.text(
            "DELETE FROM evaluation_votes WHERE NOT EXISTS ("
            "SELECT 1 FROM evaluation_pairs AS evidence_pair "
            "JOIN evaluation_experiments AS evidence_exp "
            "ON evidence_exp.experiment_id = evidence_pair.experiment_id "
            "WHERE evidence_pair.pair_id = evaluation_votes.pair_id "
            "AND evidence_exp.evidence_provenance = 'human')"
        )
    )
    bind.execute(
        sa.text(
            "DELETE FROM evaluation_pairs WHERE NOT EXISTS ("
            "SELECT 1 FROM evaluation_experiments AS evidence_exp "
            "WHERE evidence_exp.experiment_id = "
            "evaluation_pairs.experiment_id "
            "AND evidence_exp.evidence_provenance = 'human')"
        )
    )
    bind.execute(
        sa.text(
            "DELETE FROM evaluation_experiments "
            "WHERE COALESCE(evidence_provenance, '') <> 'human'"
        )
    )

    inspector = sa.inspect(bind)
    if not _has_foreign_key(
        inspector,
        "evaluation_pairs",
        local_column="experiment_id",
        referred_table="evaluation_experiments",
        referred_column="experiment_id",
    ):
        with op.batch_alter_table("evaluation_pairs") as batch_op:
            batch_op.create_foreign_key(
                _PAIR_EXPERIMENT_FK,
                "evaluation_experiments",
                ["experiment_id"],
                ["experiment_id"],
            )

    inspector = sa.inspect(bind)
    if not _has_foreign_key(
        inspector,
        "evaluation_votes",
        local_column="pair_id",
        referred_table="evaluation_pairs",
        referred_column="pair_id",
    ):
        with op.batch_alter_table("evaluation_votes") as batch_op:
            batch_op.create_foreign_key(
                _VOTE_PAIR_FK,
                "evaluation_pairs",
                ["pair_id"],
                ["pair_id"],
            )

    inspector = sa.inspect(bind)
    check_constraints = {
        str(check.get("name") or ""): str(check.get("sqltext") or "")
        for check in inspector.get_check_constraints("evaluation_experiments")
    }
    existing_check_sql = check_constraints.get(_HUMAN_PROVENANCE_CHECK)
    check_is_exact = (
        existing_check_sql is not None
        and _normalized_sql(existing_check_sql)
        == _normalized_sql(_HUMAN_PROVENANCE_EXPRESSION)
    )
    provenance_column = next(
        column
        for column in inspector.get_columns("evaluation_experiments")
        if column["name"] == "evidence_provenance"
    )
    default_sql = str(provenance_column.get("default") or "").strip("'\"").lower()
    provenance_is_nullable = bool(provenance_column.get("nullable", True))
    if check_is_exact and default_sql == "human" and not provenance_is_nullable:
        return
    with op.batch_alter_table("evaluation_experiments") as batch_op:
        if default_sql != "human" or provenance_is_nullable:
            batch_op.alter_column(
                "evidence_provenance",
                existing_type=sa.String(),
                existing_nullable=provenance_is_nullable,
                nullable=False,
                server_default="human",
            )
        if existing_check_sql is not None and not check_is_exact:
            batch_op.drop_constraint(
                _HUMAN_PROVENANCE_CHECK,
                type_="check",
            )
        if not check_is_exact:
            batch_op.create_check_constraint(
                _HUMAN_PROVENANCE_CHECK,
                _HUMAN_PROVENANCE_EXPRESSION,
            )


def downgrade() -> None:
    raise RuntimeError(
        "20260717_0075 is intentionally irreversible: retired non-human "
        "evaluation evidence must not be restored"
    )

