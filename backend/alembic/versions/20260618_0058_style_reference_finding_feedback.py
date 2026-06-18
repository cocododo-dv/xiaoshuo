"""style reference finding feedback: 立项 B 持续校准回路

新增 style_reference_finding_feedback 表(finding 用户 👍/👎,一人一票 uq)
与 style_reference_findings.base_confidence 列(合成基线,使反馈调档可逆)。

Revision ID: 20260618_0058
Revises: 20260617_0057
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "20260618_0058"
down_revision = "20260617_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- style_reference_findings: base_confidence(合成基线,反馈调档可逆) ---
    if inspector.has_table("style_reference_findings"):
        cols = {col["name"] for col in inspector.get_columns("style_reference_findings")}
        if "base_confidence" not in cols:
            op.add_column(
                "style_reference_findings",
                sa.Column("base_confidence", sa.String(), nullable=True),
            )

    # --- style_reference_finding_feedback: 一人一票反馈表 ---
    if "style_reference_finding_feedback" not in set(inspector.get_table_names()):
        op.create_table(
            "style_reference_finding_feedback",
            sa.Column("feedback_id", sa.String(), nullable=False),
            sa.Column("finding_id", sa.String(), nullable=False),
            sa.Column("operator_ref", sa.String(), nullable=False),
            sa.Column("vote", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(
                ["finding_id"], ["style_reference_findings.finding_id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("feedback_id"),
            sa.UniqueConstraint(
                "finding_id",
                "operator_ref",
                name="uq_style_reference_finding_feedback_finding_operator",
            ),
        )
        op.create_index(
            "ix_sr_finding_feedback_finding",
            "style_reference_finding_feedback",
            ["finding_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "style_reference_finding_feedback" in set(inspector.get_table_names()):
        try:
            op.drop_index(
                "ix_sr_finding_feedback_finding",
                "style_reference_finding_feedback",
            )
        except Exception:
            pass
        op.drop_table("style_reference_finding_feedback")
    if inspector.has_table("style_reference_findings"):
        cols = {col["name"] for col in inspector.get_columns("style_reference_findings")}
        if "base_confidence" in cols:
            op.drop_column("style_reference_findings", "base_confidence")
