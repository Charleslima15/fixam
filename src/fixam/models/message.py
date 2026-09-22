import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UUIDPrimaryKey


class Message(Base, UUIDPrimaryKey):
    __tablename__ = "message"

    meta_message_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    sender_phone_hash: Mapped[str] = mapped_column(String, nullable=False)
    recipient_phone_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    message_type: Mapped[str] = mapped_column(String, nullable=False)
    body_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_request.id"), nullable=True
    )
    template_name: Mapped[str | None] = mapped_column(String, nullable=True)
    delivery_status: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class Media(Base, UUIDPrimaryKey):
    __tablename__ = "media"

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id"), nullable=False
    )
    media_type: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
