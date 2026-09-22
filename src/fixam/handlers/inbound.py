"""Inbound message processing handler (FR-MSG-04, FR-MSG-06)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import ContactWindow, Media, MediaStatus, Message, Provider
from fixam.services.deps import Deps
from fixam.services.jobs import enqueue_job
from fixam.worker import register_handler

logger = logging.getLogger(__name__)

UNSUPPORTED_TYPES = {"location", "contacts", "document", "sticker"}

UNSUPPORTED_REPLY = (
    "Sorry, we can only handle text, photos, and voice messages right now."
)

PROVIDER_ACK = "Message received."


@register_handler("process_inbound")
async def process_inbound(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    msg_id = uuid.UUID(payload["message_id"])
    sender_phone = payload["sender_phone"]

    msg = await session.get(Message, msg_id)
    if msg is None:
        logger.error("Message not found msg_id=%s", msg_id)
        return

    # Upsert contact window (FR-OUT-02)
    now = datetime.now(timezone.utc)
    stmt = pg_insert(ContactWindow).values(
        phone_hash=msg.sender_phone_hash, last_inbound_at=now
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[ContactWindow.phone_hash],
        set_={"last_inbound_at": now},
    )
    await session.execute(stmt)

    # Enqueue media downloads for pending media (FR-MSG-05)
    from sqlalchemy import and_

    result = await session.execute(
        select(Media).where(
            and_(Media.message_id == msg_id, Media.status == MediaStatus.pending)
        )
    )
    for media_row in result.scalars():
        await enqueue_job(
            session,
            "download_media",
            {"media_id": str(media_row.id), "media_meta_id": media_row.media_id},
        )

    # Unsupported message types get a fixed reply (FR-MSG-06)
    if msg.message_type in UNSUPPORTED_TYPES:
        await enqueue_job(
            session,
            "send_message",
            {"to": sender_phone, "text": UNSUPPORTED_REPLY},
        )
        logger.info("Unsupported type=%s msg_id=%s", msg.message_type, msg_id)
        return

    # Route by sender (FR-MSG-04)
    result = await session.execute(
        select(Provider.id).where(Provider.phone_hash == msg.sender_phone_hash)
    )
    is_provider = result.scalar_one_or_none() is not None

    if is_provider:
        await enqueue_job(
            session,
            "send_message",
            {"to": sender_phone, "text": PROVIDER_ACK},
        )
        logger.info("Provider message msg_id=%s", msg_id)
    else:
        # Route customer messages through intake (FR-INT)
        await enqueue_job(
            session,
            "process_customer_intake",
            {"message_id": str(msg_id), "sender_phone": sender_phone},
        )
        logger.info("Customer message routed to intake msg_id=%s", msg_id)
