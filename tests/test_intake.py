"""Slice 4 tests: intake, AI interface, confirmation, abuse controls."""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fixam.models import (
    Config,
    ContactWindow,
    Customer,
    ModelCallLog,
    Quarter,
    RequestState,
    ServiceRequest,
    Trade,
    TrustTier,
)
from fixam.services.ai import ExtractionResult, FakeAIClient
from fixam.services.intake import (
    BLOCKED_REPLY,
    CAP_REACHED_REPLY,
    GREETING_REPLY,
    REDIRECT_COPY,
    STATUS_REPLY,
    process_customer_message,
)
from fixam.services.prefilter import is_trivial
from fixam.services.transitions import InvalidTransition, transition
from fixam.services.whatsapp import FakeWhatsAppClient


@pytest_asyncio.fixture
async def sf(session_factory) -> async_sessionmaker[AsyncSession]:
    """Alias for session_factory with auto-cleanup of intake-specific tables."""
    yield session_factory
    async with session_factory() as s:
        async with s.begin():
            await s.execute(text(
                "TRUNCATE model_call_log, message, service_request, "
                "contact_window, customer, provider CASCADE"
            ))
            await s.execute(text(
                "DELETE FROM config WHERE key IN ("
                "'daily_model_call_cap','max_open_requests_per_customer',"
                "'daily_request_cap_per_customer','confirmation_expiry_minutes',"
                "'bounded_context_messages')"
            ))


@pytest_asyncio.fixture
async def ref_data(sf):
    """Seed trades and quarters; returns (trades, quarters) lists."""
    async with sf() as s:
        async with s.begin():
            # Clear old reference data left by committed tests
            await s.execute(text("TRUNCATE quarter, trade CASCADE"))
            trades = []
            for name in ("Plumber", "Electrician", "Carpenter"):
                t = Trade(id=uuid.uuid4(), name=name)
                s.add(t)
                trades.append(t)
            quarters = []
            for name in ("Molyko", "Bonduma", "Ndongo"):
                q = Quarter(id=uuid.uuid4(), name=name)
                s.add(q)
                quarters.append(q)
    return {"trades": trades, "quarters": quarters}


# ── Pre-filter (FR-AI-06) ──


class TestPrefilter:
    def test_greetings(self):
        assert is_trivial("Hello") is True
        assert is_trivial("hi") is True
        assert is_trivial("Good morning!") is True
        assert is_trivial("bonjour") is True

    def test_thanks(self):
        assert is_trivial("Thanks!") is True
        assert is_trivial("thank you") is True
        assert is_trivial("merci") is True

    def test_ok_ack(self):
        assert is_trivial("ok") is True
        assert is_trivial("Sure") is True
        assert is_trivial("alright") is True

    def test_emoji_only(self):
        assert is_trivial("\U0001F44D") is True
        assert is_trivial("\U0001F600\U0001F600") is True

    def test_real_request(self):
        assert is_trivial("I need a plumber in Molyko") is False
        assert is_trivial("My pipe is leaking") is False


# ── State transitions (§4.1) ──


class TestTransitions:
    def test_valid_collecting_to_awaiting(self):
        assert (
            transition(RequestState.collecting, RequestState.awaiting_confirmation)
            == RequestState.awaiting_confirmation
        )

    def test_valid_awaiting_to_dispatching(self):
        assert (
            transition(RequestState.awaiting_confirmation, RequestState.dispatching)
            == RequestState.dispatching
        )

    def test_invalid_collecting_to_dispatching(self):
        with pytest.raises(InvalidTransition):
            transition(RequestState.collecting, RequestState.dispatching)

    def test_invalid_expired_to_anything(self):
        with pytest.raises(InvalidTransition):
            transition(RequestState.expired, RequestState.collecting)

    def test_invalid_dispatching_to_collecting(self):
        with pytest.raises(InvalidTransition):
            transition(RequestState.dispatching, RequestState.collecting)

    def test_cancel_from_collecting(self):
        assert (
            transition(RequestState.collecting, RequestState.cancelled)
            == RequestState.cancelled
        )

    def test_cancel_from_dispatching(self):
        assert (
            transition(RequestState.dispatching, RequestState.cancelled)
            == RequestState.cancelled
        )

    def test_invalid_cancel_from_assigned(self):
        with pytest.raises(InvalidTransition):
            transition(RequestState.assigned, RequestState.cancelled)


# ── Scenario 7: provider contacts → redirect, no provider data in model ──


