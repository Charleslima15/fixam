"""Outbound message sender with 24-hour window logic (FR-OUT-01, FR-OUT-02)."""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import ContactWindow, Message
from fixam.services.whatsapp import WhatsAppClient

logger = logging.getLogger(__name__)

WINDOW_HOURS = 24


async def send_outbound(
    session: AsyncSession,
    whatsapp: WhatsAppClient,
    recipient_phone: str,
    text: str,
    *,
    template_name: str | None = None,
    request_id: uuid.UUID | None = None,
) -> Message:
    """Send a message, choosing free-form vs template based on window state.

    Returns the persisted outbound Message row (FR-OUT-03).
    """
    recipient_hash = hashlib.sha256(recipient_phone.encode()).hexdigest()

    row = await session.execute(
        select(ContactWindow).where(ContactWindow.phone_hash == recipient_hash)
    )
    window = row.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    window_open = (
        window is not None
        and (now - window.last_inbound_at) < timedelta(hours=WINDOW_HOURS)
    )

    if window_open:
        meta_id = await whatsapp.send_text(recipient_phone, text)
        used_template = None
    else:
        tpl = template_name or "general_notification"
        meta_id = await whatsapp.send_template(recipient_phone, tpl)
        used_template = tpl

    msg = Message(
        id=uuid.uuid4(),
        meta_message_id=meta_id,
        direction="outbound",
        sender_phone_hash="system",
        recipient_phone_hash=recipient_hash,
        message_type="text" if window_open else "template",
        template_name=used_template,
        request_id=request_id,
    )
    session.add(msg)
    logger.info(
        "Outbound msg_id=%s type=%s request_id=%s",
        msg.id,
        msg.message_type,
        request_id,
    )
    return msg
