"""Payment service — initiate, confirm, poll, balance, free credits."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import Config, CreditLedger, LedgerKind, Payment, PaymentState, Provider
from fixam.services.jobs import enqueue_job

logger = logging.getLogger(__name__)

TERMINAL_SUCCESS = {"SUCCESSFUL"}
TERMINAL_FAILURE = {"FAILED", "EXPIRED", "TIMEOUT", "REJECTED"}


@dataclass(frozen=True, slots=True)
class Bundle:
    key: str
    credits: int
    price_fcfa: int
    first_purchase_only: bool


async def _get_config(session: AsyncSession, key: str) -> str | None:
    row = await session.execute(select(Config.value).where(Config.key == key))
    return row.scalar_one_or_none()


async def get_bundles(session: AsyncSession, provider_id: uuid.UUID) -> list[Bundle]:
    has_purchase = (
        await session.execute(
            select(Payment.id)
            .where(Payment.provider_id == provider_id)
            .where(Payment.state == PaymentState.succeeded)
            .limit(1)
        )
    ).scalar_one_or_none() is not None

    bundles: list[Bundle] = []

    raw_first = await _get_config(session, "bundle_first_purchase")
    if raw_first:
        data = json.loads(raw_first)
        if not has_purchase:
            bundles.append(Bundle(
                key="first_purchase",
                credits=data["credits"],
                price_fcfa=data["price_fcfa"],
                first_purchase_only=True,
            ))

    raw_default = await _get_config(session, "bundle_default")
    if raw_default:
        data = json.loads(raw_default)
        bundles.append(Bundle(
            key="default",
            credits=data["credits"],
            price_fcfa=data["price_fcfa"],
            first_purchase_only=False,
        ))

    return bundles


async def get_provider_balance(session: AsyncSession, provider_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
            CreditLedger.provider_id == provider_id
        )
    )
    return result.scalar_one()


async def get_free_credit_remainder(session: AsyncSession, provider_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
            CreditLedger.provider_id == provider_id,
            CreditLedger.kind.in_([LedgerKind.grant_free, LedgerKind.adjustment]),
        )
    )
    remainder = result.scalar_one()
    return max(remainder, 0)


async def initiate_payment(
    session: AsyncSession,
    deps,
    provider: Provider,
    bundle: Bundle,
    phone: str,
) -> Payment:
    """FR-PAY-02: create payment record before calling MTN."""
    our_reference = str(uuid.uuid4())

    payment = Payment(
        provider_id=provider.id,
        our_reference=our_reference,
        amount_fcfa=bundle.price_fcfa,
        credits=bundle.credits,
        state=PaymentState.initiated,
    )
    session.add(payment)
    await session.flush()

    await deps.momo.request_to_pay(
        reference_id=our_reference,
        phone=phone,
        amount=bundle.price_fcfa,
        external_id=our_reference,
        note=f"FixAm {bundle.credits} credits",
    )

    payment.state = PaymentState.pending

    from fixam.services.sender import send_outbound
    await send_outbound(
        session, deps.whatsapp, phone,
        f"Check your phone to approve the payment of {bundle.price_fcfa} FCFA "
        f"for {bundle.credits} credits.",
    )

    return payment


async def confirm_payment(
    session: AsyncSession,
    deps,
    payment_id: uuid.UUID,
) -> None:
    """Verify payment status with MTN and write credits on success.

    Idempotent: already-terminal payments are a no-op (FR-PAY-07).
    """
    payment = await session.get(Payment, payment_id, with_for_update=True)
    if payment is None:
        logger.warning("confirm_payment: payment %s not found", payment_id)
        return

    if payment.state in (PaymentState.succeeded, PaymentState.failed):
        return

    status = await deps.momo.get_payment_status(payment.our_reference)
    mtn_status = status.get("status", "")

    if mtn_status in TERMINAL_SUCCESS:
        payment.state = PaymentState.succeeded
        payment.mtn_reference = status.get("financialTransactionId")
        payment.raw_callback = status

        session.add(CreditLedger(
            provider_id=payment.provider_id,
            kind=LedgerKind.purchase,
            amount=payment.credits,
            reference_id=payment.id,
            reference_type="payment",
            actor="system",
        ))
        await session.flush()

        new_balance = await get_provider_balance(session, payment.provider_id)

        provider = await session.get(Provider, payment.provider_id)
        if provider:
            phone = provider.phone_encrypted.decode()
            from fixam.services.sender import send_outbound
            await send_outbound(
                session, deps.whatsapp, phone,
                f"Payment confirmed! {payment.credits} credits added. "
                f"Your balance: {new_balance}.",
            )

    elif mtn_status in TERMINAL_FAILURE:
        payment.state = PaymentState.failed
        payment.raw_callback = status

        provider = await session.get(Provider, payment.provider_id)
        if provider:
            phone = provider.phone_encrypted.decode()
            from fixam.services.sender import send_outbound
            await send_outbound(
                session, deps.whatsapp, phone,
                "Your payment was not completed. Send TOP UP to try again.",
            )


async def poll_pending_payments(session: AsyncSession, deps) -> None:
    """FR-PAY-05: poll payments not confirmed by callback."""
    poll_after = int(await _get_config(session, "payment_poll_after_seconds") or "120")
    stuck_after = int(await _get_config(session, "payment_stuck_after_seconds") or "900")
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=poll_after)
    stuck_cutoff = now - timedelta(seconds=stuck_after)

    result = await session.execute(
        select(Payment).where(
            Payment.state.in_([PaymentState.initiated, PaymentState.pending]),
            Payment.updated_at <= cutoff,
        )
    )
    payments = result.scalars().all()

    for payment in payments:
        status = await deps.momo.get_payment_status(payment.our_reference)
        mtn_status = status.get("status", "")

        if mtn_status in TERMINAL_SUCCESS:
            payment.state = PaymentState.succeeded
            payment.mtn_reference = status.get("financialTransactionId")
            payment.raw_callback = status

            session.add(CreditLedger(
                provider_id=payment.provider_id,
                kind=LedgerKind.purchase,
                amount=payment.credits,
                reference_id=payment.id,
                reference_type="payment",
                actor="system",
            ))

            provider = await session.get(Provider, payment.provider_id)
            if provider:
                phone = provider.phone_encrypted.decode()
                from fixam.services.sender import send_outbound
                await send_outbound(
                    session, deps.whatsapp, phone,
                    f"Payment confirmed! {payment.credits} credits added.",
                )

        elif mtn_status in TERMINAL_FAILURE:
            payment.state = PaymentState.failed
            payment.raw_callback = status

        elif payment.created_at <= stuck_cutoff:
            payment.state = PaymentState.stuck
            logger.warning("Payment %s stuck after %ds", payment.id, stuck_after)


async def grant_activation_credits(
    session: AsyncSession, provider_id: uuid.UUID
) -> CreditLedger:
    """FR-FRE-01: grant free credits on activation."""
    cap = int(await _get_config(session, "free_credit_cap") or "5")
    entry = CreditLedger(
        provider_id=provider_id,
        kind=LedgerKind.grant_free,
        amount=cap,
        actor="system",
        note="activation grant",
    )
    session.add(entry)
    return entry


async def remove_free_credits(
    session: AsyncSession, deps, provider_id: uuid.UUID
) -> bool:
    """FR-FRE-02: remove remaining free credits after first confirmed job.

    Caps the removal at the overall balance so it never goes negative.
    Returns True if an adjustment was written.
    """
    remainder = await get_free_credit_remainder(session, provider_id)
    if remainder <= 0:
        return False

    balance = await get_provider_balance(session, provider_id)
    to_remove = min(remainder, balance)
    if to_remove <= 0:
        return False

    session.add(CreditLedger(
        provider_id=provider_id,
        kind=LedgerKind.adjustment,
        amount=-to_remove,
        actor="system",
        note="first job confirmed",
    ))

    provider = await session.get(Provider, provider_id)
    if provider:
        phone = provider.phone_encrypted.decode()
        from fixam.services.sender import send_outbound
        await send_outbound(
            session, deps.whatsapp, phone,
            "Your free trial credits have been removed. "
            "Send TOP UP to continue receiving job offers.",
        )

    return True
