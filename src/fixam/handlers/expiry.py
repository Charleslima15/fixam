"""Expire unconfirmed requests (FR-INT-06)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import Config, RequestState, ServiceRequest
from fixam.services.deps import Deps
from fixam.services.transitions import transition
from fixam.worker import register_handler

logger = logging.getLogger(__name__)


@register_handler("expire_unconfirmed")
async def expire_unconfirmed(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    """Expire requests in collecting or awaiting_confirmation past the timeout."""
    result = await session.execute(
        select(Config.value).where(Config.key == "confirmation_expiry_minutes")
    )
    val = result.scalar_one_or_none()
    expiry_minutes = int(val) if val else 30

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=expiry_minutes)

    result = await session.execute(
        select(ServiceRequest).where(
            ServiceRequest.state.in_([
                RequestState.collecting.value,
                RequestState.awaiting_confirmation.value,
            ]),
            ServiceRequest.updated_at < cutoff,
        )
    )
    requests = result.scalars().all()

    for req in requests:
        req.state = transition(req.state, RequestState.expired)
        logger.info("Expired request_id=%s from state=%s", req.id, req.state)
