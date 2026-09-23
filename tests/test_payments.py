"""Slice 6 tests: payments, free credits, BALANCE, TOP UP."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import (
    Config,
    ContactWindow,
    CreditLedger,
    LedgerKind,
    Payment,
    PaymentState,
)
from fixam.services.payments import (
    Bundle,
    confirm_payment,
    get_bundles,
    get_free_credit_remainder,
    get_provider_balance,
    grant_activation_credits,
    initiate_payment,
    poll_pending_payments,
    remove_free_credits,
)
from fixam.services.acceptance import accept_offer
from fixam.handlers.provider_commands import process_provider_message

from tests.conftest import (
    grant_credits,
    make_customer,
    make_offer,
    make_payment,
    make_provider,
    make_request,
)

pytestmark = pytest.mark.asyncio


def _ensure_window(session, phone: str):
    """Insert a ContactWindow so send_outbound uses free-form text."""
    import hashlib
    from datetime import datetime, timezone
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()
    window = ContactWindow(
        phone_hash=phone_hash,
        last_inbound_at=datetime.now(timezone.utc),
    )
    session.add(window)


class TestHappyPathPurchase:
    """Scenario 1: initiate → verify via GET → credits written."""

    async def test_initiate_and_confirm(self, session: AsyncSession, fake_deps):
        provider = make_provider(phone_encrypted=b"237600000001")
        session.add(provider)
        _ensure_window(session, provider.phone_encrypted.decode())
        await session.flush()

        bundle = Bundle(key="default", credits=10, price_fcfa=5000, first_purchase_only=False)
        payment = await initiate_payment(session, fake_deps, provider, bundle, "237600000001")
        await session.flush()

        assert payment.state == PaymentState.pending
        assert len(fake_deps.momo.requests) == 1
        assert fake_deps.momo.requests[0]["amount"] == 5000

        # Confirm via GET verification
        await confirm_payment(session, fake_deps, payment.id)
        await session.flush()

        assert payment.state == PaymentState.succeeded
        assert payment.mtn_reference is not None

        count = (await session.execute(
            select(func.count()).select_from(CreditLedger).where(
                CreditLedger.provider_id == provider.id,
                CreditLedger.kind == LedgerKind.purchase,
            )
        )).scalar_one()
        assert count == 1

        balance = await get_provider_balance(session, provider.id)
        assert balance == 10


class TestDuplicateSuccess:
    """Scenario 2 (FR-PAY-07): duplicate success → one purchase entry."""

    async def test_duplicate_callback_is_noop(self, session: AsyncSession, fake_deps):
        provider = make_provider(phone_encrypted=b"237600000002")
        session.add(provider)
        _ensure_window(session, provider.phone_encrypted.decode())
        await session.flush()

        payment = make_payment(provider.id, state=PaymentState.pending)
        session.add(payment)
        await session.flush()

        # First confirm
        await confirm_payment(session, fake_deps, payment.id)
        await session.flush()
        assert payment.state == PaymentState.succeeded

        # Second confirm — should be no-op
        await confirm_payment(session, fake_deps, payment.id)
        await session.flush()

        count = (await session.execute(
            select(func.count()).select_from(CreditLedger).where(
                CreditLedger.provider_id == provider.id,
                CreditLedger.kind == LedgerKind.purchase,
            )
        )).scalar_one()
        assert count == 1


class TestPollingResolves:
    """Scenario 3: no callback → polling resolves payment."""

    async def test_poll_finds_and_confirms(self, session: AsyncSession, fake_deps):
        provider = make_provider(phone_encrypted=b"237600000003")
        session.add(provider)
        _ensure_window(session, provider.phone_encrypted.decode())
        await session.flush()

        payment = make_payment(provider.id, state=PaymentState.pending)
        session.add(payment)
        await session.flush()

        # Backdate updated_at so poll picks it up
        from sqlalchemy import update, text
        await session.execute(
            update(Payment).where(Payment.id == payment.id).values(
                updated_at=text("now() - interval '300 seconds'")
            )
        )
        await session.flush()
        await session.refresh(payment)

        await poll_pending_payments(session, fake_deps)
        await session.flush()

        await session.refresh(payment)
        assert payment.state == PaymentState.succeeded

        balance = await get_provider_balance(session, provider.id)
        assert balance == payment.credits


class TestFailedPayment:
    """Scenario 4: failed/declined → no credits."""

    async def test_failed_payment_no_credits(self, session: AsyncSession, fake_deps):
        provider = make_provider(phone_encrypted=b"237600000004")
        session.add(provider)
        _ensure_window(session, provider.phone_encrypted.decode())
        await session.flush()

        payment = make_payment(provider.id, state=PaymentState.pending)
        session.add(payment)
        await session.flush()

        fake_deps.momo.set_status(payment.our_reference, {
            "status": "FAILED",
            "reason": "PAYER_NOT_FOUND",
        })

        await confirm_payment(session, fake_deps, payment.id)
        await session.flush()

        assert payment.state == PaymentState.failed

        count = (await session.execute(
            select(func.count()).select_from(CreditLedger).where(
                CreditLedger.provider_id == provider.id,
                CreditLedger.kind == LedgerKind.purchase,
            )
        )).scalar_one()
        assert count == 0


class TestFreeCreditRemoval:
    """Scenario 5: partial use → adjustment removes only what won't go negative."""

    async def test_remove_after_partial_use(self, session: AsyncSession, fake_deps):
        provider = make_provider(phone_encrypted=b"237600000005")
        session.add(provider)
        _ensure_window(session, provider.phone_encrypted.decode())
        await session.flush()

        # Grant 5 free credits
        await grant_activation_credits(session, provider.id)
        await session.flush()

        # Use 2 (simulate debit_accept)
        for _ in range(2):
            session.add(CreditLedger(
                provider_id=provider.id,
                kind=LedgerKind.debit_accept,
                amount=-1,
                reference_id=uuid.uuid4(),
                reference_type="offer",
                actor="system",
            ))
        await session.flush()

        balance_before = await get_provider_balance(session, provider.id)
        assert balance_before == 3

        removed = await remove_free_credits(session, fake_deps, provider.id)
        await session.flush()

        assert removed is True

        # Balance capped at 0, not negative
        balance_after = await get_provider_balance(session, provider.id)
        assert balance_after == 0

        # Adjustment should be -3 (min of free_remainder=5, balance=3)
        adj = (await session.execute(
            select(CreditLedger).where(
                CreditLedger.provider_id == provider.id,
                CreditLedger.kind == LedgerKind.adjustment,
            )
        )).scalars().all()
        assert len(adj) == 1
        assert adj[0].amount == -3
        assert adj[0].note == "first job confirmed"


