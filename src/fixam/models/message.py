import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UUIDPrimaryKey
from .enums import MediaStatus


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
    media_id: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[MediaStatus] = mapped_column(
        ENUM(MediaStatus, name="media_status", create_type=False),
        nullable=False,
        server_default=MediaStatus.pending.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class ContactWindow(Base):
    __tablename__ = "contact_window"

    phone_hash: Mapped[str] = mapped_column(String, primary_key=True)
    last_inbound_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
