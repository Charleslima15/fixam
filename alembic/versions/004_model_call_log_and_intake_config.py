"""model_call_log table and intake config seeds

Revision ID: 004
Revises: 003
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_call_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("phone_hash", sa.String(), nullable=False, index=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("service_request.id"), nullable=True),
        sa.Column("input_size", sa.Integer(), nullable=False),
        sa.Column("output", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_estimate_fcfa", sa.Integer(), nullable=False),
        sa.Column("error", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.execute("""
        INSERT INTO config (key, value, description) VALUES
        ('daily_model_call_cap', '60', 'Max model calls per phone number per day (FR-AI-07)'),
        ('max_open_requests_per_customer', '2', 'Max concurrent open requests per customer (FR-ABU-01)'),
        ('daily_request_cap_per_customer', '10', 'Max new requests per customer per day (FR-ABU-01)'),
        ('confirmation_expiry_minutes', '30', 'Minutes before unconfirmed requests expire (FR-INT-06)'),
        ('bounded_context_messages', '5', 'Max messages sent as context to AI (FR-AI-08)'),
        ('bad_lead_block_threshold', '3', 'Bad-lead reports before auto-block (FR-ABU-04)')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table("model_call_log")
    op.execute("""
        DELETE FROM config WHERE key IN (
            'daily_model_call_cap', 'max_open_requests_per_customer',
            'daily_request_cap_per_customer', 'confirmation_expiry_minutes',
            'bounded_context_messages', 'bad_lead_block_threshold'
        )
    """)
