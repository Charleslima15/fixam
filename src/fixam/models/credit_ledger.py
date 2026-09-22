import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, UUIDPrimaryKey
from .enums import LedgerKind


class CreditLedger(Base, UUIDPrimaryKey):
    __tablename__ = "credit_ledger"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider.id"), nullable=False
    )
    provider: Mapped["Provider"] = relationship()  # noqa: F821
    kind: Mapped[LedgerKind] = mapped_column(
        ENUM(LedgerKind, name="ledger_kind", create_type=False),
        nullable=False,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String, nullable=True)
    actor: Mapped[str] = mapped_column(String, nullable=False, server_default="system")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
