"""Provider text commands: AVAILABLE, OFF, BALANCE, TOP UP (FR-PRV)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.handlers.dispatch import handle_accept, handle_decline
from fixam.models import Provider
from fixam.services.deps import Deps
from fixam.services.payments import (
    get_bundles,
    get_free_credit_remainder,
    get_provider_balance,
    initiate_payment,
)
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

    # Handle button replies
    if button_reply_id:
        if button_reply_id.startswith("accept:"):
            offer_id = uuid.UUID(button_reply_id.split(":", 1)[1])
            await handle_accept(session, deps, provider, offer_id)
            return
        elif button_reply_id.startswith("decline:"):
            offer_id = uuid.UUID(button_reply_id.split(":", 1)[1])
            await handle_decline(session, deps, provider, offer_id)
            return
        elif button_reply_id.startswith("topup:"):
            bundle_key = button_reply_id.split(":", 1)[1]
            bundles = await get_bundles(session, provider.id)
            bundle = next((b for b in bundles if b.key == bundle_key), None)
            if bundle is None:
                await send_outbound(
                    session, deps.whatsapp, phone,
                    "That bundle is not available. Send TOP UP to see options.",
                )
                return
            await initiate_payment(session, deps, provider, bundle, phone)
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
    elif cmd == "BALANCE":
        balance = await get_provider_balance(session, provider.id)
        free = await get_free_credit_remainder(session, provider.id)
        if free > 0:
            msg = f"You have {balance} credit{'s' if balance != 1 else ''} ({free} free)."
        else:
            msg = f"You have {balance} credit{'s' if balance != 1 else ''}."
        msg += " Send TOP UP to add more."
        await send_outbound(session, deps.whatsapp, phone, msg)
    elif cmd == "TOP UP":
        bundles = await get_bundles(session, provider.id)
        if not bundles:
            await send_outbound(
                session, deps.whatsapp, phone,
                "No credit bundles available. Please contact support.",
            )
            return
        buttons = [
            {"id": f"topup:{b.key}", "title": f"{b.credits} for {b.price_fcfa}"}
            for b in bundles
        ]
        await send_outbound(
            session, deps.whatsapp, phone,
            "Choose a credit bundle:",
            buttons=buttons,
        )
    else:
        await send_outbound(
            session, deps.whatsapp, phone, COMMAND_LIST,
        )
