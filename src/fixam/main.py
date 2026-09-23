"""FastAPI application — webhook ingress (FR-MSG-01 through FR-MSG-07)."""
from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.config import settings
from fixam.db import get_session
from fixam.models import Media, MediaStatus, Message
from fixam.services.jobs import enqueue_job
from fixam.services.whatsapp import verify_signature

logger = logging.getLogger(__name__)
app = FastAPI(title="FixAm")


@app.get("/webhook")
async def webhook_verify(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
) -> Response:
    """Meta webhook verification (subscription handshake)."""
    if hub_mode == "subscribe" and hub_verify_token == settings.webhook_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook", status_code=200, response_model=None)
async def webhook_ingest(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict | Response:
    """Receive Meta webhook, verify signature, persist, enqueue jobs (FR-MSG-01..03)."""
    body = await request.body()

    # Signature verification (FR-MSG-01)
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not settings.whatsapp_app_secret:
        logger.warning("whatsapp_app_secret not configured, skipping signature check")
    elif not verify_signature(body, signature, settings.whatsapp_app_secret):
        return Response(status_code=403, content="Invalid signature")

    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            await _process_messages(session, value)
            await _process_statuses(session, value)

    await session.commit()
    return {"status": "ok"}


async def _process_messages(session: AsyncSession, value: dict) -> None:
    """Persist inbound messages and enqueue processing jobs."""
    messages = value.get("messages", [])
    for msg_data in messages:
        meta_id = msg_data.get("id", "")
        if not meta_id:
            continue

        # Idempotency check (FR-MSG-03)
        existing = await session.execute(
            select(Message.id).where(Message.meta_message_id == meta_id)
        )
        if existing.scalar_one_or_none() is not None:
            continue

        sender_phone = msg_data.get("from", "")
        sender_hash = hashlib.sha256(sender_phone.encode()).hexdigest()
        msg_type = msg_data.get("type", "text")

        body_text = ""
        button_reply_id = None
        if msg_type == "text":
            body_text = msg_data.get("text", {}).get("body", "")
        elif msg_type == "interactive":
            interactive = msg_data.get("interactive", {})
            if "button_reply" in interactive:
                button_reply_id = interactive["button_reply"].get("id", "")
                body_text = button_reply_id

        msg = Message(
            id=uuid.uuid4(),
            meta_message_id=meta_id,
            direction="inbound",
            sender_phone_hash=sender_hash,
            message_type=msg_type,
            body_encrypted=body_text.encode() if body_text else None,
        )
        session.add(msg)

        # Media attachments
        if msg_type in ("image", "audio", "video"):
            media_section = msg_data.get(msg_type, {})
            media_meta_id = media_section.get("id")
            media_row = Media(
                id=uuid.uuid4(),
                message_id=msg.id,
                media_type=msg_type,
                media_id=media_meta_id,
                status=MediaStatus.pending,
            )
            session.add(media_row)

        job_payload: dict = {"message_id": str(msg.id), "sender_phone": sender_phone}
        if button_reply_id:
            job_payload["button_reply_id"] = button_reply_id
        await enqueue_job(
            session,
            "process_inbound",
            job_payload,
        )
        logger.info("Inbound persisted msg_id=%s type=%s", msg.id, msg_type)


async def _process_statuses(session: AsyncSession, value: dict) -> None:
    """Record delivery status updates against outbound messages (FR-MSG-07)."""
    statuses = value.get("statuses", [])
    for status_data in statuses:
        meta_id = status_data.get("id", "")
        status = status_data.get("status", "")
        if not meta_id or not status:
            continue

        result = await session.execute(
            select(Message).where(
                Message.meta_message_id == meta_id,
                Message.direction == "outbound",
            )
        )
        msg = result.scalar_one_or_none()
        if msg is not None:
            msg.delivery_status = status
            logger.info(
                "Status update msg_id=%s status=%s", msg.id, status
            )
