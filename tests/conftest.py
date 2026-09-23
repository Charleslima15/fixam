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
    Config,
    CreditLedger,
    Customer,
    LedgerKind,
    Message,
    Offer,
    OfferState,
    Payment,
    PaymentState,
    Provider,
    ProviderArea,
    ProviderTrade,
    Quarter,
    RequestState,
    ServiceRequest,
    Trade,
)
from fixam.services.ai import FakeAIClient
from fixam.services.deps import Deps
from fixam.services.momo import FakeMoMoClient
from fixam.services.whatsapp import FakeWhatsAppClient
from fixam.services.media import FakeMediaStore

_schema_created = False


def _kill_idle_transactions(async_url: str) -> None:
    """Terminate any PostgreSQL backends stuck 'idle in transaction'."""
    eng = create_engine(_sync_url(async_url))
    try:
        with eng.connect() as conn:
            conn.execute(text(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND pid != pg_backend_pid() "
                "AND state = 'idle in transaction'"
            ))
            conn.commit()
    except Exception:
        pass
    finally:
        eng.dispose()


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
    with eng.begin() as conn:
        for cfg in DISPATCH_CONFIG:
            conn.execute(
                text(
                    "INSERT INTO config (key, value) VALUES (:k, :v) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"k": cfg.key, "v": cfg.value},
            )
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
    _kill_idle_transactions(db_url)


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
    sess = session_factory()
    try:
        await sess.begin()
        yield sess
    finally:
        try:
            await sess.rollback()
        except Exception:
            pass
        try:
            await sess.close()
        except Exception:
            pass


@pytest_asyncio.fixture
async def fake_deps():
    return Deps(
        whatsapp=FakeWhatsAppClient(),
        media=FakeMediaStore(),
        ai=FakeAIClient(),
        momo=FakeMoMoClient(),
    )


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


def make_trade(**kwargs) -> Trade:
    defaults = dict(id=uuid.uuid4(), name=f"trade-{uuid.uuid4().hex[:6]}")
    defaults.update(kwargs)
    return Trade(**defaults)


def make_quarter(**kwargs) -> Quarter:
    defaults = dict(id=uuid.uuid4(), name=f"quarter-{uuid.uuid4().hex[:6]}")
    defaults.update(kwargs)
    return Quarter(**defaults)


def make_provider_trade(provider_id: uuid.UUID, trade_id: uuid.UUID) -> ProviderTrade:
    return ProviderTrade(provider_id=provider_id, trade_id=trade_id)


def make_provider_area(provider_id: uuid.UUID, quarter_id: uuid.UUID) -> ProviderArea:
    return ProviderArea(provider_id=provider_id, quarter_id=quarter_id)


DISPATCH_CONFIG = [
    Config(key="wave_sizes", value="2,3,0"),
    Config(key="wave_sizes_now", value="3,5,0"),
    Config(key="wave_sizes_established", value="2,3,0"),
    Config(key="wave_timeout_seconds", value="300"),
    Config(key="wave_timeout_seconds_now", value="180"),
    Config(key="cold_start_offer_cap", value="3"),
    Config(key="auto_off_threshold", value="3"),
    Config(key="bundle_default", value='{"credits": 10, "price_fcfa": 5000}'),
    Config(key="bundle_first_purchase", value='{"credits": 3, "price_fcfa": 1500, "first_purchase_only": true}'),
    Config(key="free_credit_cap", value="5"),
    Config(key="payment_poll_after_seconds", value="120"),
    Config(key="payment_stuck_after_seconds", value="900"),
    Config(key="low_balance_threshold", value="1"),
]


def make_payment(provider_id: uuid.UUID, **kwargs) -> Payment:
    defaults = dict(
        id=uuid.uuid4(),
        provider_id=provider_id,
        our_reference=str(uuid.uuid4()),
        amount_fcfa=5000,
        credits=10,
        state=PaymentState.pending,
    )
    defaults.update(kwargs)
    return Payment(**defaults)


async def seed_dispatch_config(session: AsyncSession) -> None:
    """No-op: config rows are seeded once in _ensure_schema via sync connection."""
    pass
