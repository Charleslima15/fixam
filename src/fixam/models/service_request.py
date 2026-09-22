import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKey
from .enums import RequestState, Urgency


class ServiceRequest(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "service_request"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer.id"), nullable=False
    )
    customer: Mapped["Customer"] = relationship()  # noqa: F821
    trade_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trade.id"), nullable=True
    )
    quarter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("quarter.id"), nullable=True
    )
    urgency: Mapped[Urgency | None] = mapped_column(
        ENUM(Urgency, name="urgency", create_type=False),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[RequestState] = mapped_column(
        ENUM(RequestState, name="request_state", create_type=False),
        nullable=False,
    )
    conversation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