class TestFreeCreditRemovalAllSpent:
    """Scenario 6: all free credits spent → no adjustment (balance is 0)."""

    async def test_no_adjustment_when_all_spent(self, session: AsyncSession, fake_deps):
        provider = make_provider(phone_encrypted=b"237600000006")
        session.add(provider)
        _ensure_window(session, provider.phone_encrypted.decode())
        await session.flush()

        # Grant 5 free credits
        await grant_activation_credits(session, provider.id)
        await session.flush()

        # Use all 5
        for _ in range(5):
            session.add(CreditLedger(
                provider_id=provider.id,
                kind=LedgerKind.debit_accept,
                amount=-1,
                reference_id=uuid.uuid4(),
                reference_type="offer",
                actor="system",
            ))
        await session.flush()

        balance = await get_provider_balance(session, provider.id)
        assert balance == 0

        removed = await remove_free_credits(session, fake_deps, provider.id)
        await session.flush()

        # Balance is 0, so min(remainder=5, balance=0) = 0 → no adjustment
        assert removed is False

        adj_count = (await session.execute(
            select(func.count()).select_from(CreditLedger).where(
                CreditLedger.provider_id == provider.id,
                CreditLedger.kind == LedgerKind.adjustment,
            )
        )).scalar_one()
        assert adj_count == 0


