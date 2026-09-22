"""Tests for the job worker.

Covers NFR-COR-03 (FOR UPDATE SKIP LOCKED), NFR-COR-04 (retry + dead),
NFR-REL-01 (restart picks up due jobs), and transactional enqueue safety.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fixam.models import Config, Job, JobState
from fixam.services.deps import Deps
from fixam.services.jobs import enqueue_job
from fixam.services.whatsapp import FakeWhatsAppClient
from fixam.services.media import FakeMediaStore
from fixam.worker import HANDLERS, _claim_one, register_handler, run_worker


@pytest_asyncio.fixture
async def fake_deps():
    return Deps(whatsapp=FakeWhatsAppClient(), media=FakeMediaStore())


@pytest_asyncio.fixture(autouse=True)
async def _clean_jobs(session_factory):
    """Delete all jobs after each test."""
    yield
    try:
        async with session_factory() as s:
            async with s.begin():
                await s.execute(text("DELETE FROM job"))
    except Exception:
        pass


@pytest_asyncio.fixture(autouse=True)
async def _clean_handlers():
    """Restore handler registry after each test."""
    saved = dict(HANDLERS)
    yield
    HANDLERS.clear()
    HANDLERS.update(saved)


# ---------------------------------------------------------------------------
# NFR-COR-03: Two workers never execute the same job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_workers_no_duplicate_execution(session_factory, fake_deps):
    """Two workers claiming concurrently never run the same job twice."""
    executed: list[uuid.UUID] = []
    lock = asyncio.Lock()

    @register_handler("test_concurrent")
    async def handler(session: AsyncSession, payload: dict, deps: Deps) -> None:
        async with lock:
            executed.append(uuid.UUID(payload["job_id"]))
        await asyncio.sleep(0.01)

    async with session_factory() as s:
        async with s.begin():
            for _ in range(10):
                jid = uuid.uuid4()
                await enqueue_job(s, "test_concurrent", {"job_id": str(jid)})

    shutdown = asyncio.Event()

    async def worker_loop():
        await run_worker(session_factory, fake_deps, poll_interval=0.05, shutdown=shutdown)

    t1 = asyncio.create_task(worker_loop())
    t2 = asyncio.create_task(worker_loop())

    for _ in range(200):
        await asyncio.sleep(0.05)
        async with session_factory() as s:
            remaining = (
                await s.execute(
                    select(Job).where(Job.state.in_([JobState.pending, JobState.claimed]))
                )
            ).scalars().all()
            if not remaining:
                break

    shutdown.set()
    await asyncio.gather(t1, t2)

    assert len(executed) == 10
    assert len(set(executed)) == 10


# ---------------------------------------------------------------------------
# NFR-COR-04: Failing job retries with backoff, then dead
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_then_dead(session_factory, fake_deps):
    """A failing handler retries with backoff, then goes dead after max_attempts."""
    call_count = 0

    @register_handler("test_fail")
    async def handler(session: AsyncSession, payload: dict, deps: Deps) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("boom")

    # Seed backoff config
    async with session_factory() as s:
        async with s.begin():
            await s.execute(text("DELETE FROM config WHERE key = 'job_backoff_base_seconds'"))
            s.add(Config(key="job_backoff_base_seconds", value="1"))

    async with session_factory() as s:
        async with s.begin():
            job = await enqueue_job(s, "test_fail", {"x": 1}, max_attempts=3)
            job_id = job.id

    shutdown = asyncio.Event()
    task = asyncio.create_task(
        run_worker(session_factory, fake_deps, poll_interval=0.05, shutdown=shutdown)
    )

    for attempt in range(3):
        # Wait for the attempt to complete (state goes to pending or dead)
        for _ in range(100):
            await asyncio.sleep(0.05)
            async with session_factory() as s:
                j = await s.get(Job, job_id)
                if j.state in (JobState.pending, JobState.dead):
                    break
        if j.state == JobState.dead:
            break
        # Fast-forward scheduled_at so the retry fires immediately
        async with session_factory() as s:
            async with s.begin():
                await s.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(scheduled_at=datetime.now(timezone.utc))
                )

    # Wait for dead
    for _ in range(100):
        await asyncio.sleep(0.05)
        async with session_factory() as s:
            j = await s.get(Job, job_id)
            if j.state == JobState.dead:
                break

    shutdown.set()
    await task

    # Clean up config
    async with session_factory() as s:
        async with s.begin():
            await s.execute(text("DELETE FROM config WHERE key = 'job_backoff_base_seconds'"))

    assert j.state == JobState.dead
    assert j.error == "boom"
    assert call_count == 3


# ---------------------------------------------------------------------------
# Transactional enqueue: rollback prevents job from running
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueued_job_rolls_back_with_transaction(session_factory, fake_deps):
    """A job enqueued inside a transaction that rolls back never appears."""
    executed = []

    @register_handler("test_rollback")
    async def handler(session: AsyncSession, payload: dict, deps: Deps) -> None:
        executed.append(1)

    try:
        async with session_factory() as s:
            async with s.begin():
                await enqueue_job(s, "test_rollback", {"x": 1})
                raise ValueError("force rollback")
    except ValueError:
        pass

    # Run worker briefly — should find nothing
    shutdown = asyncio.Event()
    task = asyncio.create_task(
        run_worker(session_factory, fake_deps, poll_interval=0.05, shutdown=shutdown)
    )
    await asyncio.sleep(0.3)
    shutdown.set()
    await task

    assert executed == []

    async with session_factory() as s:
        jobs = (
            await s.execute(select(Job).where(Job.kind == "test_rollback"))
        ).scalars().all()
        assert len(jobs) == 0


# ---------------------------------------------------------------------------
# NFR-REL-01: Jobs due during downtime run on restart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jobs_due_during_downtime_run_on_restart(session_factory, fake_deps):
    """Jobs scheduled in the past are picked up when the worker starts."""
    executed_ids: list[str] = []

    @register_handler("test_restart")
    async def handler(session: AsyncSession, payload: dict, deps: Deps) -> None:
        executed_ids.append(payload["id"])

    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    async with session_factory() as s:
        async with s.begin():
            await enqueue_job(s, "test_restart", {"id": "old1"}, due_at=past)
            await enqueue_job(s, "test_restart", {"id": "old2"}, due_at=past)

    shutdown = asyncio.Event()
    task = asyncio.create_task(
        run_worker(session_factory, fake_deps, poll_interval=0.05, shutdown=shutdown)
    )

    for _ in range(100):
        await asyncio.sleep(0.05)
        if len(executed_ids) == 2:
            break

    shutdown.set()
    await task

    assert sorted(executed_ids) == ["old1", "old2"]
