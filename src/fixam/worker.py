"""Background job worker.

Claims due jobs with FOR UPDATE SKIP LOCKED (NFR-COR-03).
Retries with exponential backoff; dead after max_attempts (NFR-COR-04).
Handlers registered by kind — later slices just add entries to HANDLERS.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable, TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fixam.models import Config, Job, JobState

if TYPE_CHECKING:
    from fixam.services.deps import Deps

logger = logging.getLogger(__name__)

HandlerFn = Callable[[AsyncSession, dict[str, Any], "Deps"], Awaitable[None]]
HANDLERS: dict[str, HandlerFn] = {}


def register_handler(kind: str) -> Callable[[HandlerFn], HandlerFn]:
    def decorator(fn: HandlerFn) -> HandlerFn:
        HANDLERS[kind] = fn
        return fn
    return decorator


@dataclass(frozen=True, slots=True)
class _ClaimedJob:
    id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


async def _get_backoff_base(session: AsyncSession) -> int:
    row = await session.execute(
        select(Config.value).where(Config.key == "job_backoff_base_seconds")
    )
    val = row.scalar_one_or_none()
    return int(val) if val else 30


async def _claim_one(sf: async_sessionmaker[AsyncSession], deps: Deps) -> bool:
    """Try to claim and execute one job. Returns True if a job was processed."""
    # Phase 1: claim
    async with sf() as session:
        async with session.begin():
            now = datetime.now(timezone.utc)
            result = await session.execute(
                select(Job)
                .where(Job.state == JobState.pending)
                .where(Job.scheduled_at <= now)
                .order_by(Job.scheduled_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            job = result.scalar_one_or_none()
            if job is None:
                return False

            job.state = JobState.claimed
            job.claimed_at = now
            job.attempts += 1

            claimed = _ClaimedJob(
                id=job.id,
                kind=job.kind,
                payload=dict(job.payload),
                attempts=job.attempts,
                max_attempts=job.max_attempts,
            )

    handler = HANDLERS.get(claimed.kind)
    if handler is None:
        async with sf() as session:
            async with session.begin():
                await session.execute(
                    update(Job).where(Job.id == claimed.id).values(
                        state=JobState.dead,
                        completed_at=datetime.now(timezone.utc),
                        error=f"No handler registered for kind={claimed.kind!r}",
                    )
                )
        logger.error("No handler for job kind=%s id=%s", claimed.kind, claimed.id)
        return True

    # Phase 2: execute handler
    try:
        async with sf() as session:
            async with session.begin():
                await handler(session, claimed.payload, deps)
                await session.execute(
                    update(Job).where(Job.id == claimed.id).values(
                        state=JobState.succeeded,
                        completed_at=datetime.now(timezone.utc),
                        error=None,
                    )
                )
    except Exception as exc:
        # Phase 3: retry or dead
        async with sf() as session:
            async with session.begin():
                if claimed.attempts >= claimed.max_attempts:
                    await session.execute(
                        update(Job).where(Job.id == claimed.id).values(
                            state=JobState.dead,
                            completed_at=datetime.now(timezone.utc),
                            error=str(exc)[:2000],
                        )
                    )
                    logger.error(
                        "Job dead kind=%s id=%s after %d attempts: %s",
                        claimed.kind, claimed.id, claimed.attempts, exc,
                    )
                else:
                    backoff_base = await _get_backoff_base(session)
                    delay = backoff_base * (2 ** (claimed.attempts - 1))
                    await session.execute(
                        update(Job).where(Job.id == claimed.id).values(
                            state=JobState.pending,
                            scheduled_at=datetime.now(timezone.utc) + timedelta(seconds=delay),
                            claimed_at=None,
                            error=str(exc)[:2000],
                        )
                    )
                    logger.warning(
                        "Job retry kind=%s id=%s attempt=%d next_in=%ds: %s",
                        claimed.kind, claimed.id, claimed.attempts, delay, exc,
                    )
    return True


async def run_worker(
    sf: async_sessionmaker[AsyncSession],
    deps: Deps,
    *,
    poll_interval: float = 1.0,
    shutdown: asyncio.Event | None = None,
) -> None:
    """Main worker loop. Runs until shutdown event is set."""
    _shutdown = shutdown or asyncio.Event()
    while not _shutdown.is_set():
        try:
            processed = await _claim_one(sf, deps)
        except Exception:
            logger.exception("Worker loop error")
            processed = False
        if not processed:
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass


async def main() -> None:
    from fixam.db import async_session_factory
    from fixam.services.deps import Deps
    from fixam.services.whatsapp import FakeWhatsAppClient
    from fixam.services.media import FakeMediaStore
    from fixam.services.ai import FakeAIClient
    import fixam.handlers  # noqa: F401 — registers handlers
    deps = Deps(whatsapp=FakeWhatsAppClient(), media=FakeMediaStore(), ai=FakeAIClient())
    logger.info("Worker starting")
    await run_worker(async_session_factory, deps)
