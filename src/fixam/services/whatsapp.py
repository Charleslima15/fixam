"""WhatsApp Cloud API interface and fake implementation."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import Protocol, runtime_checkable


@runtime_checkable
class WhatsAppClient(Protocol):
    async def send_text(
        self, to: str, text: str, *, reply_to: str | None = None
    ) -> str:
        """Send a free-form text message. Returns the Meta message ID."""
        ...

    async def send_template(
        self,
        to: str,
        template: str,
        components: list[dict] | None = None,
    ) -> str:
        """Send a template message. Returns the Meta message ID."""
        ...

    async def send_buttons(
        self, to: str, body: str, buttons: list[dict[str, str]]
    ) -> str:
        """Send interactive reply buttons. Max 3 buttons with 'id' and 'title'."""
        ...

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Download media by Meta media ID. Returns (data, content_type)."""
        ...


class FakeWhatsAppClient:
    """Test double that records all calls."""

    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.downloaded: list[str] = []
        self._counter = 0
        self._prefix = uuid.uuid4().hex[:8]

    def _next_id(self) -> str:
        self._counter += 1
        return f"wamid.fake_{self._prefix}_{self._counter:04d}"

    async def send_text(
        self, to: str, text: str, *, reply_to: str | None = None
    ) -> str:
        mid = self._next_id()
        self.sent_messages.append(
            {"to": to, "text": text, "reply_to": reply_to, "type": "text", "meta_message_id": mid}
        )
        return mid

    async def send_template(
        self,
        to: str,
        template: str,
        components: list[dict] | None = None,
    ) -> str:
        mid = self._next_id()
        self.sent_messages.append(
            {"to": to, "template": template, "components": components, "type": "template", "meta_message_id": mid}
        )
        return mid

    async def send_buttons(
        self, to: str, body: str, buttons: list[dict[str, str]]
    ) -> str:
        mid = self._next_id()
        self.sent_messages.append(
            {"to": to, "text": body, "buttons": buttons, "type": "interactive", "meta_message_id": mid}
        )
        return mid

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        self.downloaded.append(media_id)
        return b"fake-media-bytes", "image/jpeg"


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify Meta webhook HMAC-SHA256 signature (FR-MSG-01)."""
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
