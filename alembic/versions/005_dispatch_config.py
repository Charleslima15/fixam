"""Add dispatch config and provider.consecutive_unanswered.

Revision ID: 005
Revises: 004
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

CONFIG_ROWS = [
    ("wave_sizes", "2,3,0", "Wave sizes per wave number; 0 = all remaining"),
    ("wave_sizes_now", "3,5,0", "Wave sizes for urgency=now"),
    ("wave_sizes_established", "2,3,0", "Wave sizes for established-tier customers"),
    ("wave_timeout_seconds", "300", "Seconds before advancing to next wave"),
    ("wave_timeout_seconds_now", "180", "Wave timeout for urgency=now"),
    ("cold_start_offer_cap", "3", "Force-include providers with fewer than N total offers in wave 1"),
    ("auto_off_threshold", "3", "Set provider OFF after N consecutive unanswered offers"),
]


def upgrade() -> None:
    op.add_column(
        "provider",
        sa.Column(
            "consecutive_unanswered",
            sa.SmallInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    config = sa.table(
        "config",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(config, [
        {"key": k, "value": v, "description": d} for k, v, d in CONFIG_ROWS
    ])


def downgrade() -> None:
    op.drop_column("provider", "consecutive_unanswered")
    op.execute(
        "DELETE FROM config WHERE key IN ("
        + ",".join(f"'{r[0]}'" for r in CONFIG_ROWS)
        + ")"
    )
