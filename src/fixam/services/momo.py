"""MTN MoMo Collections API interface and fake implementation."""
from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable


@runtime_checkable
class MoMoClient(Protocol):
    async def request_to_pay(
        self,
        reference_id: str,
        phone: str,
        amount: int,
        external_id: str,
        note: str,
    ) -> None:
        """POST /collection/v1_0/requesttopay — 202 Accepted, empty body."""
        ...

    async def get_payment_status(self, reference_id: str) -> dict:
        """GET /collection/v1_0/requesttopay/{referenceId}.
        Returns dict with at least: status, financialTransactionId."""
        ...


class FakeMoMoClient:
    """Test double that records calls and returns configurable statuses."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self._status_overrides: dict[str, dict] = {}

    def set_status(self, reference_id: str, status: dict) -> None:
        self._status_overrides[reference_id] = status

    async def request_to_pay(
        self,
        reference_id: str,
        phone: str,
        amount: int,
        external_id: str,
        note: str,
    ) -> None:
        self.requests.append({
            "reference_id": reference_id,
            "phone": phone,
            "amount": amount,
            "external_id": external_id,
            "note": note,
        })

    async def get_payment_status(self, reference_id: str) -> dict:
        if reference_id in self._status_overrides:
            return self._status_overrides[reference_id]
        return {
            "status": "SUCCESSFUL",
            "financialTransactionId": f"fake-txn-{reference_id[:8]}",
            "externalId": reference_id,
            "amount": "0",
            "currency": "XAF",
        }
