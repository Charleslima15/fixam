"""Payment job handlers — confirm_payment, poll, low-balance warning."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import Provider
from fixam.services.deps import Deps
from fixam.services.payments import (
    confirm_payment,
    poll_pending_payments,
)
from fixam.services.sender import send_outbound
from fixam.worker import register_handler

logger = logging.getLogger(__name__)


@register_handler("confirm_payment")
async def handle_confirm_payment(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    payment_id = uuid.UUID(payload["payment_id"])
    await confirm_payment(session, deps, payment_id)


@register_handler("poll_pending_payments")
async def handle_poll_pending_payments(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    await poll_pending_payments(session, deps)


@register_handler("send_low_balance_warning")
async def handle_low_balance_warning(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    provider_id = uuid.UUID(payload["provider_id"])
    balance = payload["balance"]
    provider = await session.get(Provider, provider_id)
    if not provider:
        return
    phone = provider.phone_encrypted.decode()
    await send_outbound(
        session, deps.whatsapp, phone,
        f"Your balance is low ({balance} credit{'s' if balance != 1 else ''}). "
        "Send TOP UP to add more.",
    )
