"""Provider text commands: AVAILABLE, OFF (FR-PRV-01)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.handlers.dispatch import handle_accept, handle_decline
from fixam.models import Provider
from fixam.services.deps import Deps
from fixam.services.sender import send_outbound
from fixam.worker import register_handler

logger = logging.getLogger(__name__)

COMMAND_LIST = (
    "Available commands:\n"
    "AVAILABLE - Turn on to receive job offers\n"
    "OFF - Stop receiving job offers\n"
    "BALANCE - Check your credits\n"
    "TOP UP - Add credits"
)


@register_handler("process_provider_message")
async def process_provider_message(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    provider_id = uuid.UUID(payload["provider_id"])
    phone = payload["sender_phone"]
    body: str | None = payload.get("body")
    button_reply_id: str | None = payload.get("button_reply_id")

    provider = await session.get(Provider, provider_id)
    if not provider:
        return

    # Handle button replies (accept/decline offers)
    if button_reply_id:
        if button_reply_id.startswith("accept:"):
            offer_id = uuid.UUID(button_reply_id.split(":", 1)[1])
            await handle_accept(session, deps, provider, offer_id)
            return
        elif button_reply_id.startswith("decline:"):
            offer_id = uuid.UUID(button_reply_id.split(":", 1)[1])
            await handle_decline(session, deps, provider, offer_id)
            return

    # Handle text commands
    cmd = (body or "").strip().upper()

    if cmd == "AVAILABLE":
        provider.is_available = True
        provider.consecutive_unanswered = 0
        await send_outbound(
            session, deps.whatsapp, phone,
            "You're now AVAILABLE and will receive job offers.",
        )
    elif cmd == "OFF":
        provider.is_available = False
        await send_outbound(
            session, deps.whatsapp, phone,
            "You're now OFF. Send AVAILABLE when you're ready for jobs again.",
        )
    else:
        await send_outbound(
            session, deps.whatsapp, phone, COMMAND_LIST,
        )
