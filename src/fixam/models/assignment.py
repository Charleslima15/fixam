import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, UUIDPrimaryKey


class Assignment(Base, UUIDPrimaryKey):
    __tablename__ = "assignment"

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_request.id"), unique=True, nullable=False
    )
    offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offer.id"), nullable=False
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider.id"), nullable=False
    )
    request: Mapped["ServiceRequest"] = relationship()  # noqa: F821
    offer: Mapped["Offer"] = relationship()  # noqa: F821
    provider: Mapped["Provider"] = relationship()  # noqa: F821
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