@pytest.mark.asyncio
async def test_provider_contacts_redirect_FR_INT_09(sf, ref_data):
    """Requesting provider contacts must be redirected; model must never see provider data."""
    wa = FakeWhatsAppClient()
    ai = FakeAIClient()
    phone = "+237670000001"

    async with sf() as s:
        async with s.begin():
            await process_customer_message(
                s, phone, "Give me numbers for plumbers please", ai, wa,
            )

    assert len(wa.sent_messages) == 1
    assert REDIRECT_COPY in wa.sent_messages[0]["text"]
    assert len(ai.calls) == 0


@pytest.mark.asyncio
async def test_model_never_receives_provider_data_FR_AI_03(sf, ref_data):
    """When the model IS called, its input must contain no provider data."""
    from fixam.models import Provider

    async with sf() as s:
        async with s.begin():
            provider = Provider(
                id=uuid.uuid4(),
                phone_hash="provhash123",
                name_encrypted=b"John Plumber",
                phone_encrypted=b"+237670099999",
            )
            s.add(provider)

    wa = FakeWhatsAppClient()
    ai = FakeAIClient()
    ai.set_responses(
        ExtractionResult(
            is_service_request=True,
            trade="Plumber",
            area="Molyko",
            urgency="today",
            description="Leaking pipe",
        )
    )
    phone = "+237670000002"

    async with sf() as s:
        async with s.begin():
            await process_customer_message(
                s, phone, "I need a plumber in Molyko, leaking pipe", ai, wa,
            )

    assert len(ai.calls) == 1
    call = ai.calls[0]
    all_input = " ".join(call["messages"]) + " ".join(call["trades"]) + " ".join(call["quarters"])
    assert "John Plumber" not in all_input
    assert "+237670099999" not in all_input
    assert "provhash123" not in all_input


# ── Scenario 8: model call cap (FR-AI-07) ──


@pytest.mark.asyncio
async def test_model_cap_stops_calls_replies_continue_FR_AI_07(sf, ref_data):
    """Messages beyond daily cap → model calls stop, replies continue."""
    wa = FakeWhatsAppClient()
    ai = FakeAIClient()
    phone = "+237670000003"
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()

    async with sf() as s:
        async with s.begin():
            s.add(Config(key="daily_model_call_cap", value="5"))
            for _ in range(5):
                s.add(ModelCallLog(
                    id=uuid.uuid4(),
                    phone_hash=phone_hash,
                    input_size=10,
                    output=None,
                    latency_ms=100,
                    cost_estimate_fcfa=1,
                ))

    ai.set_responses(ExtractionResult(is_service_request=True, trade="Plumber"))

    async with sf() as s:
        async with s.begin():
            await process_customer_message(s, phone, "I need a plumber", ai, wa)

    assert len(ai.calls) == 0
    assert len(wa.sent_messages) >= 1
    sent_texts = [m.get("text", "") for m in wa.sent_messages]
    assert any(CAP_REACHED_REPLY in t for t in sent_texts)


# ── Scenario 12: AI down → button-driven fallback (NFR-REL-02) ──


@pytest.mark.asyncio
async def test_ai_down_fallback_to_buttons_NFR_REL_02(sf, ref_data):
    """When AI interface errors, intake completes via button-driven fallback."""
    wa = FakeWhatsAppClient()
    ai = FakeAIClient()
    phone = "+237670000004"

    # AI always fails (need 2 errors for the retry)
    ai.set_responses(RuntimeError("AI unavailable"), RuntimeError("AI unavailable"))

    # Step 1: Customer sends initial message — AI fails, fallback starts
    async with sf() as s:
        async with s.begin():
            await process_customer_message(
                s, phone, "I need help with my plumbing", ai, wa,
            )

    assert len(wa.sent_messages) >= 1
    last_msg = wa.sent_messages[-1]
    assert last_msg.get("buttons") is not None
    assert any("trade_" in b["id"] for b in last_msg["buttons"])

    # Step 2: Customer selects trade via button
    wa.sent_messages.clear()
    async with sf() as s:
        async with s.begin():
            await process_customer_message(
                s, phone, "", ai, wa, button_reply_id="trade_plumber",
            )

    assert len(wa.sent_messages) >= 1
    last_msg = wa.sent_messages[-1]
    assert last_msg.get("buttons") is not None
    assert any("area_" in b["id"] for b in last_msg["buttons"])

    # Step 3: Customer selects area via button
    wa.sent_messages.clear()
    async with sf() as s:
        async with s.begin():
            await process_customer_message(
                s, phone, "", ai, wa, button_reply_id="area_molyko",
            )

    assert len(wa.sent_messages) >= 1
    last_msg = wa.sent_messages[-1]
    assert last_msg.get("buttons") is not None
    assert any(b["id"] == "confirm_yes" for b in last_msg["buttons"])

    # Step 4: Customer confirms
    wa.sent_messages.clear()
    async with sf() as s:
        async with s.begin():
            await process_customer_message(
                s, phone, "", ai, wa, button_reply_id="confirm_yes",
            )

    phone_hash = hashlib.sha256(phone.encode()).hexdigest()
    async with sf() as s:
        result = await s.execute(
            select(ServiceRequest)
            .join(Customer)
            .where(Customer.phone_hash == phone_hash)
            .order_by(ServiceRequest.created_at.desc())
        )
        req = result.scalar_one()
        assert req.state == RequestState.dispatching


