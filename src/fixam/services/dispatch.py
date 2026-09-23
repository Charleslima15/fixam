"""Eligibility query, ranking, and wave planning (FR-DSP-01 through FR-DSP-04)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import (
    Assignment,
    Config,
    CreditLedger,
    Customer,
    Followup,
    FollowupOutcome,
    Offer,
    Provider,
    ProviderArea,
    ProviderTrade,
    ServiceRequest,
    TrustTier,
)


async def get_eligible_providers(
    session: AsyncSession,
    trade_id: uuid.UUID,
    quarter_id: uuid.UUID,
    request_id: uuid.UUID,
) -> list[uuid.UUID]:
    """FR-DSP-01: eligibility is a query, not a score."""
    already_offered = (
        select(Offer.provider_id).where(Offer.request_id == request_id)
    ).correlate(None)

    balance_sub = (
        select(func.coalesce(func.sum(CreditLedger.amount), 0))
        .where(CreditLedger.provider_id == Provider.id)
        .correlate(Provider)
        .scalar_subquery()
    )

    stmt = (
        select(Provider.id)
        .join(ProviderTrade, (ProviderTrade.provider_id == Provider.id) & (ProviderTrade.trade_id == trade_id))
        .join(ProviderArea, (ProviderArea.provider_id == Provider.id) & (ProviderArea.quarter_id == quarter_id))
        .where(
            Provider.is_active.is_(True),
            Provider.is_suspended.is_(False),
            Provider.is_available.is_(True),
            Provider.id.not_in(already_offered),
            balance_sub >= 1,
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def rank_providers(
    session: AsyncSession,
    provider_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    """FR-DSP-02: completion rate DESC, then time since last lead ASC.

    Isolated so ranking can change without touching dispatch.
    """
    if not provider_ids:
        return []

    epoch = datetime(2000, 1, 1, tzinfo=timezone.utc)

    # Completion rate: confirmed_jobs / assignments_with_known_outcome
    # A "confirmed job" is an assignment whose followup outcome is 'yes'.
    # Known-outcome assignments have a non-null followup outcome that isn't 'no_response'.
    confirmed_sub = (
        select(func.count())
        .select_from(Assignment)
        .join(Followup, Followup.assignment_id == Assignment.id)
        .where(
            Assignment.provider_id == Provider.id,
            Followup.outcome == FollowupOutcome.yes,
        )
        .correlate(Provider)
        .scalar_subquery()
    )

    known_outcome_sub = (
        select(func.count())
        .select_from(Assignment)
        .join(Followup, Followup.assignment_id == Assignment.id)
        .where(
            Assignment.provider_id == Provider.id,
            Followup.outcome.is_not(None),
            Followup.outcome != FollowupOutcome.no_response,
        )
        .correlate(Provider)
        .scalar_subquery()
    )

    last_lead_sub = (
        select(func.coalesce(func.max(Assignment.created_at), epoch))
        .where(Assignment.provider_id == Provider.id)
        .correlate(Provider)
        .scalar_subquery()
    )

    completion_rate = case(
        (known_outcome_sub > 0, confirmed_sub * 1.0 / known_outcome_sub),
        else_=0.0,
    )

    stmt = (
        select(Provider.id)
        .where(Provider.id.in_(provider_ids))
        .order_by(completion_rate.desc(), last_lead_sub.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_cold_start_providers(
    session: AsyncSession,
    provider_ids: list[uuid.UUID],
) -> set[uuid.UUID]:
    """FR-DSP-04: providers with fewer than N total offers."""
    if not provider_ids:
        return set()

    row = await session.execute(
        select(Config.value).where(Config.key == "cold_start_offer_cap")
    )
    cap = int(row.scalar_one_or_none() or "3")

    offer_count_sub = (
        select(func.count())
        .select_from(Offer)
        .where(Offer.provider_id == Provider.id)
        .correlate(Provider)
        .scalar_subquery()
    )
    stmt = (
        select(Provider.id)
        .where(Provider.id.in_(provider_ids), offer_count_sub < cap)
    )
    result = await session.execute(stmt)
    return set(result.scalars().all())


async def get_wave_config(
    session: AsyncSession,
    request: ServiceRequest,
) -> tuple[list[int], int]:
    """Return (wave_sizes, timeout_seconds) based on urgency and customer tier."""
    customer = await session.get(Customer, request.customer_id)

    # Try urgency-specific, then tier-specific, then default
    keys_to_try = []
    if request.urgency:
        keys_to_try.append(f"wave_sizes_{request.urgency.value}")
    if customer and customer.trust_tier == TrustTier.established:
        keys_to_try.append("wave_sizes_established")
    keys_to_try.append("wave_sizes")

    sizes_str = None
    for key in keys_to_try:
        row = await session.execute(select(Config.value).where(Config.key == key))
        val = row.scalar_one_or_none()
        if val:
            sizes_str = val
            break
    sizes = [int(s) for s in (sizes_str or "2,3,0").split(",")]

    timeout_key = f"wave_timeout_seconds_{request.urgency.value}" if request.urgency else None
    timeout = None
    if timeout_key:
        row = await session.execute(select(Config.value).where(Config.key == timeout_key))
        timeout = row.scalar_one_or_none()
    if not timeout:
        row = await session.execute(select(Config.value).where(Config.key == "wave_timeout_seconds"))
        timeout = row.scalar_one_or_none()

    return sizes, int(timeout or "300")


def split_into_waves(
    ranked: list[uuid.UUID],
    wave_sizes: list[int],
) -> list[list[uuid.UUID]]:
    """Split a ranked list into wave buckets. 0 in sizes = all remaining."""
    waves: list[list[uuid.UUID]] = []
    offset = 0
    for size in wave_sizes:
        if offset >= len(ranked):
            break
        if size == 0:
            waves.append(ranked[offset:])
            offset = len(ranked)
        else:
            waves.append(ranked[offset : offset + size])
            offset += size
    if offset < len(ranked):
        waves.append(ranked[offset:])
    return waves


def build_offer_body(
    trade_name: str,
    quarter_name: str,
    urgency: str,
    description: str,
) -> str:
    """FR-DSP-06: offer content. No customer name or phone."""
    return (
        f"New job opportunity!\n"
        f"Trade: {trade_name}\n"
        f"Area: {quarter_name}\n"
        f"Urgency: {urgency}\n"
        f"Description: {description}"
    )
