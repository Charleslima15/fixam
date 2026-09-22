"""Job enqueueing helper — usable inside an existing DB transaction."""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import Job


async def enqueue_job(
    session: AsyncSession,
    kind: str,
    payload: dict,
    *,
    due_at: datetime | None = None,
    max_attempts: int = 5,
) -> Job:
    job = Job(
        id=uuid.uuid4(),
        kind=kind,
        payload=payload,
        scheduled_at=due_at or datetime.now(timezone.utc),
        max_attempts=max_attempts,
    )
    session.add(job)
    return job
