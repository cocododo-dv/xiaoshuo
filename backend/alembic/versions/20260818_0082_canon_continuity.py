"""Add accepted-canon continuity commit pipeline.

Revision ID: 20260818_0082
Revises: 20260805_0081
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260818_0082"
down_revision = "20260805_0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canon_commits",
        sa.Column("commit_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=False),
        sa.Column("final_scene_row_id", sa.String(), nullable=False),
        sa.Column("final_content_hash", sa.String(), nullable=False),
        sa.Column("commit_kind", sa.String(), nullable=False, server_default="candidate_acceptance"),
        sa.Column("candidate_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_final_scene_row_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("actor_ref", sa.String(), nullable=False, server_default="operator"),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active','superseded')",
            name="ck_canon_commits_status",
        ),
        sa.CheckConstraint(
            "commit_kind IN "
            "('candidate_acceptance','author_verification','facts_unchanged')",
            name="ck_canon_commits_commit_kind",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["story_projects.project_id"]),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapter_goals.chapter_id"]),
        sa.ForeignKeyConstraint(["scene_id"], ["scene_cards.scene_id"]),
        sa.ForeignKeyConstraint(["final_scene_row_id"], ["final_scenes.row_id"]),
        sa.ForeignKeyConstraint(["source_final_scene_row_id"], ["final_scenes.row_id"]),
        sa.PrimaryKeyConstraint("commit_id"),
    )
    op.create_index(
        "ix_canon_commits_project_scene_final",
        "canon_commits",
        ["project_id", "scene_id", "final_scene_row_id"],
        unique=False,
    )
    op.create_index(
        "ix_canon_commits_chapter",
        "canon_commits",
        ["chapter_id"],
        unique=False,
    )
    op.create_index("ix_canon_commits_scene", "canon_commits", ["scene_id"], unique=False)
    op.create_index(
        "ix_canon_commits_final_scene",
        "canon_commits",
        ["final_scene_row_id"],
        unique=False,
    )
    op.create_index(
        "ix_canon_commits_source_final_scene",
        "canon_commits",
        ["source_final_scene_row_id"],
        unique=False,
    )

    with op.batch_alter_table("timeline_events") as batch_op:
        batch_op.add_column(
            sa.Column("event_mode", sa.String(), nullable=False, server_default="planned")
        )
        batch_op.add_column(
            sa.Column(
                "realization_status",
                sa.String(),
                nullable=False,
                server_default="planned",
            )
        )
        batch_op.add_column(sa.Column("realized_canon_commit_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("realized_scene_id", sa.String(), nullable=True))
        batch_op.create_check_constraint(
            "ck_timeline_events_event_mode",
            "event_mode IN ('planned','recorded')",
        )
        batch_op.create_check_constraint(
            "ck_timeline_events_realization_status",
            "realization_status IN ('planned','realized')",
        )
        batch_op.create_foreign_key(
            "fk_timeline_events_realized_canon_commit_id",
            "canon_commits",
            ["realized_canon_commit_id"],
            ["commit_id"],
        )
        batch_op.create_foreign_key(
            "fk_timeline_events_realized_scene_id",
            "scene_cards",
            ["realized_scene_id"],
            ["scene_id"],
        )
    op.create_index(
        "ix_timeline_events_realized_canon_commit_id",
        "timeline_events",
        ["realized_canon_commit_id"],
        unique=False,
    )
    op.create_index(
        "ix_timeline_events_realized_scene_id",
        "timeline_events",
        ["realized_scene_id"],
        unique=False,
    )

    with op.batch_alter_table("narrative_events") as batch_op:
        batch_op.add_column(
            sa.Column(
                "authority_status",
                sa.String(),
                nullable=False,
                server_default="planned",
            )
        )
        batch_op.add_column(
            sa.Column(
                "source_kind",
                sa.String(),
                nullable=False,
                server_default="legacy_plan",
            )
        )
        batch_op.add_column(sa.Column("final_scene_row_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("canon_commit_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_narrative_events_final_scene_row_id",
            "final_scenes",
            ["final_scene_row_id"],
            ["row_id"],
        )
        batch_op.create_foreign_key(
            "fk_narrative_events_canon_commit_id",
            "canon_commits",
            ["canon_commit_id"],
            ["commit_id"],
        )
        batch_op.create_check_constraint(
            "ck_narrative_events_authority_status",
            "authority_status IN ('accepted','pending','rejected','planned','superseded')",
        )
    # Revision 0081 had no way to distinguish plan-derived events from facts
    # grounded in an accepted final scene. Fail closed: legacy events and all
    # unspecified future writes are planned, while detectable prose extraction
    # rows remain pending until an author reviews current-final evidence through
    # the new candidate ledger.
    op.execute(
        sa.text(
            "UPDATE narrative_events "
            "SET authority_status = 'planned', source_kind = 'legacy_plan'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE narrative_events "
            "SET authority_status = 'pending', source_kind = 'prose_extraction' "
            "WHERE LOWER(CAST(payload_json AS VARCHAR)) LIKE "
            "'%\"source\": \"prose\"%' "
            "OR LOWER(CAST(payload_json AS VARCHAR)) LIKE "
            "'%\"source\":\"prose\"%'"
        )
    )
    op.create_index(
        "ix_narrative_events_authority_project_scene",
        "narrative_events",
        ["authority_status", "project_id", "scene_id"],
        unique=False,
    )
    op.create_index(
        "ix_narrative_events_final_scene",
        "narrative_events",
        ["final_scene_row_id"],
        unique=False,
    )
    op.create_index(
        "ix_narrative_events_canon_commit",
        "narrative_events",
        ["canon_commit_id"],
        unique=False,
    )

    op.create_table(
        "fact_candidates",
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=False),
        sa.Column("final_scene_row_id", sa.String(), nullable=False),
        sa.Column("staged_event_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("raw_entity_ref", sa.String(), nullable=False),
        sa.Column("resolved_entity_id", sa.String(), nullable=True),
        sa.Column(
            "entity_resolution_status",
            sa.String(),
            nullable=False,
            server_default="unresolved",
        ),
        sa.Column("entity_candidates_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("fact_key", sa.String(), nullable=False),
        sa.Column("fact_value", sa.Text(), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("evidence_start", sa.Integer(), nullable=True),
        sa.Column("evidence_end", sa.Integer(), nullable=True),
        sa.Column(
            "source_kind",
            sa.String(),
            nullable=False,
            server_default="prose_extraction",
        ),
        sa.Column("confidence", sa.String(), nullable=False, server_default="extracted"),
        sa.Column("criticality", sa.String(), nullable=False, server_default="critical"),
        sa.Column("planned_timeline_event_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("canon_commit_id", sa.String(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("decided_at", sa.String(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','accepted','rejected','superseded')",
            name="ck_fact_candidates_status",
        ),
        sa.CheckConstraint(
            "entity_resolution_status IN ('exact','alias','ambiguous','unresolved','manual')",
            name="ck_fact_candidates_entity_resolution_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["story_projects.project_id"]),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapter_goals.chapter_id"]),
        sa.ForeignKeyConstraint(["scene_id"], ["scene_cards.scene_id"]),
        sa.ForeignKeyConstraint(["final_scene_row_id"], ["final_scenes.row_id"]),
        sa.ForeignKeyConstraint(["staged_event_id"], ["narrative_events.event_id"]),
        sa.ForeignKeyConstraint(["planned_timeline_event_id"], ["timeline_events.event_id"]),
        sa.ForeignKeyConstraint(["canon_commit_id"], ["canon_commits.commit_id"]),
        sa.PrimaryKeyConstraint("candidate_id"),
        sa.UniqueConstraint("staged_event_id", name="ux_fact_candidates_staged_event"),
    )
    op.create_index(
        "ix_fact_candidates_project_chapter_status",
        "fact_candidates",
        ["project_id", "chapter_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_fact_candidates_scene_status",
        "fact_candidates",
        ["scene_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_fact_candidates_final_scene",
        "fact_candidates",
        ["final_scene_row_id"],
        unique=False,
    )
    op.create_index(
        "ix_fact_candidates_chapter",
        "fact_candidates",
        ["chapter_id"],
        unique=False,
    )
    op.create_index(
        "ix_fact_candidates_planned_timeline",
        "fact_candidates",
        ["planned_timeline_event_id"],
        unique=False,
    )
    op.create_index(
        "ix_fact_candidates_canon_commit",
        "fact_candidates",
        ["canon_commit_id"],
        unique=False,
    )

    op.create_table(
        "continuity_snapshots",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("scope_type", sa.String(), nullable=False),
        sa.Column("scope_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=True),
        sa.Column("final_scene_row_id", sa.String(), nullable=True),
        sa.Column("latest_commit_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("summary_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("state_deltas_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("knowledge_deltas_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("relationship_deltas_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("item_deltas_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("timeline_deltas_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("open_obligations_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("entity_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_commit_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('scene','chapter')",
            name="ck_continuity_snapshots_scope_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','complete','degraded','superseded')",
            name="ck_continuity_snapshots_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["story_projects.project_id"]),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapter_goals.chapter_id"]),
        sa.ForeignKeyConstraint(["scene_id"], ["scene_cards.scene_id"]),
        sa.ForeignKeyConstraint(["final_scene_row_id"], ["final_scenes.row_id"]),
        sa.ForeignKeyConstraint(["latest_commit_id"], ["canon_commits.commit_id"]),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.UniqueConstraint(
            "project_id",
            "scope_type",
            "scope_id",
            name="ux_continuity_snapshots_scope",
        ),
    )
    op.create_index(
        "ix_continuity_snapshots_chapter",
        "continuity_snapshots",
        ["chapter_id", "scope_type"],
        unique=False,
    )
    op.create_index(
        "ix_continuity_snapshots_scene",
        "continuity_snapshots",
        ["scene_id"],
        unique=False,
    )
    op.create_index(
        "ix_continuity_snapshots_final_scene",
        "continuity_snapshots",
        ["final_scene_row_id"],
        unique=False,
    )
    op.create_index(
        "ix_continuity_snapshots_latest_commit",
        "continuity_snapshots",
        ["latest_commit_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_continuity_snapshots_latest_commit", table_name="continuity_snapshots")
    op.drop_index("ix_continuity_snapshots_final_scene", table_name="continuity_snapshots")
    op.drop_index("ix_continuity_snapshots_scene", table_name="continuity_snapshots")
    op.drop_index("ix_continuity_snapshots_chapter", table_name="continuity_snapshots")
    op.drop_table("continuity_snapshots")

    op.drop_index("ix_fact_candidates_canon_commit", table_name="fact_candidates")
    op.drop_index("ix_fact_candidates_planned_timeline", table_name="fact_candidates")
    op.drop_index("ix_fact_candidates_chapter", table_name="fact_candidates")
    op.drop_index("ix_fact_candidates_final_scene", table_name="fact_candidates")
    op.drop_index("ix_fact_candidates_scene_status", table_name="fact_candidates")
    op.drop_index("ix_fact_candidates_project_chapter_status", table_name="fact_candidates")
    op.drop_table("fact_candidates")

    op.drop_index("ix_narrative_events_canon_commit", table_name="narrative_events")
    op.drop_index("ix_narrative_events_final_scene", table_name="narrative_events")
    op.drop_index("ix_narrative_events_authority_project_scene", table_name="narrative_events")
    with op.batch_alter_table("narrative_events") as batch_op:
        batch_op.drop_constraint("fk_narrative_events_canon_commit_id", type_="foreignkey")
        batch_op.drop_constraint("fk_narrative_events_final_scene_row_id", type_="foreignkey")
        batch_op.drop_constraint("ck_narrative_events_authority_status", type_="check")
        batch_op.drop_column("canon_commit_id")
        batch_op.drop_column("final_scene_row_id")
        batch_op.drop_column("source_kind")
        batch_op.drop_column("authority_status")

    op.drop_index("ix_timeline_events_realized_scene_id", table_name="timeline_events")
    op.drop_index(
        "ix_timeline_events_realized_canon_commit_id", table_name="timeline_events"
    )
    with op.batch_alter_table("timeline_events") as batch_op:
        batch_op.drop_constraint("fk_timeline_events_realized_scene_id", type_="foreignkey")
        batch_op.drop_constraint(
            "fk_timeline_events_realized_canon_commit_id", type_="foreignkey"
        )
        batch_op.drop_constraint("ck_timeline_events_realization_status", type_="check")
        batch_op.drop_constraint("ck_timeline_events_event_mode", type_="check")
        batch_op.drop_column("realized_scene_id")
        batch_op.drop_column("realized_canon_commit_id")
        batch_op.drop_column("realization_status")
        batch_op.drop_column("event_mode")

    op.drop_index("ix_canon_commits_source_final_scene", table_name="canon_commits")
    op.drop_index("ix_canon_commits_final_scene", table_name="canon_commits")
    op.drop_index("ix_canon_commits_scene", table_name="canon_commits")
    op.drop_index("ix_canon_commits_chapter", table_name="canon_commits")
    op.drop_index("ix_canon_commits_project_scene_final", table_name="canon_commits")
    op.drop_table("canon_commits")
