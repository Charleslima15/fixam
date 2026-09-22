import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, SmallInteger
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UUIDPrimaryKey
from .enums import FollowupOutcome


class Followup(Base, UUIDPrimaryKey):
    __tablename__ = "followup"

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignment.id"), nullable=False
    )
    outcome: Mapped[FollowupOutcome | None] = mapped_column(
        ENUM(FollowupOutcome, name="followup_outcome", create_type=False),
        nullable=True,
    )
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
