"""Dispatch, wave advancement, contact release, and withdrawn-notice handlers."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import (
    Assignment,
    Config,
    Customer,
    Followup,
    FollowupOutcome,
    Offer,
    OfferState,
    Provider,
    Quarter,
    RequestState,
    ServiceRequest,
    Trade,
)
from fixam.services.acceptance import (
    AcceptanceError,
    InsufficientBalance,
    OfferNotActionable,
    RequestNotDispatching,
    accept_offer,
)
from fixam.services.deps import Deps
from fixam.services.dispatch import (
    build_offer_body,
    get_cold_start_providers,
    get_eligible_providers,
    get_wave_config,
    rank_providers,
    split_into_waves,
)
from fixam.services.jobs import enqueue_job
from fixam.services.sender import send_outbound
from fixam.services.transitions import transition
from fixam.worker import register_handler

logger = logging.getLogger(__name__)


async def _send_offer(
    session: AsyncSession,
    deps: Deps,
    offer: Offer,
    request: ServiceRequest,
) -> bool:
    """Send an offer to a provider. Returns True on success."""
    provider = await session.get(Provider, offer.provider_id)
    phone = provider.phone_encrypted.decode()

    trade = await session.get(Trade, request.trade_id) if request.trade_id else None
    quarter = await session.get(Quarter, request.quarter_id) if request.quarter_id else None

    body = build_offer_body(
        trade_name=trade.name if trade else "General",
        quarter_name=quarter.name if quarter else "Unknown",
        urgency=request.urgency.value if request.urgency else "unknown",
        description=request.description or "No details provided",
    )
    buttons = [
        {"id": f"accept:{offer.id}", "title": "Accept"},
        {"id": f"decline:{offer.id}", "title": "Decline"},
    ]
    try:
        await send_outbound(
            session, deps.whatsapp, phone, body,
            request_id=request.id, buttons=buttons,
        )
        offer.state = OfferState.sent
        offer.sent_at = datetime.now(timezone.utc)
        return True
    except Exception:
        logger.exception("Failed to send offer %s", offer.id)
        offer.state = OfferState.failed
        return False


@register_handler("dispatch_request")
async def dispatch_request_handler(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    """FR-DSP: find eligible providers, rank, plan waves, send wave 1."""
    request_id = uuid.UUID(payload["request_id"])
    request = await session.get(ServiceRequest, request_id)
    if not request or request.state != RequestState.dispatching:
        return

    if not request.trade_id or not request.quarter_id:
        logger.error("Request %s missing trade or quarter", request_id)
        request.state = transition(request.state, RequestState.unfilled)
        customer = await session.get(Customer, request.customer_id)
        await send_outbound(
            session, deps.whatsapp, customer.phone_encrypted.decode(),
            "We couldn't find providers for your request. A person is looking into it.",
            request_id=request_id,
        )
        return

    eligible = await get_eligible_providers(
        session, request.trade_id, request.quarter_id, request_id,
    )

    if not eligible:
        request.state = transition(request.state, RequestState.unfilled)
        customer = await session.get(Customer, request.customer_id)
        await send_outbound(
            session, deps.whatsapp, customer.phone_encrypted.decode(),
            "We couldn't find available providers right now. A person is looking into it.",
            request_id=request_id,
        )
        return

    ranked = await rank_providers(session, eligible)
    cold_start = await get_cold_start_providers(session, eligible)

    # Force cold-start providers to the front of the list
    if cold_start:
        cold_list = [p for p in ranked if p in cold_start]
        rest = [p for p in ranked if p not in cold_start]
        ranked = cold_list + rest

    wave_sizes, timeout = await get_wave_config(session, request)
    waves = split_into_waves(ranked, wave_sizes)

    # Send wave 1
    for pid in waves[0]:
        offer = Offer(
            request_id=request_id,
            provider_id=pid,
            state=OfferState.queued,
            wave=1,
        )
        session.add(offer)
        await session.flush()
        await _send_offer(session, deps, offer, request)

    # Enqueue advance_wave for wave 2 (if any)
    remaining_waves = [[str(p) for p in w] for w in waves[1:]]
    if remaining_waves:
        await enqueue_job(
            session,
            "advance_wave",
            {
                "request_id": str(request_id),
                "wave_number": 2,
                "remaining_waves": remaining_waves,
            },
            due_at=datetime.now(timezone.utc) + timedelta(seconds=timeout),
        )
    else:
        # Only one wave — schedule a timeout to check for unfilled
        await enqueue_job(
            session,
            "advance_wave",
            {
                "request_id": str(request_id),
                "wave_number": 2,
                "remaining_waves": [],
            },
            due_at=datetime.now(timezone.utc) + timedelta(seconds=timeout),
        )


@register_handler("advance_wave")
async def advance_wave_handler(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    """Expire current wave, auto-OFF, send next wave or go unfilled."""
    request_id = uuid.UUID(payload["request_id"])
    wave_number = payload["wave_number"]
    remaining_waves = payload["remaining_waves"]

    request = await session.get(ServiceRequest, request_id)
    if not request or request.state != RequestState.dispatching:
        return

    # Expire all sent offers for previous wave
    now = datetime.now(timezone.utc)
    prev_wave = wave_number - 1
    result = await session.execute(
        select(Offer).where(
            Offer.request_id == request_id,
            Offer.wave == prev_wave,
            Offer.state == OfferState.sent,
        )
    )
    expired_offers = list(result.scalars().all())
    for offer in expired_offers:
        offer.state = OfferState.expired

    # Auto-OFF for providers who didn't respond
    await _handle_auto_off(session, deps, expired_offers)

    if remaining_waves:
        # Send next wave
        next_providers = [uuid.UUID(p) for p in remaining_waves[0]]
        for pid in next_providers:
            offer = Offer(
                request_id=request_id,
                provider_id=pid,
                state=OfferState.queued,
                wave=wave_number,
            )
            session.add(offer)
            await session.flush()
            await _send_offer(session, deps, offer, request)

        wave_sizes_str = None
        row = await session.execute(
            select(Config.value).where(Config.key == "wave_timeout_seconds")
        )
        timeout = int(row.scalar_one_or_none() or "300")
        if request.urgency:
            row = await session.execute(
                select(Config.value).where(
                    Config.key == f"wave_timeout_seconds_{request.urgency.value}"
                )
            )
            val = row.scalar_one_or_none()
            if val:
                timeout = int(val)

        await enqueue_job(
            session,
            "advance_wave",
            {
                "request_id": str(request_id),
                "wave_number": wave_number + 1,
                "remaining_waves": remaining_waves[1:],
            },
            due_at=now + timedelta(seconds=timeout),
        )
    else:
        # All waves exhausted — unfilled (FR-DSP-08)
        request.state = transition(request.state, RequestState.unfilled)
        customer = await session.get(Customer, request.customer_id)
        await send_outbound(
            session, deps.whatsapp, customer.phone_encrypted.decode(),
            "We haven't found a provider yet. A person from our team is handling your request.",
            request_id=request_id,
        )


async def _handle_auto_off(
    session: AsyncSession,
    deps: Deps,
    expired_offers: list[Offer],
) -> None:
    """FR-PRV-06: increment consecutive_unanswered, auto-OFF at threshold."""
    if not expired_offers:
        return

    row = await session.execute(
        select(Config.value).where(Config.key == "auto_off_threshold")
    )
    threshold = int(row.scalar_one_or_none() or "3")

    for offer in expired_offers:
        provider = await session.get(Provider, offer.provider_id)
        provider.consecutive_unanswered += 1
        if provider.consecutive_unanswered >= threshold:
            provider.is_available = False
            phone = provider.phone_encrypted.decode()
            await send_outbound(
                session, deps.whatsapp, phone,
                "You've been set to OFF because you haven't responded to recent offers. "
                "Send AVAILABLE when you're ready to receive jobs again.",
            )


@register_handler("release_contacts")
async def release_contacts_handler(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    """FR-ACC-03, FR-ACC-04: send contact details after acceptance."""
    assignment_id = uuid.UUID(payload["assignment_id"])

    assignment = await session.get(Assignment, assignment_id)
    if not assignment:
        return

    request = await session.get(ServiceRequest, assignment.request_id)
    provider = await session.get(Provider, assignment.provider_id)
    customer = await session.get(Customer, request.customer_id)

    trade = await session.get(Trade, request.trade_id) if request.trade_id else None
    quarter = await session.get(Quarter, request.quarter_id) if request.quarter_id else None

    customer_name = customer.name_encrypted.decode() if customer.name_encrypted else "Customer"
    customer_phone = customer.phone_encrypted.decode()
    provider_name = provider.name_encrypted.decode()
    provider_phone = provider.phone_encrypted.decode()

    # Compute provider rating
    rating_text = await _provider_rating_text(session, provider.id)

    # Send provider the customer's details
    provider_msg = (
        f"You've been matched with a customer!\n"
        f"Name: {customer_name}\n"
        f"Phone: {customer_phone}\n"
        f"Area: {quarter.name if quarter else 'Unknown'}\n"
        f"Description: {request.description or 'No details'}"
    )
    await send_outbound(
        session, deps.whatsapp, provider_phone, provider_msg,
        request_id=request.id,
    )

    # Send customer the provider's details
    customer_msg = (
        f"Great news! We found a provider for you.\n"
        f"Name: {provider_name}\n"
        f"Phone: {provider_phone}\n"
        f"Trade: {trade.name if trade else 'General'}\n"
        f"Rating: {rating_text}"
    )
    await send_outbound(
        session, deps.whatsapp, customer_phone, customer_msg,
        request_id=request.id,
    )


async def _provider_rating_text(session: AsyncSession, provider_id: uuid.UUID) -> str:
    result = await session.execute(
        select(func.avg(Followup.rating))
        .join(Assignment, Assignment.id == Followup.assignment_id)
        .where(
            Assignment.provider_id == provider_id,
            Followup.rating.is_not(None),
        )
    )
    avg = result.scalar_one_or_none()
    if avg is None:
        return "New provider"
    return f"{avg:.1f}/5"


@register_handler("notify_withdrawn")
async def notify_withdrawn_handler(
    session: AsyncSession, payload: dict[str, Any], deps: Deps
) -> None:
    """FR-ACC-05: tell providers whose offers were withdrawn."""
    request_id = uuid.UUID(payload["request_id"])

    result = await session.execute(
        select(Offer).where(
            Offer.request_id == request_id,
            Offer.state == OfferState.withdrawn,
        )
    )
    for offer in result.scalars():
        provider = await session.get(Provider, offer.provider_id)
        phone = provider.phone_encrypted.decode()
        await send_outbound(
            session, deps.whatsapp, phone,
            "The job you were offered has been taken by another provider.",
            request_id=request_id,
        )


async def handle_accept(
    session: AsyncSession,
    deps: Deps,
    provider: Provider,
    offer_id: uuid.UUID,
) -> None:
    """Process an Accept button tap from a provider."""
    try:
        assignment = await accept_offer(session, offer_id, provider.id)
    except (OfferNotActionable, RequestNotDispatching):
        phone = provider.phone_encrypted.decode()
        await send_outbound(
            session, deps.whatsapp, phone,
            "Sorry, this job has already been taken. No charge.",
        )
        return
    except InsufficientBalance:
        phone = provider.phone_encrypted.decode()
        await send_outbound(
            session, deps.whatsapp, phone,
            "You don't have enough credits to accept. Send TOP UP to add credits.",
        )
        return

    provider.consecutive_unanswered = 0

    phone = provider.phone_encrypted.decode()
    await send_outbound(
        session, deps.whatsapp, phone,
        "You've accepted the job! Contact details are being sent to you now.",
    )

    await enqueue_job(
        session,
        "release_contacts",
        {"assignment_id": str(assignment.id)},
    )
    await enqueue_job(
        session,
        "notify_withdrawn",
        {"request_id": str(assignment.request_id)},
    )


async def handle_decline(
    session: AsyncSession,
    deps: Deps,
    provider: Provider,
    offer_id: uuid.UUID,
) -> None:
    """Process a Decline button tap from a provider."""
    offer = await session.get(Offer, offer_id)
    if not offer or offer.provider_id != provider.id:
        return
    if offer.state != OfferState.sent:
        return

    offer.state = OfferState.declined
    offer.responded_at = datetime.now(timezone.utc)
    provider.consecutive_unanswered = 0

    phone = provider.phone_encrypted.decode()
    await send_outbound(
        session, deps.whatsapp, phone,
        "Got it, you've declined this job.",
    )
