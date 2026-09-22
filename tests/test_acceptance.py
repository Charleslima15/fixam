"""Tests for the credit ledger and acceptance transaction.

Covers FR-LED-01, FR-LED-04, FR-ACC-01, FR-ACC-02.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import (
    Assignment,
    CreditLedger,
    LedgerKind,
    Offer,
    OfferState,
    RequestState,
    ServiceRequest,
)
from fixam.services.acceptance import (
    AcceptanceError,
    InsufficientBalance,
    OfferNotActionable,
    OfferNotFound,
    RequestNotDispatching,
    accept_offer,
)
from tests.conftest import (
    grant_credits,
    make_customer,
    make_offer,
    make_provider,
    make_request,
)


# ---------------------------------------------------------------------------
# FR-LED-01: credit_ledger is append-only (database-enforced)
# ---------------------------------------------------------------------------

class TestLedgerAppendOnly:
    async def test_update_blocked(self, session_factory):
        """FR-LED-01: UPDATE on credit_ledger must raise."""
        async with session_factory() as session:
            async with session.begin():
                provider = make_provider()
                session.add(provider)
                entry = grant_credits(provider.id, 5)
                session.add(entry)
                await session.flush()

            async with session.begin():
                with pytest.raises(Exception, match="append-only"):
                    await session.execute(
                        update(CreditLedger)
                        .where(CreditLedger.id == entry.id)
                        .values(amount=100)
                    )

    async def test_delete_blocked(self, session_factory):
        """FR-LED-01: DELETE on credit_ledger must raise."""
        async with session_factory() as session:
            async with session.begin():
                provider = make_provider()
                session.add(provider)
                entry = grant_credits(provider.id, 5)
                session.add(entry)
                await session.flush()

            async with session.begin():
                with pytest.raises(Exception, match="append-only"):
                    await session.execute(
                        text("DELETE FROM credit_ledger WHERE id = :id"),
                        {"id": str(entry.id)},
                    )

    async def test_insert_allowed(self, session_factory):
        """FR-LED-01: INSERT on credit_ledger must succeed."""
        async with session_factory() as session:
            async with session.begin():
                provider = make_provider()
                session.add(provider)
                entry = grant_credits(provider.id, 5)
                session.add(entry)
                await session.flush()

                balance = (await session.execute(
                    select(func.sum(CreditLedger.amount)).where(
                        CreditLedger.provider_id == provider.id
                    )
                )).scalar_one()
                assert balance == 5


# ---------------------------------------------------------------------------
# FR-LED-04: balance must never go below zero
# ---------------------------------------------------------------------------

class TestBalanceNonNegative:
    async def test_accept_with_zero_balance_rejected(self, session_factory):
        """FR-LED-04: acceptance must fail when balance is 0."""
        async with session_factory() as session:
            async with session.begin():
                provider = make_provider()
                customer = make_customer()
                session.add_all([provider, customer])
                req = make_request(customer.id)
                session.add(req)
                offer = make_offer(req.id, provider.id)
                session.add(offer)
                await session.flush()

                with pytest.raises(InsufficientBalance):
                    await accept_offer(session, offer.id, provider.id)

    async def test_accept_with_one_credit_succeeds(self, session_factory):
        """FR-LED-04: acceptance succeeds with exactly 1 credit."""
        async with session_factory() as session:
            async with session.begin():
                provider = make_provider()
                customer = make_customer()
                session.add_all([provider, customer])
                session.add(grant_credits(provider.id, 1))
                req = make_request(customer.id)
                session.add(req)
                offer = make_offer(req.id, provider.id)
                session.add(offer)
                await session.flush()

                assignment = await accept_offer(session, offer.id, provider.id)
                await session.flush()

                assert assignment.provider_id == provider.id

                balance = (await session.execute(
                    select(func.sum(CreditLedger.amount)).where(
                        CreditLedger.provider_id == provider.id
                    )
                )).scalar_one()
                assert balance == 0


# ---------------------------------------------------------------------------
# FR-ACC-01: acceptance transaction atomicity
# ---------------------------------------------------------------------------

class TestAcceptanceTransaction:
    async def test_happy_path(self, session_factory):
        """FR-ACC-01: successful acceptance creates assignment, debits, and
        updates offer/request states."""
        async with session_factory() as session:
            async with session.begin():
                provider = make_provider()
                customer = make_customer()
                session.add_all([provider, customer])
                session.add(grant_credits(provider.id, 5))
                req = make_request(customer.id)
                session.add(req)
                provider_b = make_provider()
                session.add(provider_b)
                offer_a = make_offer(req.id, provider.id)
                offer_b = make_offer(req.id, provider_b.id)
                session.add_all([offer_a, offer_b])
                await session.flush()

                assignment = await accept_offer(session, offer_a.id, provider.id)
                await session.flush()

                assert assignment.request_id == req.id
                assert assignment.offer_id == offer_a.id

                await session.refresh(offer_a)
                assert offer_a.state == OfferState.accepted

                await session.refresh(offer_b)
                assert offer_b.state == OfferState.withdrawn

                await session.refresh(req)
                assert req.state == RequestState.assigned

                debits = (await session.execute(
                    select(func.count()).select_from(CreditLedger).where(
                        CreditLedger.provider_id == provider.id,
                        CreditLedger.kind == LedgerKind.debit_accept,
                    )
                )).scalar_one()
                assert debits == 1

    async def test_wrong_provider_rejected(self, session_factory):
        """FR-ACC-01: offer/provider mismatch raises OfferNotFound."""
        async with session_factory() as session:
            async with session.begin():
                provider = make_provider()
                customer = make_customer()
                session.add_all([provider, customer])
                req = make_request(customer.id)
                session.add(req)
                offer = make_offer(req.id, provider.id)
                session.add(offer)
                await session.flush()

                with pytest.raises(OfferNotFound):
                    await accept_offer(session, offer.id, uuid.uuid4())

    async def test_offer_already_accepted_rejected(self, session_factory):
        """FR-ACC-01: offer not in 'sent' state raises OfferNotActionable."""
        async with session_factory() as session:
            async with session.begin():
                provider = make_provider()
                customer = make_customer()
                session.add_all([provider, customer])
                session.add(grant_credits(provider.id, 5))
                req = make_request(customer.id)
                session.add(req)
                offer = make_offer(req.id, provider.id, state=OfferState.declined)
                session.add(offer)
                await session.flush()

                with pytest.raises(OfferNotActionable):
                    await accept_offer(session, offer.id, provider.id)

    async def test_request_not_dispatching_rejected(self, session_factory):
        """FR-ACC-01: request not in 'dispatching' raises RequestNotDispatching."""
        async with session_factory() as session:
            async with session.begin():
                provider = make_provider()
                customer = make_customer()
                session.add_all([provider, customer])
                session.add(grant_credits(provider.id, 5))
                req = make_request(customer.id, state=RequestState.assigned)
                session.add(req)
                offer = make_offer(req.id, provider.id)
                session.add(offer)
                await session.flush()

                with pytest.raises(RequestNotDispatching):
                    await accept_offer(session, offer.id, provider.id)


# ---------------------------------------------------------------------------
# FR-ACC-02: concurrent acceptance — exactly one winner
# ---------------------------------------------------------------------------

class TestConcurrentAcceptance:
    async def test_two_simultaneous_accepts_one_wins(self, session_factory):
        """FR-ACC-02: two concurrent accepts on the same request produce
        exactly one assignment and one debit. Uses separate DB connections."""
        # --- setup ---
        async with session_factory() as setup_session:
            async with setup_session.begin():
                provider_a = make_provider()
                provider_b = make_provider()
                customer = make_customer()
                setup_session.add_all([provider_a, provider_b, customer])
                setup_session.add(grant_credits(provider_a.id, 5))
                setup_session.add(grant_credits(provider_b.id, 5))
                req = make_request(customer.id)
                setup_session.add(req)
                offer_a = make_offer(req.id, provider_a.id)
                offer_b = make_offer(req.id, provider_b.id)
                setup_session.add_all([offer_a, offer_b])

        # --- concurrent accepts ---
        async def do_accept(offer_id, provider_id):
            async with session_factory() as s:
                async with s.begin():
                    return await accept_offer(s, offer_id, provider_id)

        results = await asyncio.gather(
            do_accept(offer_a.id, provider_a.id),
            do_accept(offer_b.id, provider_b.id),
            return_exceptions=True,
        )

        successes = [r for r in results if isinstance(r, Assignment)]
        failures = [r for r in results if isinstance(r, AcceptanceError)]
        assert len(successes) == 1, f"Expected 1 success, got {successes}"
        assert len(failures) == 1, f"Expected 1 failure, got {failures}"

        # --- verify DB state ---
        async with session_factory() as verify_session:
            assignment_count = (await verify_session.execute(
                select(func.count()).select_from(Assignment).where(
                    Assignment.request_id == req.id
                )
            )).scalar_one()
            assert assignment_count == 1

            debit_count = (await verify_session.execute(
                select(func.count()).select_from(CreditLedger).where(
                    CreditLedger.kind == LedgerKind.debit_accept,
                    CreditLedger.reference_id.in_([offer_a.id, offer_b.id]),
                )
            )).scalar_one()
            assert debit_count == 1

            winner = successes[0]
            loser_provider_id = (
                provider_b.id if winner.provider_id == provider_a.id else provider_a.id
            )
            loser_balance = (await verify_session.execute(
                select(func.sum(CreditLedger.amount)).where(
                    CreditLedger.provider_id == loser_provider_id
                )
            )).scalar_one()
            assert loser_balance == 5