# ── Invalid state transitions raise ──


def test_invalid_state_transition_on_service_request():
    with pytest.raises(InvalidTransition):
        transition(RequestState.collecting, RequestState.dispatching)
    with pytest.raises(InvalidTransition):
        transition(RequestState.expired, RequestState.collecting)
    with pytest.raises(InvalidTransition):
        transition(RequestState.closed, RequestState.dispatching)
    with pytest.raises(InvalidTransition):
        transition(RequestState.assigned, RequestState.cancelled)


# ── Happy path: full intake conversation ──


@pytest.mark.asyncio
async def test_full_intake_happy_path(sf, ref_data):
    """Customer sends request → AI extracts → confirmation → dispatching."""
    wa = FakeWhatsAppClient()
    ai = FakeAIClient()
    phone = "+237670000005"

    ai.set_responses(
        ExtractionResult(
            is_service_request=True,
            trade="Plumber",
            area="Molyko",
            urgency="today",
            description="Leaking pipe in bathroom",
            language="en",
            confidence=0.95,
        )
    )

    async with sf() as s:
        async with s.begin():
            await process_customer_message(
                s, phone, "I need a plumber in Molyko, my pipe is leaking", ai, wa,
            )

    assert len(wa.sent_messages) >= 1
    last_msg = wa.sent_messages[-1]
    assert "Plumber" in last_msg.get("text", "")
    assert "Molyko" in last_msg.get("text", "")
    assert last_msg.get("buttons") is not None

    # Customer confirms
    wa.sent_messages.clear()
    async with sf() as s:
        async with s.begin():
            await process_customer_message(
                s, phone, "", ai, wa, button_reply_id="confirm_yes",
            )

    phone_hash = hashlib.sha256(phone.encode()).hexdigest()
    async with sf() as s:
        result = await s.execute(
            select(ServiceRequest)
            .join(Customer)
            .where(Customer.phone_hash == phone_hash)
        )
        req = result.scalar_one()
        assert req.state == RequestState.dispatching
        assert req.confirmed_at is not None
        assert req.trade_id is not None
        assert req.quarter_id is not None


# ── Blocked customer (FR-ABU-04) ──


@pytest.mark.asyncio
async def test_blocked_customer_gets_neutral_reply(sf, ref_data):
    wa = FakeWhatsAppClient()
    ai = FakeAIClient()
    phone = "+237670000006"
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()

    async with sf() as s:
        async with s.begin():
            customer = Customer(
                id=uuid.uuid4(),
                phone_hash=phone_hash,
                phone_encrypted=phone.encode(),
                trust_tier=TrustTier.blocked,
            )
            s.add(customer)

    async with sf() as s:
        async with s.begin():
            await process_customer_message(s, phone, "I need a plumber", ai, wa)

    assert len(wa.sent_messages) == 1
    assert BLOCKED_REPLY in wa.sent_messages[0]["text"]
    assert len(ai.calls) == 0


# ── Greeting without open request (FR-AI-06) ──


@pytest.mark.asyncio
async def test_greeting_no_model_call(sf, ref_data):
    wa = FakeWhatsAppClient()
    ai = FakeAIClient()
    phone = "+237670000007"

    async with sf() as s:
        async with s.begin():
            await process_customer_message(s, phone, "Hello!", ai, wa)

    assert len(ai.calls) == 0
    assert len(wa.sent_messages) == 1
    assert GREETING_REPLY in wa.sent_messages[0]["text"]


# ── Messages after confirmation get status reply (FR-INT-07) ──


@pytest.mark.asyncio
async def test_post_confirmation_status_reply_FR_INT_07(sf, ref_data):
    wa = FakeWhatsAppClient()
    ai = FakeAIClient()
    phone = "+237670000008"
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()

    async with sf() as s:
        async with s.begin():
            customer = Customer(
                id=uuid.uuid4(),
                phone_hash=phone_hash,
                phone_encrypted=phone.encode(),
            )
            s.add(customer)
            await s.flush()
            req = ServiceRequest(
                id=uuid.uuid4(),
                customer_id=customer.id,
                state=RequestState.dispatching,
                confirmed_at=datetime.now(timezone.utc),
            )
            s.add(req)

    async with sf() as s:
        async with s.begin():
            await process_customer_message(s, phone, "Any update?", ai, wa)

    assert len(ai.calls) == 0
    assert len(wa.sent_messages) == 1
    assert STATUS_REPLY in wa.sent_messages[0]["text"]


