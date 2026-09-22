import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, SmallInteger, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, UUIDPrimaryKey
from .enums import OfferState


class Offer(Base, UUIDPrimaryKey):
    __tablename__ = "offer"
    __table_args__ = (
        UniqueConstraint("request_id", "provider_id", name="uq_offer_request_provider"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_request.id"), nullable=False
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider.id"), nullable=False
    )
    request: Mapped["ServiceRequest"] = relationship()  # noqa: F821
    provider: Mapped["Provider"] = relationship()  # noqa: F821
    state: Mapped[OfferState] = mapped_column(
        ENUM(OfferState, name="offer_state", create_type=False),
        nullable=False,
    )
    wave: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
