from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fixam.services.ai import AIClient
    from fixam.services.media import MediaStore
    from fixam.services.momo import MoMoClient
    from fixam.services.whatsapp import WhatsAppClient


@dataclass(frozen=True, slots=True)
class Deps:
    whatsapp: WhatsAppClient
    media: MediaStore
    ai: AIClient
    momo: MoMoClient
