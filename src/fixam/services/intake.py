"""Customer intake conversation orchestrator (FR-INT, FR-ABU)."""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models import (
    Config,
    Customer,
    Quarter,
    RequestState,
    ServiceRequest,
    Trade,
    TrustTier,
)
from fixam.models.model_call_log import ModelCallLog
from fixam.services.ai import (
    AIClient,
    ExtractionResult,
    check_daily_cap,
    extract_with_retry,
)
from fixam.services.prefilter import is_trivial
from fixam.services.sender import send_outbound
from fixam.services.transitions import OPEN_STATES, InvalidTransition, transition
from fixam.services.whatsapp import WhatsAppClient

from fixam.models import ContactWindow
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)

REDIRECT_COPY = (
    "I don't share contacts directly — tell me what you need "
    "and I'll get someone to take the job."
)

BLOCKED_REPLY = "Your account is currently suspended. Please contact support."

CAP_REACHED_REPLY = (
    "You've sent a lot of messages today. Please try again tomorrow, "
    "or reply with a short description of the service you need."
)

STATUS_REPLY = "Your request is being processed. We'll update you shortly."

GREETING_REPLY = (
    "Hello! I help connect you with local service providers in Buea. "
    "Tell me what you need — for example, 'I need a plumber in Molyko'."
)

FALLBACK_PROMPT = (
    "I'd like to help you find a service provider. "
    "What service do you need? Please pick one:"
)

FALLBACK_AREA_PROMPT = "Which area do you need the service in? Please pick one:"

CONFIRM_TEMPLATE = (
    "I understand you need a {trade} in {area} ({urgency}): {description}\n\n"
    "Is that right?"
)

_CONTACT_KEYWORDS = {
    "number", "numbers", "phone", "contact", "contacts", "list",
    "give me", "send me", "provider", "providers",
}


def _wants_contacts(text: str) -> bool:
    lower = text.lower()
    matches = sum(1 for kw in _CONTACT_KEYWORDS if kw in lower)
    return matches >= 2


async def _get_config_int(session: AsyncSession, key: str, default: int) -> int:
    result = await session.execute(
        select(Config.value).where(Config.key == key)
    )
    val = result.scalar_one_or_none()
    return int(val) if val else default


async def _get_or_create_customer(
    session: AsyncSession, phone: str
) -> Customer:
    """FR-INT-01: create customer on first contact."""
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()
    result = await session.execute(
        select(Customer).where(Customer.phone_hash == phone_hash)
    )
    customer = result.scalar_one_or_none()
    if customer is not None:
        return customer
    customer = Customer(
        id=uuid.uuid4(),
        phone_hash=phone_hash,
        phone_encrypted=phone.encode(),
    )
    session.add(customer)
    await session.flush()
    return customer


