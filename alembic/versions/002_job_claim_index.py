"""Add index on job(state, scheduled_at) for FOR UPDATE SKIP LOCKED claims.

Revision ID: 002
Revises: 001
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_job_claimable",
        "job",
        ["state", "scheduled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_claimable", table_name="job")
