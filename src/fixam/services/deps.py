from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fixam.services.whatsapp import WhatsAppClient
    from fixam.services.media import MediaStore


@dataclass(frozen=True, slots=True)
class Deps:
    whatsapp: WhatsAppClient
    media: MediaStore
