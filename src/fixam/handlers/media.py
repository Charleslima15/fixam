"""Media download handler (FR-MSG-05)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import Media, MediaStatus
from fixam.services.deps import Deps
from fixam.worker import register_handler

logger = logging.getLogger(__name__)


@register_handler("download_media")
async def download_media_handler(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    media_id = uuid.UUID(payload["media_id"])
    media_meta_id = payload.get("media_meta_id")

    media = await session.get(Media, media_id)
    if media is None:
        logger.error("Media row not found media_id=%s", media_id)
        return

    if media.status != MediaStatus.pending:
        return

    if not media_meta_id:
        media.status = MediaStatus.failed
        return

    try:
        data, content_type = await deps.whatsapp.download_media(media_meta_id)
        storage_key = await deps.media.store(media_meta_id, data, content_type)
        media.storage_key = storage_key
        media.status = MediaStatus.stored
        logger.info("Media stored media_id=%s key=%s", media_id, storage_key)
    except Exception:
        media.status = MediaStatus.failed
        logger.exception("Media download failed media_id=%s", media_id)
        raise