async def _get_open_request(
    session: AsyncSession, customer_id: uuid.UUID
) -> ServiceRequest | None:
    """FR-INT-02: at most one open request per conversation."""
    result = await session.execute(
        select(ServiceRequest)
        .where(
            ServiceRequest.customer_id == customer_id,
            ServiceRequest.state.in_([s.value for s in OPEN_STATES]),
        )
        .order_by(ServiceRequest.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _count_open_requests(
    session: AsyncSession, customer_id: uuid.UUID
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(ServiceRequest)
        .where(
            ServiceRequest.customer_id == customer_id,
            ServiceRequest.state.in_([s.value for s in OPEN_STATES]),
        )
    )
    return result.scalar_one()


async def _count_today_requests(
    session: AsyncSession, customer_id: uuid.UUID
) -> int:
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    result = await session.execute(
        select(func.count())
        .select_from(ServiceRequest)
        .where(
            ServiceRequest.customer_id == customer_id,
            ServiceRequest.created_at >= today_start,
        )
    )
    return result.scalar_one()


async def _load_trades(session: AsyncSession) -> list[tuple[uuid.UUID, str]]:
    result = await session.execute(
        select(Trade.id, Trade.name).where(Trade.active == True).order_by(Trade.name)
    )
    return list(result.all())


async def _load_quarters(session: AsyncSession) -> list[tuple[uuid.UUID, str]]:
    result = await session.execute(
        select(Quarter.id, Quarter.name).where(Quarter.active == True).order_by(Quarter.name)
    )
    return list(result.all())


async def _resolve_trade(
    session: AsyncSession, name: str
) -> tuple[uuid.UUID, str] | None:
    result = await session.execute(
        select(Trade.id, Trade.name).where(
            func.lower(Trade.name) == name.lower(), Trade.active == True
        )
    )
    return result.one_or_none()


async def _resolve_quarter(
    session: AsyncSession, name: str
) -> tuple[uuid.UUID, str] | None:
    result = await session.execute(
        select(Quarter.id, Quarter.name).where(
            func.lower(Quarter.name) == name.lower(), Quarter.active == True
        )
    )
    return result.one_or_none()


async def _send_reply(
    session: AsyncSession,
    whatsapp: WhatsAppClient,
    phone: str,
    text: str,
    *,
    request_id: uuid.UUID | None = None,
    buttons: list[dict[str, str]] | None = None,
) -> None:
    await send_outbound(
        session, whatsapp, phone, text,
        request_id=request_id, buttons=buttons,
    )


async def process_customer_message(
    session: AsyncSession,
    phone: str,
    body: str,
    ai: AIClient,
    whatsapp: WhatsAppClient,
    *,
    message_type: str = "text",
    button_reply_id: str | None = None,
) -> None:
    """Main intake entry point. Called from the process_inbound handler."""
    # Ensure contact window exists (inbound handler creates it, but belt-and-suspenders)
    phone_hash_for_window = hashlib.sha256(phone.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    stmt = pg_insert(ContactWindow).values(
        phone_hash=phone_hash_for_window, last_inbound_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[ContactWindow.phone_hash],
        set_={"last_inbound_at": now},
    )
    await session.execute(stmt)

    customer = await _get_or_create_customer(session, phone)

    # FR-ABU-04: blocked customers get neutral reply
    if customer.trust_tier == TrustTier.blocked:
        await _send_reply(session, whatsapp, phone, BLOCKED_REPLY)
        return

    req = await _get_open_request(session, customer.id)

    # Handle messages on already-dispatching/assigned requests (FR-INT-07)
    if req and req.state in (
        RequestState.dispatching,
        RequestState.assigned,
        RequestState.followed_up,
    ):
        await _send_reply(
            session, whatsapp, phone, STATUS_REPLY, request_id=req.id
        )
        return

    # Handle confirmation response (FR-INT-05)
    if req and req.state == RequestState.awaiting_confirmation:
        await _handle_confirmation(session, whatsapp, phone, req, body, button_reply_id)
        return

    # FR-INT-09: redirect requests for provider contacts
    if body and _wants_contacts(body):
        await _send_reply(session, whatsapp, phone, REDIRECT_COPY)
        return

    # Pre-filter trivial messages (FR-AI-06) — button replies bypass this
    if not button_reply_id and is_trivial(body) and req is None:
        await _send_reply(session, whatsapp, phone, GREETING_REPLY)
        return
    if not button_reply_id and is_trivial(body) and req is not None:
        return

    # FR-ABU-01: check open request limits
    max_open = await _get_config_int(session, "max_open_requests_per_customer", 2)
    if req is None:
        open_count = await _count_open_requests(session, customer.id)
        if open_count >= max_open:
            await _send_reply(
                session, whatsapp, phone,
                "You already have open requests. Please wait for them to be processed.",
            )
            return

    # FR-ABU-01: daily request cap
    daily_cap = await _get_config_int(session, "daily_request_cap_per_customer", 10)
    if req is None:
        today_count = await _count_today_requests(session, customer.id)
        if today_count >= daily_cap:
            await _send_reply(
                session, whatsapp, phone,
                "You've reached the daily request limit. Please try again tomorrow.",
            )
            return

    # Create new request if needed
    if req is None:
        req = ServiceRequest(
            id=uuid.uuid4(),
            customer_id=customer.id,
            state=RequestState.collecting,
            conversation={"messages": [], "step": "initial"},
        )
        session.add(req)
        await session.flush()

    conv = dict(req.conversation or {"messages": [], "step": "initial"})

    # Handle fallback mode button replies
    if conv.get("fallback_mode") and button_reply_id:
        await _handle_fallback_reply(
            session, whatsapp, phone, req, customer, conv, button_reply_id
        )
        return

    # Append message to bounded context (FR-AI-08)
    context_limit = await _get_config_int(session, "bounded_context_messages", 5)
    msgs = conv.get("messages", [])
    msgs.append(body)
    if len(msgs) > context_limit:
        msgs = msgs[-context_limit:]
    conv["messages"] = msgs

    # FR-AI-07: daily model call cap
    model_cap = await _get_config_int(session, "daily_model_call_cap", 60)
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()
    if not await check_daily_cap(session, phone_hash, model_cap):
        conv["step"] = "cap_reached"
        req.conversation = conv
        await _send_reply(
            session, whatsapp, phone, CAP_REACHED_REPLY, request_id=req.id
        )
        return

    # Load reference data for AI
    trades_data = await _load_trades(session)
    quarters_data = await _load_quarters(session)
    trade_names = [t[1] for t in trades_data]
    quarter_names = [q[1] for q in quarters_data]

    # Call AI (FR-AI-01, FR-AI-02)
    result = await extract_with_retry(
        ai, msgs, trade_names, quarter_names,
        session=session, request_id=req.id, phone_hash=phone_hash,
    )

    if result is None:
        # NFR-REL-02: AI down — switch to button-driven fallback
        await _start_fallback(session, whatsapp, phone, req, conv, trades_data)
        return

    if not result.is_service_request:
        await _send_reply(
            session, whatsapp, phone, GREETING_REPLY, request_id=req.id
        )
        return

    # Process extraction result
    await _process_extraction(
        session, whatsapp, phone, req, customer, conv,
        result, trades_data, quarters_data,
    )


async def _handle_confirmation(
    session: AsyncSession,
    whatsapp: WhatsAppClient,
    phone: str,
    req: ServiceRequest,
    body: str,
    button_reply_id: str | None,
) -> None:
    if button_reply_id == "confirm_yes" or (body and body.strip().lower() in ("yes", "confirm")):
        req.state = transition(req.state, RequestState.dispatching)
        req.confirmed_at = datetime.now(timezone.utc)
        # Update customer's last confirmed area (FR-INT-04)
        if req.quarter_id:
            customer = await session.get(Customer, req.customer_id)
            if customer:
                customer.last_area_id = req.quarter_id
        await _send_reply(
            session, whatsapp, phone,
            "Got it! We're finding a provider for you now.",
            request_id=req.id,
        )
    elif button_reply_id == "confirm_no":
        req.state = transition(req.state, RequestState.cancelled)
        await _send_reply(
            session, whatsapp, phone,
            "No problem. Send a new message whenever you're ready.",
            request_id=req.id,
        )
    else:
        # Resend confirmation
        conv = req.conversation or {}
        trade_name = conv.get("trade_name", "service")
        area_name = conv.get("area_name", "your area")
        urgency = conv.get("urgency", "unknown")
        description = conv.get("description", "your request")
        text = CONFIRM_TEMPLATE.format(
            trade=trade_name, area=area_name,
            urgency=urgency, description=description,
        )
        await _send_reply(
            session, whatsapp, phone, text, request_id=req.id,
            buttons=[
                {"id": "confirm_yes", "title": "Yes, that's right"},
                {"id": "confirm_no", "title": "No, start over"},
            ],
        )


async def _process_extraction(
    session: AsyncSession,
    whatsapp: WhatsAppClient,
    phone: str,
    req: ServiceRequest,
    customer: Customer,
    conv: dict,
    result: ExtractionResult,
    trades_data: list[tuple[uuid.UUID, str]],
    quarters_data: list[tuple[uuid.UUID, str]],
) -> None:
    trade_match = None
    if result.trade:
        trade_match = next(
            ((tid, tn) for tid, tn in trades_data if tn.lower() == result.trade.lower()),
            None,
        )

    area_match = None
    if result.area:
        area_match = next(
            ((qid, qn) for qid, qn in quarters_data if qn.lower() == result.area.lower()),
            None,
        )

    # FR-INT-04: default to last confirmed area
    if area_match is None and customer.last_area_id:
        for qid, qn in quarters_data:
            if qid == customer.last_area_id:
                area_match = (qid, qn)
                break

    # FR-INT-03: ask one clarifying question at a time
    if trade_match is None:
        conv["step"] = "clarify_trade"
        if result.area:
            conv["pending_area"] = result.area
        if result.urgency:
            conv["pending_urgency"] = result.urgency
        if result.description:
            conv["pending_description"] = result.description
        req.conversation = conv
        trade_names = [t[1] for t in trades_data[:3]]
        buttons = [{"id": f"trade_{tn.lower()}", "title": tn} for tn in trade_names]
        await _send_reply(
            session, whatsapp, phone,
            "What type of service do you need?",
            request_id=req.id,
            buttons=buttons,
        )
        return

    if area_match is None:
        conv["step"] = "clarify_area"
        conv["trade_id"] = str(trade_match[0])
        conv["trade_name"] = trade_match[1]
        if result.urgency:
            conv["pending_urgency"] = result.urgency
        if result.description:
            conv["pending_description"] = result.description
        req.conversation = conv
        quarter_names = [q[1] for q in quarters_data[:3]]
        buttons = [{"id": f"area_{qn.lower()}", "title": qn} for qn in quarter_names]
        await _send_reply(
            session, whatsapp, phone,
            "Which area do you need the service in?",
            request_id=req.id,
            buttons=buttons,
        )
        return

    # All info collected — move to confirmation
    req.trade_id = trade_match[0]
    req.quarter_id = area_match[0]
    req.urgency = result.urgency
    req.description = result.description or conv.get("pending_description", "")
    conv["trade_name"] = trade_match[1]
    conv["area_name"] = area_match[1]
    conv["urgency"] = result.urgency or "unknown"
    conv["description"] = req.description
    conv["step"] = "confirm"
    req.conversation = conv
    req.state = transition(req.state, RequestState.awaiting_confirmation)

    text = CONFIRM_TEMPLATE.format(
        trade=trade_match[1], area=area_match[1],
        urgency=result.urgency or "unknown",
        description=req.description or "your request",
    )
    await _send_reply(
        session, whatsapp, phone, text, request_id=req.id,
        buttons=[
            {"id": "confirm_yes", "title": "Yes, that's right"},
            {"id": "confirm_no", "title": "No, start over"},
        ],
    )


async def _start_fallback(
    session: AsyncSession,
    whatsapp: WhatsAppClient,
    phone: str,
    req: ServiceRequest,
    conv: dict,
    trades_data: list[tuple[uuid.UUID, str]],
) -> None:
    """NFR-REL-02: button-driven intake when AI is down."""
    conv["fallback_mode"] = True
    conv["step"] = "fallback_trade"
    req.conversation = conv
    trade_names = [t[1] for t in trades_data[:3]]
    buttons = [{"id": f"trade_{tn.lower()}", "title": tn} for tn in trade_names]
    await _send_reply(
        session, whatsapp, phone, FALLBACK_PROMPT, request_id=req.id,
        buttons=buttons,
    )


async def _handle_fallback_reply(
    session: AsyncSession,
    whatsapp: WhatsAppClient,
    phone: str,
    req: ServiceRequest,
    customer: Customer,
    conv: dict,
    button_reply_id: str,
) -> None:
    step = conv.get("step", "")
    trades_data = await _load_trades(session)
    quarters_data = await _load_quarters(session)

    if step == "fallback_trade" and button_reply_id.startswith("trade_"):
        trade_key = button_reply_id[6:]
        trade_match = next(
            ((tid, tn) for tid, tn in trades_data if tn.lower() == trade_key),
            None,
        )
        if trade_match:
            conv["trade_id"] = str(trade_match[0])
            conv["trade_name"] = trade_match[1]
            conv["step"] = "fallback_area"
            req.conversation = conv
            quarter_names = [q[1] for q in quarters_data[:3]]
            buttons = [{"id": f"area_{qn.lower()}", "title": qn} for qn in quarter_names]
            await _send_reply(
                session, whatsapp, phone, FALLBACK_AREA_PROMPT,
                request_id=req.id, buttons=buttons,
            )
        return

    if step == "fallback_area" and button_reply_id.startswith("area_"):
        area_key = button_reply_id[5:]
        area_match = next(
            ((qid, qn) for qid, qn in quarters_data if qn.lower() == area_key),
            None,
        )
        if area_match:
            trade_id = uuid.UUID(conv["trade_id"])
            trade_name = conv["trade_name"]
            req.trade_id = trade_id
            req.quarter_id = area_match[0]
            req.urgency = "unknown"
            req.description = "Service request via quick selection"
            conv["area_name"] = area_match[1]
            conv["urgency"] = "unknown"
            conv["description"] = req.description
            conv["step"] = "confirm"
            req.conversation = conv
            req.state = transition(req.state, RequestState.awaiting_confirmation)

            text = CONFIRM_TEMPLATE.format(
                trade=trade_name, area=area_match[1],
                urgency="unknown", description=req.description,
            )
            await _send_reply(
                session, whatsapp, phone, text, request_id=req.id,
                buttons=[
                    {"id": "confirm_yes", "title": "Yes, that's right"},
                    {"id": "confirm_no", "title": "No, start over"},
                ],
            )
        return

    if button_reply_id == "confirm_yes":
        await _handle_confirmation(
            session, whatsapp, phone, req, "", button_reply_id
        )
        return
    if button_reply_id == "confirm_no":
        await _handle_confirmation(
            session, whatsapp, phone, req, "", button_reply_id
        )
        return