# ── Clarifying question (FR-INT-03) ──


@pytest.mark.asyncio
async def test_clarifying_question_for_missing_trade(sf, ref_data):
    wa = FakeWhatsAppClient()
    ai = FakeAIClient()
    phone = "+237670000009"

    ai.set_responses(
        ExtractionResult(
            is_service_request=True,
            trade=None,
            area="Molyko",
            urgency="today",
            description="Something is broken",
        )
    )

    async with sf() as s:
        async with s.begin():
            await process_customer_message(
                s, phone, "Something is broken in my house", ai, wa,
            )

    assert len(wa.sent_messages) >= 1
    last_msg = wa.sent_messages[-1]
    assert "service" in last_msg.get("text", "").lower()
    assert last_msg.get("buttons") is not None


# ── Model call logging (FR-AI-10) ──


@pytest.mark.asyncio
async def test_model_call_logged_FR_AI_10(sf, ref_data):
    wa = FakeWhatsAppClient()
    ai = FakeAIClient()
    phone = "+237670000010"
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()

    ai.set_responses(
        ExtractionResult(
            is_service_request=True,
            trade="Plumber",
            area="Molyko",
            urgency="now",
            description="Emergency leak",
        )
    )

    async with sf() as s:
        async with s.begin():
            await process_customer_message(
                s, phone, "Emergency plumber needed in Molyko", ai, wa,
            )

    async with sf() as s:
        result = await s.execute(
            select(ModelCallLog).where(ModelCallLog.phone_hash == phone_hash)
        )
        logs = result.scalars().all()
        assert len(logs) == 1
        log = logs[0]
        assert log.input_size > 0
        assert log.latency_ms >= 0
        assert log.cost_estimate_fcfa >= 1
        assert log.output is not None
        assert log.error is False


# ── Expiry handler (FR-INT-06) ──


@pytest.mark.asyncio
async def test_expire_unconfirmed_FR_INT_06(sf, ref_data):
    from fixam.handlers.expiry import expire_unconfirmed
    from fixam.services.deps import Deps
    from fixam.services.media import FakeMediaStore

    cust_id = uuid.uuid4()
    req_id = uuid.uuid4()

    async with sf() as s:
        async with s.begin():
            s.add(Customer(
                id=cust_id,
                phone_hash="expirehash",
                phone_encrypted=b"phone",
            ))
            await s.flush()
            req = ServiceRequest(
                id=req_id,
                customer_id=cust_id,
                state=RequestState.awaiting_confirmation,
            )
            s.add(req)

    # Set updated_at to old time
    async with sf() as s:
        async with s.begin():
            from sqlalchemy import update
            await s.execute(
                update(ServiceRequest)
                .where(ServiceRequest.id == req_id)
                .values(updated_at=datetime.now(timezone.utc) - timedelta(minutes=60))
            )

    deps = Deps(
        whatsapp=FakeWhatsAppClient(),
        media=FakeMediaStore(),
        ai=FakeAIClient(),
    )

    async with sf() as s:
        async with s.begin():
            await expire_unconfirmed(s, {}, deps)

    async with sf() as s:
        req = await s.get(ServiceRequest, req_id)
        assert req.state == RequestState.expired


# ── Default area from last confirmed (FR-INT-04) ──


@pytest.mark.asyncio
async def test_default_area_from_last_confirmed_FR_INT_04(sf, ref_data):
    wa = FakeWhatsAppClient()
    ai = FakeAIClient()
    phone = "+237670000012"
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()

    molyko = ref_data["quarters"][0]

    async with sf() as s:
        async with s.begin():
            customer = Customer(
                id=uuid.uuid4(),
                phone_hash=phone_hash,
                phone_encrypted=phone.encode(),
                last_area_id=molyko.id,
            )
            s.add(customer)

    ai.set_responses(
        ExtractionResult(
            is_service_request=True,
            trade="Plumber",
            area=None,
            urgency="today",
            description="Pipe issue",
        )
    )

    async with sf() as s:
        async with s.begin():
            await process_customer_message(
                s, phone, "I need a plumber, pipe issue", ai, wa,
            )

    assert len(wa.sent_messages) >= 1
    last_msg = wa.sent_messages[-1]
    assert "Molyko" in last_msg.get("text", "")
    assert last_msg.get("buttons") is not None
    assert any(b["id"] == "confirm_yes" for b in last_msg["buttons"])
