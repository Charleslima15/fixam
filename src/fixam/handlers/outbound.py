"""Outbound message sending handler (FR-OUT-01, FR-OUT-04)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from fixam.services.deps import Deps
from fixam.services.sender import send_outbound
from fixam.worker import register_handler

logger = logging.getLogger(__name__)


@register_handler("send_message")
async def send_message_handler(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    to = payload["to"]
    text = payload["text"]
    template_name = payload.get("template_name")
    request_id_str = payload.get("request_id")
    request_id = uuid.UUID(request_id_str) if request_id_str else None

    await send_outbound(
        session,
        deps.whatsapp,
        to,
        text,
        template_name=template_name,
        request_id=request_id,
    )
