"""AI extraction interface and helpers (FR-AI-01 through FR-AI-10)."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fixam.models.model_call_log import ModelCallLog

logger = logging.getLogger(__name__)


class ExtractionResult(BaseModel):
    is_service_request: bool
    trade: str | None = None
    area: str | None = None
    urgency: str | None = None
    description: str | None = None
    language: str | None = None
    confidence: float | None = None


@runtime_checkable
class AIClient(Protocol):
    async def extract(
        self,
        messages: list[str],
        trades: list[str],
        quarters: list[str],
    ) -> ExtractionResult:
        ...


class FakeAIClient:
    """Test double driven by queued responses."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._responses: list[ExtractionResult | Exception] = []
        self._idx = 0

    def set_responses(self, *responses: ExtractionResult | Exception) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def extract(
        self,
        messages: list[str],
        trades: list[str],
        quarters: list[str],
    ) -> ExtractionResult:
        self.calls.append({"messages": messages, "trades": trades, "quarters": quarters})
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            if isinstance(resp, Exception):
                raise resp
            return resp
        return ExtractionResult(is_service_request=False)


async def check_daily_cap(
    session: AsyncSession, phone_hash: str, cap: int
) -> bool:
    """True if under the daily model call cap (FR-AI-07)."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    result = await session.execute(
        select(func.count())
        .select_from(ModelCallLog)
        .where(
            ModelCallLog.phone_hash == phone_hash,
            ModelCallLog.created_at >= today_start,
        )
    )
    return result.scalar_one() < cap


def log_model_call(
    session: AsyncSession,
    phone_hash: str,
    request_id: uuid.UUID | None,
    messages: list[str],
    result: ExtractionResult | None,
    latency_ms: int,
    *,
    is_error: bool = False,
) -> None:
    """Record a model call (FR-AI-10)."""
    input_size = sum(len(m) for m in messages)
    log = ModelCallLog(
        id=uuid.uuid4(),
        phone_hash=phone_hash,
        request_id=request_id,
        input_size=input_size,
        output=result.model_dump() if result else None,
        latency_ms=latency_ms,
        cost_estimate_fcfa=max(1, input_size // 1000),
        error=is_error,
    )
    session.add(log)


async def extract_with_retry(
    ai: AIClient,
    messages: list[str],
    trades: list[str],
    quarters: list[str],
    *,
    session: AsyncSession,
    request_id: uuid.UUID | None,
    phone_hash: str,
) -> ExtractionResult | None:
    """Call AI with one retry on failure (FR-AI-02). Returns None if both fail."""
    for attempt in range(2):
        start = time.monotonic()
        try:
            result = await ai.extract(messages, trades, quarters)
            latency_ms = int((time.monotonic() - start) * 1000)
            log_model_call(
                session, phone_hash, request_id, messages, result, latency_ms
            )
            return result
        except Exception:
            latency_ms = int((time.monotonic() - start) * 1000)
            log_model_call(
                session, phone_hash, request_id, messages, None, latency_ms,
                is_error=True,
            )
            if attempt == 0:
                logger.warning("AI extract failed, retrying (attempt 1)")
                continue
            logger.error("AI extract failed after retry")
            return None
    return None
