"""Customer intake job handler (FR-INT, FR-AI, FR-ABU)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import Message
from fixam.services.deps import Deps
from fixam.services.intake import process_customer_message
from fixam.worker import register_handler

logger = logging.getLogger(__name__)


@register_handler("process_customer_intake")
async def process_customer_intake(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    msg_id = uuid.UUID(payload["message_id"])
    sender_phone = payload["sender_phone"]

    msg = await session.get(Message, msg_id)
    if msg is None:
        logger.error("Message not found msg_id=%s", msg_id)
        return

    body = ""
    button_reply_id = None
    if msg.body_encrypted:
        body = msg.body_encrypted.decode("utf-8", errors="replace")

    if msg.message_type == "interactive":
        button_reply_id = body
        body = ""

    await process_customer_message(
        session,
        sender_phone,
        body,
        deps.ai,
        deps.whatsapp,
        message_type=msg.message_type,
        button_reply_id=button_reply_id,
    )
