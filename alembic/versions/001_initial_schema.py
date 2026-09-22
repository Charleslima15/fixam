"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- enums ---
    request_state = postgresql.ENUM(
        "collecting", "awaiting_confirmation", "dispatching", "assigned",
        "followed_up", "closed", "expired", "unfilled", "cancelled",
        name="request_state", create_type=True,
    )
    request_state.create(op.get_bind(), checkfirst=True)

    offer_state = postgresql.ENUM(
        "queued", "sent", "accepted", "declined", "expired", "withdrawn", "failed",
        name="offer_state", create_type=True,
    )
    offer_state.create(op.get_bind(), checkfirst=True)

    payment_state = postgresql.ENUM(
        "initiated", "pending", "succeeded", "failed", "stuck",
        name="payment_state", create_type=True,
    )
    payment_state.create(op.get_bind(), checkfirst=True)

    ledger_kind = postgresql.ENUM(
        "grant_free", "purchase", "debit_accept", "refund_bad_lead", "adjustment",
        name="ledger_kind", create_type=True,
    )
    ledger_kind.create(op.get_bind(), checkfirst=True)

    urgency = postgresql.ENUM(
        "now", "today", "this_week", "unknown",
        name="urgency", create_type=True,
    )
    urgency.create(op.get_bind(), checkfirst=True)

    trust_tier = postgresql.ENUM(
        "new", "established", "blocked",
        name="trust_tier", create_type=True,
    )
    trust_tier.create(op.get_bind(), checkfirst=True)

    job_state = postgresql.ENUM(
        "pending", "claimed", "succeeded", "failed", "dead",
        name="job_state", create_type=True,
    )
    job_state.create(op.get_bind(), checkfirst=True)

    followup_outcome = postgresql.ENUM(
        "yes", "no", "still_waiting", "no_response",
        name="followup_outcome", create_type=True,
    )
    followup_outcome.create(op.get_bind(), checkfirst=True)

    bad_lead_reason = postgresql.ENUM(
        "number_unreachable", "nobody_at_location", "customer_denied",
        name="bad_lead_reason", create_type=True,
    )
    bad_lead_reason.create(op.get_bind(), checkfirst=True)

    bad_lead_status = postgresql.ENUM(
        "pending", "approved", "denied",
        name="bad_lead_status", create_type=True,
    )
    bad_lead_status.create(op.get_bind(), checkfirst=True)

    # --- reference tables ---
    op.create_table(
        "trade",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), unique=True, nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true"),
    )
    op.create_table(
        "quarter",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), unique=True, nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true"),
    )

    # --- provider ---
    op.create_table(
        "provider",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("phone_hash", sa.String(), unique=True, nullable=False),
        sa.Column("name_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("phone_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default="true"),
        sa.Column("is_active", sa.Boolean(), server_default="false"),
        sa.Column("is_suspended", sa.Boolean(), server_default="false"),
        sa.Column("suspend_reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "provider_trade",
        sa.Column("provider_id", sa.Uuid(), sa.ForeignKey("provider.id"), primary_key=True),
        sa.Column("trade_id", sa.Uuid(), sa.ForeignKey("trade.id"), primary_key=True),
    )
    op.create_table(
        "provider_area",
        sa.Column("provider_id", sa.Uuid(), sa.ForeignKey("provider.id"), primary_key=True),
        sa.Column("quarter_id", sa.Uuid(), sa.ForeignKey("quarter.id"), primary_key=True),
    )

    # --- customer ---
    op.create_table(
        "customer",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("phone_hash", sa.String(), unique=True, nullable=False),
        sa.Column("phone_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("name_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("trust_tier", trust_tier, nullable=False, server_default="new"),
        sa.Column("last_area_id", sa.Uuid(), sa.ForeignKey("quarter.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- service_request ---
    op.create_table(
        "service_request",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("trade_id", sa.Uuid(), sa.ForeignKey("trade.id"), nullable=True),
        sa.Column("quarter_id", sa.Uuid(), sa.ForeignKey("quarter.id"), nullable=True),
        sa.Column("urgency", urgency, nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("state", request_state, nullable=False),
        sa.Column("conversation", postgresql.JSONB(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- offer ---
    op.create_table(
        "offer",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("service_request.id"), nullable=False),
        sa.Column("provider_id", sa.Uuid(), sa.ForeignKey("provider.id"), nullable=False),
        sa.Column("state", offer_state, nullable=False),
        sa.Column("wave", sa.SmallInteger(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("request_id", "provider_id", name="uq_offer_request_provider"),
    )

    # --- assignment ---
    op.create_table(
        "assignment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("service_request.id"), unique=True, nullable=False),
        sa.Column("offer_id", sa.Uuid(), sa.ForeignKey("offer.id"), nullable=False),
        sa.Column("provider_id", sa.Uuid(), sa.ForeignKey("provider.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- credit_ledger ---
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider_id", sa.Uuid(), sa.ForeignKey("provider.id"), nullable=False),
        sa.Column("kind", ledger_kind, nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("reference_type", sa.String(), nullable=True),
        sa.Column("actor", sa.String(), nullable=False, server_default="system"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_credit_ledger_provider_id", "credit_ledger", ["provider_id"])

    # FR-LED-01: append-only enforcement via triggers
    op.execute("""
        CREATE FUNCTION prevent_ledger_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'credit_ledger is append-only: % not allowed', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_ledger_no_update
        BEFORE UPDATE ON credit_ledger
        FOR EACH ROW EXECUTE FUNCTION prevent_ledger_mutation();
    """)
    op.execute("""
        CREATE TRIGGER trg_ledger_no_delete
        BEFORE DELETE ON credit_ledger
        FOR EACH ROW EXECUTE FUNCTION prevent_ledger_mutation();
    """)

    # --- payment ---
    op.create_table(
        "payment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider_id", sa.Uuid(), sa.ForeignKey("provider.id"), nullable=False),
        sa.Column("our_reference", sa.String(), unique=True, nullable=False),
        sa.Column("mtn_reference", sa.String(), nullable=True),
        sa.Column("amount_fcfa", sa.Integer(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("state", payment_state, nullable=False),
        sa.Column("raw_callback", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # partial unique index: mtn_reference unique where not null
    op.execute("""
        CREATE UNIQUE INDEX uq_payment_mtn_reference
        ON payment (mtn_reference)
        WHERE mtn_reference IS NOT NULL;
    """)

    # --- message ---
    op.create_table(
        "message",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("meta_message_id", sa.String(), unique=True, nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("sender_phone_hash", sa.String(), nullable=False),
        sa.Column("recipient_phone_hash", sa.String(), nullable=True),
        sa.Column("message_type", sa.String(), nullable=False),
        sa.Column("body_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("service_request.id"), nullable=True),
        sa.Column("template_name", sa.String(), nullable=True),
        sa.Column("delivery_status", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- media ---
    op.create_table(
        "media",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("message.id"), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- job ---
    op.create_table(
        "job",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("state", job_state, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- followup ---
    op.create_table(
        "followup",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("assignment_id", sa.Uuid(), sa.ForeignKey("assignment.id"), nullable=False),
        sa.Column("outcome", followup_outcome, nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- bad_lead_report ---
    op.create_table(
        "bad_lead_report",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("assignment_id", sa.Uuid(), sa.ForeignKey("assignment.id"), unique=True, nullable=False),
        sa.Column("provider_id", sa.Uuid(), sa.ForeignKey("provider.id"), nullable=False),
        sa.Column("reason", bad_lead_reason, nullable=False),
        sa.Column("status", bad_lead_status, nullable=False, server_default="pending"),
        sa.Column("operator_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- operator ---
    op.create_table(
        "operator",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- audit_log ---
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("operator_id", sa.Uuid(), sa.ForeignKey("operator.id"), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- config ---
    op.create_table(
        "config",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    tables = [
        "config", "audit_log", "operator", "bad_lead_report", "followup",
        "job", "media", "message", "payment", "credit_ledger", "assignment",
        "offer", "service_request", "customer", "provider_area", "provider_trade",
        "provider", "quarter", "trade",
    ]
    for t in tables:
        op.drop_table(t)

    op.execute("DROP FUNCTION IF EXISTS prevent_ledger_mutation() CASCADE")

    enums = [
        "bad_lead_status", "bad_lead_reason", "followup_outcome", "job_state",
        "trust_tier", "urgency", "ledger_kind", "payment_state", "offer_state",
        "request_state",
    ]
    for e in enums:
        op.execute(f"DROP TYPE IF EXISTS {e}")
