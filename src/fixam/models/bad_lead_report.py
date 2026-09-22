import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UUIDPrimaryKey
from .enums import BadLeadReason, BadLeadStatus


class BadLeadReport(Base, UUIDPrimaryKey):
    __tablename__ = "bad_lead_report"

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignment.id"), unique=True, nullable=False
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider.id"), nullable=False
    )
    reason: Mapped[BadLeadReason] = mapped_column(
        ENUM(BadLeadReason, name="bad_lead_reason", create_type=False),
        nullable=False,
    )
    status: Mapped[BadLeadStatus] = mapped_column(
        ENUM(BadLeadStatus, name="bad_lead_status", create_type=False),
        nullable=False,
        server_default=BadLeadStatus.pending.value,
    )
    operator_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
