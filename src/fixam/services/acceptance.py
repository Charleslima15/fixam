import uuid

from sqlalchemy import func, select, update
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


class AcceptanceError(Exception):
    pass


class OfferNotFound(AcceptanceError):
    pass


class OfferNotActionable(AcceptanceError):
    def __init__(self, state: OfferState):
        self.state = state
        super().__init__(f"Offer is in state {state.value}, not sent")


class RequestNotDispatching(AcceptanceError):
    def __init__(self, state: RequestState):
        self.state = state
        super().__init__(f"Request is in state {state.value}, not dispatching")


class InsufficientBalance(AcceptanceError):
    def __init__(self, balance: int):
        self.balance = balance
        super().__init__(f"Insufficient balance: {balance}")


async def accept_offer(
    session: AsyncSession,
    offer_id: uuid.UUID,
    provider_id: uuid.UUID,
) -> Assignment:
    """FR-ACC-01: atomic acceptance transaction.

    Caller must wrap this in `async with session.begin():`.
    """
    offer = await session.get(Offer, offer_id, with_for_update=True)
    if offer is None or offer.provider_id != provider_id:
        raise OfferNotFound()
    if offer.state != OfferState.sent:
        raise OfferNotActionable(offer.state)

    request = await session.get(
        ServiceRequest, offer.request_id, with_for_update=True
    )
    if request.state != RequestState.dispatching:
        raise RequestNotDispatching(request.state)

    balance = (
        await session.execute(
            select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
                CreditLedger.provider_id == provider_id
            )
        )
    ).scalar_one()

    if balance < 1:
        raise InsufficientBalance(balance)

    session.add(
        CreditLedger(
            provider_id=provider_id,
            kind=LedgerKind.debit_accept,
            amount=-1,
            reference_id=offer.id,
            reference_type="offer",
            actor="system",
        )
    )

    assignment = Assignment(
        request_id=request.id,
        offer_id=offer.id,
        provider_id=provider_id,
    )
    session.add(assignment)

    offer.state = OfferState.accepted
    request.state = RequestState.assigned

    await session.execute(
        update(Offer)
        .where(Offer.request_id == request.id)
        .where(Offer.id != offer.id)
        .where(Offer.state.in_([OfferState.queued, OfferState.sent]))
        .values(state=OfferState.withdrawn)
    )

    return assignment
