import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from fixam.models import (
    Base,
    CreditLedger,
    Customer,
    LedgerKind,
    Message,
    Offer,
    OfferState,
    Provider,
    RequestState,
    ServiceRequest,
)
from fixam.services.ai import FakeAIClient
from fixam.services.deps import Deps
from fixam.services.whatsapp import FakeWhatsAppClient
from fixam.services.media import FakeMediaStore

_schema_created = False


def _sync_url(async_url: str) -> str:
    return async_url.replace("+asyncpg", "").replace("asyncpg", "psycopg2")


def _ensure_schema(async_url: str) -> None:
    """Create tables and triggers once per process using a sync connection."""
    global _schema_created
    if _schema_created:
        return

    from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
    for tbl in Base.metadata.sorted_tables:
        for col in tbl.columns:
            if isinstance(col.type, PG_ENUM) and not col.type.create_type:
                col.type.create_type = True
    sync_url = async_url.replace("asyncpg", "psycopg2")
    eng = create_engine(sync_url)
    with eng.begin() as conn:
        Base.metadata.create_all(conn)
    for tbl in Base.metadata.sorted_tables:
        for col in tbl.columns:
            if isinstance(col.type, PG_ENUM):
                col.type.create_type = False
    with eng.connect() as conn:
        raw = conn.connection.dbapi_connection
        cur = raw.cursor()
        cur.execute(
            "CREATE OR REPLACE FUNCTION prevent_ledger_mutation() RETURNS trigger "
            "AS $fn$ BEGIN RAISE EXCEPTION 'credit_ledger is append-only' "
            "USING DETAIL = TG_OP; END; $fn$ LANGUAGE plpgsql"
        )
        cur.execute(
            "DROP TRIGGER IF EXISTS trg_ledger_no_update ON credit_ledger"
        )
        cur.execute(
            "CREATE TRIGGER trg_ledger_no_update "
            "BEFORE UPDATE ON credit_ledger "
            "FOR EACH ROW EXECUTE FUNCTION prevent_ledger_mutation()"
        )
        cur.execute(
            "DROP TRIGGER IF EXISTS trg_ledger_no_delete ON credit_ledger"
        )
        cur.execute(
            "CREATE TRIGGER trg_ledger_no_delete "
            "BEFORE DELETE ON credit_ledger "
            "FOR EACH ROW EXECUTE FUNCTION prevent_ledger_mutation()"
        )
        raw.commit()
        cur.close()
    eng.dispose()
    _schema_created = True


@pytest.fixture(scope="session")
def db_url():
    env_url = os.environ.get("TEST_DATABASE_URL")
    if env_url:
        yield env_url
        return
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        if "psycopg2" in url:
            url = url.replace("psycopg2", "asyncpg")
        yield url


@pytest_asyncio.fixture
async def engine(db_url) -> AsyncGenerator[AsyncEngine, None]:
    from sqlalchemy.pool import NullPool

    _ensure_schema(db_url)
    eng = create_async_engine(db_url, echo=False, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def pooled_engine(db_url) -> AsyncGenerator[AsyncEngine, None]:
    """Pooled engine for concurrency tests that need real connection contention."""
    _ensure_schema(db_url)
    eng = create_async_engine(db_url, echo=False, pool_size=10)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def pooled_session_factory(pooled_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pooled_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


@pytest_asyncio.fixture
async def fake_deps():
    return Deps(whatsapp=FakeWhatsAppClient(), media=FakeMediaStore(), ai=FakeAIClient())


def make_provider(**kwargs) -> Provider:
    defaults = dict(
        id=uuid.uuid4(),
        phone_hash=f"hash-{uuid.uuid4().hex[:8]}",
        name_encrypted=b"enc-name",
        phone_encrypted=b"enc-phone",
    )
    defaults.update(kwargs)
    return Provider(**defaults)


def make_customer(**kwargs) -> Customer:
    defaults = dict(
        id=uuid.uuid4(),
        phone_hash=f"hash-{uuid.uuid4().hex[:8]}",
        phone_encrypted=b"enc-phone",
    )
    defaults.update(kwargs)
    return Customer(**defaults)


def make_request(customer_id: uuid.UUID, **kwargs) -> ServiceRequest:
    defaults = dict(
        id=uuid.uuid4(),
        customer_id=customer_id,
        state=RequestState.dispatching,
    )
    defaults.update(kwargs)
    return ServiceRequest(**defaults)


def make_offer(request_id: uuid.UUID, provider_id: uuid.UUID, **kwargs) -> Offer:
    defaults = dict(
        id=uuid.uuid4(),
        request_id=request_id,
        provider_id=provider_id,
        state=OfferState.sent,
        wave=1,
    )
    defaults.update(kwargs)
    return Offer(**defaults)


def grant_credits(provider_id: uuid.UUID, amount: int) -> CreditLedger:
    return CreditLedger(
        provider_id=provider_id,
        kind=LedgerKind.grant_free,
        amount=amount,
        actor="system",
    )


def make_message(**kwargs) -> Message:
    defaults = dict(
        id=uuid.uuid4(),
        meta_message_id=f"wamid.{uuid.uuid4().hex[:16]}",
        direction="inbound",
        sender_phone_hash=f"hash-{uuid.uuid4().hex[:8]}",
        message_type="text",
    )
    defaults.update(kwargs)
    return Message(**defaults)
