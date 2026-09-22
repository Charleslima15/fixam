import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UUIDPrimaryKey


class ModelCallLog(Base, UUIDPrimaryKey):
    __tablename__ = "model_call_log"

    phone_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_request.id"), nullable=True
    )
    input_size: Mapped[int] = mapped_column(Integer, nullable=False)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_estimate_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
