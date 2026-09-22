"""Media storage interface and fake implementation."""
from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable


@runtime_checkable
class MediaStore(Protocol):
    async def store(self, key: str, data: bytes, content_type: str) -> str:
        """Store media bytes. Returns the storage key."""
        ...


class FakeMediaStore:
    """Test double that records store calls in memory."""

    def __init__(self) -> None:
        self.stored: dict[str, tuple[bytes, str]] = {}

    async def store(self, key: str, data: bytes, content_type: str) -> str:
        storage_key = f"fake/{key}"
        self.stored[storage_key] = (data, content_type)
        return storage_key
