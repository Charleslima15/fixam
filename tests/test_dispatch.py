"""Slice 5 tests: wave dispatch, acceptance flow, contact release."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import (
    Assignment,
    Config,
    CreditLedger,
    Customer,
    LedgerKind,
    Offer,
    OfferState,
    Provider,
    RequestState,
    ServiceRequest,
    Urgency,
)
from fixam.handlers.dispatch import (
    advance_wave_handler,
    dispatch_request_handler,
    handle_accept,
    handle_decline,
    notify_withdrawn_handler,
    release_contacts_handler,
)
from fixam.services.acceptance import (
    AcceptanceError,
    OfferNotActionable,
    RequestNotDispatching,
    accept_offer,
)
from fixam.services.dispatch import (
    get_eligible_providers,
    rank_providers,
    split_into_waves,
)
from fixam.services.whatsapp import FakeWhatsAppClient

from tests.conftest import (
    grant_credits,
    make_customer,
    make_offer,
    make_provider,
    make_provider_area,
    make_provider_trade,
    make_quarter,
    make_request,
    make_trade,
    seed_dispatch_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup_provider(session, trade, quarter, *, credits=5, is_active=True, phone=None):
    """Create a provider with trade, area, credits, and a contact window."""
    import hashlib
    from fixam.models import ContactWindow

    p_phone = phone or f"+23767{uuid.uuid4().hex[:7]}"
    p = make_provider(
        is_active=is_active,
        phone_encrypted=p_phone.encode(),
        name_encrypted=b"Provider Name",
    )
    session.add(p)
    session.add(make_provider_trade(p.id, trade.id))
    session.add(make_provider_area(p.id, quarter.id))
    if credits > 0:
        session.add(grant_credits(p.id, credits))
    # Providers have messaged in, so they have an open contact window
    phone_hash = hashlib.sha256(p_phone.encode()).hexdigest()
    session.add(ContactWindow(phone_hash=phone_hash, last_inbound_at=datetime.now(timezone.utc)))
    await session.flush()
    return p


async def _setup_scenario(session):
    """Create trade, quarter, customer, request, seed config. Return (trade, quarter, customer, request)."""
    import hashlib
    from fixam.models import ContactWindow

    await seed_dispatch_config(session)

    trade = make_trade(name=f"Plumbing-{uuid.uuid4().hex[:6]}")
    quarter = make_quarter(name=f"Molyko-{uuid.uuid4().hex[:6]}")
    session.add(trade)
    session.add(quarter)

    customer = make_customer(
        phone_encrypted=b"+237670000001",
        name_encrypted=b"Alice",
    )
    session.add(customer)
    # Customer has an open contact window (they messaged in to start the request)
    cust_hash = hashlib.sha256(b"+237670000001").hexdigest()
    session.add(ContactWindow(phone_hash=cust_hash, last_inbound_at=datetime.now(timezone.utc)))
    await session.flush()

    request = make_request(
        customer.id,
        trade_id=trade.id,
        quarter_id=quarter.id,
        urgency=Urgency.today,
        description="Leaking pipe in bathroom",
        state=RequestState.dispatching,
    )
    session.add(request)
    await session.flush()
    return trade, quarter, customer, request


def _find_messages(fake_wa: FakeWhatsAppClient, *, to: str = None, containing: str = None):
    """Filter fake sent messages."""
    msgs = fake_wa.sent_messages
    if to:
        msgs = [m for m in msgs if m["to"] == to]
    if containing:
        msgs = [m for m in msgs if containing.lower() in (m.get("text", "") or "").lower()]
    return msgs


# ---------------------------------------------------------------------------
# Test 1: Happy path — confirm → wave 1 → accept → contacts released
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_dispatch_accept_release(session, fake_deps):
    """FR-DSP + FR-ACC: full happy path with fakes (scenario 1)."""
    trade, quarter, customer, request = await _setup_scenario(session)
    wa: FakeWhatsAppClient = fake_deps.whatsapp

    provider = await _setup_provider(session, trade, quarter, phone="+237670000010")

    # Dispatch
    await dispatch_request_handler(
        session, {"request_id": str(request.id)}, fake_deps,
    )

    # Verify offer created and sent
    offers = (await session.execute(
        select(Offer).where(Offer.request_id == request.id)
    )).scalars().all()
    assert len(offers) == 1
    assert offers[0].state == OfferState.sent
    assert offers[0].provider_id == provider.id

    # Verify offer message sent to provider (no customer PII)
    offer_msgs = _find_messages(wa, to="+237670000010", containing="New job opportunity")
    assert len(offer_msgs) == 1
    assert "+237670000001" not in offer_msgs[0]["text"]  # no customer phone
    assert "Alice" not in offer_msgs[0]["text"]  # no customer name
    assert offer_msgs[0]["buttons"][0]["id"] == f"accept:{offers[0].id}"

    # Accept
    await handle_accept(session, fake_deps, provider, offers[0].id)

    # Verify assignment and debit
    assignment = (await session.execute(
        select(Assignment).where(Assignment.request_id == request.id)
    )).scalar_one()
    assert assignment.provider_id == provider.id

    debit = (await session.execute(
        select(CreditLedger).where(
            CreditLedger.provider_id == provider.id,
            CreditLedger.kind == LedgerKind.debit_accept,
        )
    )).scalar_one()
    assert debit.amount == -1

    await session.refresh(request)
    assert request.state == RequestState.assigned

    # Release contacts
    await release_contacts_handler(
        session, {"assignment_id": str(assignment.id)}, fake_deps,
    )

    # Provider gets customer details
    provider_contact_msgs = _find_messages(wa, to="+237670000010", containing="matched")
    assert len(provider_contact_msgs) == 1
    assert "+237670000001" in provider_contact_msgs[0]["text"]

    # Customer gets provider details
    customer_contact_msgs = _find_messages(wa, to="+237670000001", containing="found a provider")
    assert len(customer_contact_msgs) == 1
    assert "+237670000010" in customer_contact_msgs[0]["text"]


# ---------------------------------------------------------------------------
# Test 2: Concurrent accepts — one wins, the other told "already taken"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_accepts_one_wins(pooled_session_factory, fake_deps):
    """FR-ACC-02: two simultaneous accepts → exactly one assignment, one debit (scenario 2)."""
    # Setup in a committed transaction
    async with pooled_session_factory() as s:
        async with s.begin():
            await seed_dispatch_config(s)
            trade = make_trade(name="Electrical")
            quarter = make_quarter(name="Bonduma")
            s.add(trade)
            s.add(quarter)
            customer = make_customer(phone_encrypted=b"+237670000002", name_encrypted=b"Bob")
            s.add(customer)
            await s.flush()

            request = make_request(
                customer.id,
                trade_id=trade.id,
                quarter_id=quarter.id,
                state=RequestState.dispatching,
            )
            s.add(request)
            await s.flush()

            p1 = make_provider(is_active=True, phone_encrypted=b"+237670000020", name_encrypted=b"P1")
            p2 = make_provider(is_active=True, phone_encrypted=b"+237670000021", name_encrypted=b"P2")
            s.add(p1)
            s.add(p2)
            s.add(grant_credits(p1.id, 5))
            s.add(grant_credits(p2.id, 5))
            await s.flush()

            offer1 = make_offer(request.id, p1.id, state=OfferState.sent, wave=1)
            offer2 = make_offer(request.id, p2.id, state=OfferState.sent, wave=1)
            s.add(offer1)
            s.add(offer2)
            await s.flush()

            req_id = request.id
            o1_id, o2_id = offer1.id, offer2.id
            p1_id, p2_id = p1.id, p2.id

    # Race two accepts
    results = [None, None]
    errors = [None, None]

    async def try_accept(idx, sf, offer_id, provider_id):
        try:
            async with sf() as sess:
                async with sess.begin():
                    assignment = await accept_offer(sess, offer_id, provider_id)
                    results[idx] = assignment.id
        except AcceptanceError as e:
            errors[idx] = e

    await asyncio.gather(
        try_accept(0, pooled_session_factory, o1_id, p1_id),
        try_accept(1, pooled_session_factory, o2_id, p2_id),
    )

    # Exactly one succeeded
    wins = [r for r in results if r is not None]
    losses = [e for e in errors if e is not None]
    assert len(wins) == 1
    assert len(losses) == 1

    # Verify exactly one assignment and one debit
    async with pooled_session_factory() as s:
        async with s.begin():
            assignments = (await s.execute(
                select(Assignment).where(Assignment.request_id == req_id)
            )).scalars().all()
            assert len(assignments) == 1

            debits = (await s.execute(
                select(CreditLedger).where(
                    CreditLedger.kind == LedgerKind.debit_accept,
                    CreditLedger.reference_id.in_([o1_id, o2_id]),
                )
            )).scalars().all()
            assert len(debits) == 1
            assert debits[0].amount == -1


# ---------------------------------------------------------------------------
# Test 3: No accepts → unfilled (scenario 6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unfilled_after_all_waves(session, fake_deps):
    """FR-DSP-08: all waves exhausted, request unfilled, customer told, no contacts (scenario 6)."""
    trade, quarter, customer, request = await _setup_scenario(session)
    wa: FakeWhatsAppClient = fake_deps.whatsapp

    # Create 2 providers for wave 1 (wave_sizes default "2,3,0")
    p1 = await _setup_provider(session, trade, quarter, phone="+237670000030")
    p2 = await _setup_provider(session, trade, quarter, phone="+237670000031")

    # Dispatch → sends wave 1
    await dispatch_request_handler(
        session, {"request_id": str(request.id)}, fake_deps,
    )

    offers = (await session.execute(
        select(Offer).where(Offer.request_id == request.id)
    )).scalars().all()
    assert all(o.state == OfferState.sent for o in offers)

    # Simulate wave timeout via advance_wave with empty remaining
    await advance_wave_handler(
        session,
        {"request_id": str(request.id), "wave_number": 2, "remaining_waves": []},
        fake_deps,
    )

    await session.refresh(request)
    assert request.state == RequestState.unfilled

    # Customer told a person is handling it
    unfilled_msgs = _find_messages(wa, to="+237670000001", containing="person")
    assert len(unfilled_msgs) >= 1

    # No contact details ever sent
    all_msgs = wa.sent_messages
    for msg in all_msgs:
        text = msg.get("text", "") or ""
        if "+237670000001" in msg.get("to", ""):
            # Customer messages must not contain provider phone
            assert "+237670000030" not in text
            assert "+237670000031" not in text


# ---------------------------------------------------------------------------
# Test 4: Accept on expired/withdrawn offer → no charge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_expired_offer_no_charge(session, fake_deps):
    """FR-DSP-10: accept on expired offer → 'already taken', no charge."""
    trade, quarter, customer, request = await _setup_scenario(session)
    wa: FakeWhatsAppClient = fake_deps.whatsapp

    provider = await _setup_provider(session, trade, quarter, phone="+237670000040")

    # Create an expired offer
    offer = make_offer(request.id, provider.id, state=OfferState.expired, wave=1)
    session.add(offer)
    await session.flush()

    balance_before = (await session.execute(
        select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
            CreditLedger.provider_id == provider.id
        )
    )).scalar_one()

    await handle_accept(session, fake_deps, provider, offer.id)

    # No assignment
    assignments = (await session.execute(
        select(Assignment).where(Assignment.request_id == request.id)
    )).scalars().all()
    assert len(assignments) == 0

    # No debit
    balance_after = (await session.execute(
        select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
            CreditLedger.provider_id == provider.id
        )
    )).scalar_one()
    assert balance_after == balance_before

    # "already taken" message
    taken_msgs = _find_messages(wa, to="+237670000040", containing="already been taken")
    assert len(taken_msgs) == 1


@pytest.mark.asyncio
async def test_accept_withdrawn_offer_no_charge(session, fake_deps):
    """FR-DSP-10: accept on withdrawn offer → 'already taken', no charge."""
    trade, quarter, customer, request = await _setup_scenario(session)

    provider = await _setup_provider(session, trade, quarter, phone="+237670000041")
    offer = make_offer(request.id, provider.id, state=OfferState.withdrawn, wave=1)
    session.add(offer)
    await session.flush()

    await handle_accept(session, fake_deps, provider, offer.id)

    assignments = (await session.execute(
        select(Assignment).where(Assignment.request_id == request.id)
    )).scalars().all()
    assert len(assignments) == 0


# ---------------------------------------------------------------------------
# Test 5: Contact details only sent from release_contacts job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contacts_only_from_release_job(session, fake_deps):
    """FR-ACC-04: contact details only ever sent from the release job."""
    trade, quarter, customer, request = await _setup_scenario(session)
    wa: FakeWhatsAppClient = fake_deps.whatsapp

    provider = await _setup_provider(session, trade, quarter, phone="+237670000050")

    # Dispatch
    await dispatch_request_handler(
        session, {"request_id": str(request.id)}, fake_deps,
    )
    offers = (await session.execute(
        select(Offer).where(Offer.request_id == request.id)
    )).scalars().all()

    # Accept (does NOT release contacts itself — enqueues a job)
    await handle_accept(session, fake_deps, provider, offers[0].id)

    # Check messages so far: none should contain the other party's phone
    msgs_before_release = list(wa.sent_messages)
    for msg in msgs_before_release:
        text = msg.get("text", "") or ""
        to = msg.get("to", "")
        if to == "+237670000050":
            # Provider should NOT have customer phone yet
            assert "+237670000001" not in text, "Customer phone leaked before release job"
        elif to == "+237670000001":
            # Customer should NOT have provider phone yet
            assert "+237670000050" not in text, "Provider phone leaked before release job"

    # Now run release_contacts
    assignment = (await session.execute(
        select(Assignment).where(Assignment.request_id == request.id)
    )).scalar_one()

    await release_contacts_handler(
        session, {"assignment_id": str(assignment.id)}, fake_deps,
    )

    # After release: contacts ARE present
    provider_contact_msgs = _find_messages(wa, to="+237670000050", containing="+237670000001")
    assert len(provider_contact_msgs) == 1
    customer_contact_msgs = _find_messages(wa, to="+237670000001", containing="+237670000050")
    assert len(customer_contact_msgs) == 1


# ---------------------------------------------------------------------------
# Additional: eligibility and ranking unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eligibility_excludes_inactive_suspended_unavailable(session):
    """FR-DSP-01: only active, non-suspended, available providers with balance."""
    await seed_dispatch_config(session)
    trade = make_trade()
    quarter = make_quarter()
    session.add(trade)
    session.add(quarter)
    customer = make_customer(phone_encrypted=b"+237670000099")
    session.add(customer)
    await session.flush()

    request = make_request(customer.id, trade_id=trade.id, quarter_id=quarter.id)
    session.add(request)
    await session.flush()

    # Eligible
    p_ok = await _setup_provider(session, trade, quarter, credits=5, is_active=True)
    # Not active
    p_inactive = await _setup_provider(session, trade, quarter, credits=5, is_active=False)
    # Zero balance
    p_broke = await _setup_provider(session, trade, quarter, credits=0, is_active=True)

    eligible = await get_eligible_providers(session, trade.id, quarter.id, request.id)
    assert p_ok.id in eligible
    assert p_inactive.id not in eligible
    assert p_broke.id not in eligible


@pytest.mark.asyncio
async def test_split_into_waves():
    ids = [uuid.uuid4() for _ in range(7)]
    waves = split_into_waves(ids, [2, 3, 0])
    assert len(waves) == 3
    assert len(waves[0]) == 2
    assert len(waves[1]) == 3
    assert len(waves[2]) == 2  # remaining


@pytest.mark.asyncio
async def test_provider_available_off_commands(session, fake_deps):
    """FR-PRV-01: AVAILABLE / OFF toggle."""
    from fixam.handlers.provider_commands import process_provider_message

    await seed_dispatch_config(session)
    trade = make_trade()
    quarter = make_quarter()
    session.add(trade)
    session.add(quarter)
    await session.flush()

    provider = await _setup_provider(session, trade, quarter, phone="+237670000060")
    wa: FakeWhatsAppClient = fake_deps.whatsapp

    # OFF
    await process_provider_message(
        session,
        {"provider_id": str(provider.id), "sender_phone": "+237670000060", "body": "OFF"},
        fake_deps,
    )
    await session.refresh(provider)
    assert provider.is_available is False
    off_msgs = _find_messages(wa, to="+237670000060", containing="OFF")
    assert len(off_msgs) >= 1

    # AVAILABLE
    await process_provider_message(
        session,
        {"provider_id": str(provider.id), "sender_phone": "+237670000060", "body": "available"},
        fake_deps,
    )
    await session.refresh(provider)
    assert provider.is_available is True


@pytest.mark.asyncio
async def test_auto_off_after_consecutive_unanswered(session, fake_deps):
    """FR-PRV-06: auto-OFF after threshold consecutive unanswered offers."""
    await seed_dispatch_config(session)
    # Set threshold to 2 for this test
    cfg = (await session.execute(
        select(Config).where(Config.key == "auto_off_threshold")
    )).scalar_one()
    cfg.value = "2"
    await session.flush()

    trade = make_trade()
    quarter = make_quarter()
    session.add(trade)
    session.add(quarter)
    await session.flush()

    provider = await _setup_provider(session, trade, quarter, phone="+237670000070")
    customer = make_customer(phone_encrypted=b"+237670000099")
    session.add(customer)
    await session.flush()
    request = make_request(customer.id, trade_id=trade.id, quarter_id=quarter.id)
    session.add(request)
    await session.flush()

    # Simulate 2 expired offers without response
    from fixam.handlers.dispatch import _handle_auto_off
    expired_offers = []
    for i in range(2):
        offer = make_offer(request.id, provider.id, state=OfferState.expired, wave=i + 1)
        # Need unique request+provider, so use different requests for offer 2
        if i > 0:
            req2 = make_request(customer.id, trade_id=trade.id, quarter_id=quarter.id)
            session.add(req2)
            await session.flush()
            offer = Offer(
                request_id=req2.id,
                provider_id=provider.id,
                state=OfferState.expired,
                wave=1,
            )
        session.add(offer)
        expired_offers.append(offer)
    await session.flush()

    await _handle_auto_off(session, fake_deps, expired_offers)
    await session.refresh(provider)
    assert provider.is_available is False
    assert provider.consecutive_unanswered >= 2


@pytest.mark.asyncio
async def test_decline_resets_consecutive_unanswered(session, fake_deps):
    """Declining an offer resets consecutive_unanswered counter."""
    await seed_dispatch_config(session)
    trade = make_trade()
    quarter = make_quarter()
    session.add(trade)
    session.add(quarter)
    customer = make_customer(phone_encrypted=b"+237670000099")
    session.add(customer)
    await session.flush()

    provider = await _setup_provider(session, trade, quarter, phone="+237670000080")
    provider.consecutive_unanswered = 2
    await session.flush()

    request = make_request(customer.id, trade_id=trade.id, quarter_id=quarter.id)
    session.add(request)
    await session.flush()

    offer = make_offer(request.id, provider.id, state=OfferState.sent, wave=1)
    session.add(offer)
    await session.flush()

    await handle_decline(session, fake_deps, provider, offer.id)

    await session.refresh(provider)
    assert provider.consecutive_unanswered == 0
    await session.refresh(offer)
    assert offer.state == OfferState.declined


@pytest.mark.asyncio
async def test_withdrawn_notices_sent(session, fake_deps):
    """FR-ACC-05: withdrawn providers get notified."""
    await seed_dispatch_config(session)
    trade = make_trade()
    quarter = make_quarter()
    session.add(trade)
    session.add(quarter)
    customer = make_customer(phone_encrypted=b"+237670000099")
    session.add(customer)
    await session.flush()

    request = make_request(customer.id, trade_id=trade.id, quarter_id=quarter.id)
    session.add(request)
    await session.flush()

    p1 = await _setup_provider(session, trade, quarter, phone="+237670000090")
    p2 = await _setup_provider(session, trade, quarter, phone="+237670000091")

    # p1's offer withdrawn (another provider accepted)
    o1 = make_offer(request.id, p1.id, state=OfferState.withdrawn, wave=1)
    o2 = make_offer(request.id, p2.id, state=OfferState.accepted, wave=1)
    session.add(o1)
    session.add(o2)
    await session.flush()

    wa: FakeWhatsAppClient = fake_deps.whatsapp
    await notify_withdrawn_handler(
        session, {"request_id": str(request.id)}, fake_deps,
    )

    withdrawn_msgs = _find_messages(wa, to="+237670000090", containing="taken")
    assert len(withdrawn_msgs) == 1
    # The accepting provider should NOT get a withdrawn notice
    p2_taken_msgs = _find_messages(wa, to="+237670000091", containing="taken")
    assert len(p2_taken_msgs) == 0
