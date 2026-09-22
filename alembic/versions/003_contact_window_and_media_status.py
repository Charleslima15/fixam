"""Add contact_window table and media status/media_id columns.

Revision ID: 003
Revises: 002
"""
import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # contact_window table for 24-hour window tracking (FR-OUT-02)
    op.create_table(
        "contact_window",
        sa.Column("phone_hash", sa.String(), nullable=False),
        sa.Column(
            "last_inbound_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("phone_hash"),
    )

    # media_status enum
    media_status = sa.Enum("pending", "stored", "failed", name="media_status")
    media_status.create(op.get_bind(), checkfirst=True)

    # Add status column to media
    op.add_column(
        "media",
        sa.Column(
            "status",
            sa.Enum("pending", "stored", "failed", name="media_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
    )

    # Add media_id column to media (Meta's media ID for download)
    op.add_column(
        "media",
        sa.Column("media_id", sa.String(), nullable=True),
    )

    # Make storage_key nullable (not set until download completes)
    op.alter_column("media", "storage_key", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.alter_column("media", "storage_key", existing_type=sa.String(), nullable=False)
    op.drop_column("media", "media_id")
    op.drop_column("media", "status")
    sa.Enum(name="media_status").drop(op.get_bind(), checkfirst=True)
    op.drop_table("contact_window")
