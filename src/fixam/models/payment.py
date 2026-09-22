import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKey
from .enums import PaymentState


class Payment(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "payment"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider.id"), nullable=False
    )
    our_reference: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    mtn_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    amount_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[PaymentState] = mapped_column(
        ENUM(PaymentState, name="payment_state", create_type=False),
        nullable=False,
    )
    raw_callback: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
