"""Seed payment and free-credit config rows.

Revision ID: 006
Revises: 005
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

CONFIG_ROWS = [
    ("bundle_default", '{"credits": 10, "price_fcfa": 5000}', "Default credit bundle"),
    ("bundle_first_purchase", '{"credits": 3, "price_fcfa": 1500, "first_purchase_only": true}', "First-purchase-only bundle (FR-PAY-01)"),
    ("free_credit_cap", "5", "Free credits granted on activation (FR-FRE-01)"),
    ("payment_poll_after_seconds", "120", "Poll MTN after this many seconds without callback"),
    ("payment_stuck_after_seconds", "900", "Mark payment stuck after this many seconds"),
    ("low_balance_threshold", "1", "Send low-balance warning at this balance (FR-PRV-04)"),
]


def upgrade() -> None:
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
    op.execute(
        "DELETE FROM config WHERE key IN ("
        + ",".join(f"'{r[0]}'" for r in CONFIG_ROWS)
        + ")"
    )