class TestBalanceCommand:
    """Scenario 7: BALANCE returns correct info."""

    async def test_balance_with_free_credits(self, session: AsyncSession, fake_deps):
        provider = make_provider(phone_encrypted=b"237600000007")
        session.add(provider)
        _ensure_window(session, provider.phone_encrypted.decode())
        await session.flush()

        session.add(grant_credits(provider.id, 5))
        await session.flush()

        payload = {
            "provider_id": str(provider.id),
            "sender_phone": "237600000007",
            "body": "BALANCE",
        }
        await process_provider_message(session, payload, fake_deps)
        await session.flush()

        msgs = [m for m in fake_deps.whatsapp.sent_messages if "credit" in m.get("text", "").lower()]
        assert len(msgs) >= 1
        assert "5" in msgs[-1]["text"]
        assert "free" in msgs[-1]["text"]


class TestTopUpFlow:
    """Scenario 8: TOP UP → bundle buttons → selection → payment initiated."""

    async def test_top_up_shows_bundles(self, session: AsyncSession, fake_deps):
        provider = make_provider(phone_encrypted=b"237600000008")
        session.add(provider)
        _ensure_window(session, provider.phone_encrypted.decode())
        await session.flush()

        payload = {
            "provider_id": str(provider.id),
            "sender_phone": "237600000008",
            "body": "TOP UP",
        }
        await process_provider_message(session, payload, fake_deps)
        await session.flush()

        interactive_msgs = [m for m in fake_deps.whatsapp.sent_messages if m.get("type") == "interactive"]
        assert len(interactive_msgs) >= 1
        buttons = interactive_msgs[-1]["buttons"]
        bundle_ids = [b["id"] for b in buttons]
        assert "topup:first_purchase" in bundle_ids
        assert "topup:default" in bundle_ids

    async def test_top_up_button_initiates_payment(self, session: AsyncSession, fake_deps):
        provider = make_provider(phone_encrypted=b"237600000008b")
        session.add(provider)
        _ensure_window(session, provider.phone_encrypted.decode())
        await session.flush()

        payload = {
            "provider_id": str(provider.id),
            "sender_phone": "237600000008b",
            "button_reply_id": "topup:default",
        }
        await process_provider_message(session, payload, fake_deps)
        await session.flush()

        assert len(fake_deps.momo.requests) == 1
        payments = (await session.execute(
            select(Payment).where(Payment.provider_id == provider.id)
        )).scalars().all()
        assert len(payments) == 1
        assert payments[0].state == PaymentState.pending


class TestLowBalanceWarning:
    """Scenario 9: acceptance drops balance to threshold → warning enqueued."""

    async def test_low_balance_warning_enqueued(self, session: AsyncSession, fake_deps):
        from fixam.models import Job
        provider = make_provider(phone_encrypted=b"237600000009")
        customer = make_customer()
        session.add_all([provider, customer])
        await session.flush()

        session.add(grant_credits(provider.id, 1))
        await session.flush()

        req = make_request(customer.id)
        offer = make_offer(req.id, provider.id)
        session.add_all([req, offer])
        await session.flush()

        await accept_offer(session, offer.id, provider.id)
        await session.flush()

        from sqlalchemy.dialects.postgresql import JSONB
        jobs = (await session.execute(
            select(Job).where(
                Job.kind == "send_low_balance_warning",
                Job.payload["provider_id"].astext == str(provider.id),
            )
        )).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].payload["balance"] == 0


class TestFirstPurchaseBundleEligibility:
    """Scenario 10: first-purchase bundle shown only to new providers."""

    async def test_new_provider_sees_first_purchase(self, session: AsyncSession, fake_deps):
        provider = make_provider()
        session.add(provider)
        await session.flush()

        bundles = await get_bundles(session, provider.id)
        keys = [b.key for b in bundles]
        assert "first_purchase" in keys
        assert "default" in keys

    async def test_existing_purchaser_no_first_purchase(self, session: AsyncSession, fake_deps):
        provider = make_provider()
        session.add(provider)
        await session.flush()

        payment = make_payment(provider.id, state=PaymentState.succeeded)
        session.add(payment)
        await session.flush()

        bundles = await get_bundles(session, provider.id)
        keys = [b.key for b in bundles]
        assert "first_purchase" not in keys
        assert "default" in keys
