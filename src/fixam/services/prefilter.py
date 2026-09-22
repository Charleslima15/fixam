"""Rule-based pre-filter so trivial messages never reach the model (FR-AI-06)."""
from __future__ import annotations

import re

_GREETING_WORDS = {
    "hello", "hi", "hey", "yo", "hiya", "howdy",
    "good morning", "good afternoon", "good evening", "good night",
    "bonjour", "bonsoir", "salut",
    "how far", "how you dey",
}

_THANKS_WORDS = {
    "thanks", "thank you", "thank u", "merci", "tnx", "thx",
    "god bless", "appreciated",
}

_OK_WORDS = {
    "ok", "okay", "k", "alright", "sure", "fine", "yes", "yep", "yeah",
    "no problem", "np", "cool", "oui", "d'accord",
}

_EMOJI_PATTERN = re.compile(
    r"^[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
    r"\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF"
    r"\U00002702-\U000027B0\U0000FE00-\U0000FE0F"
    r"\U0000200D\U00002640\U00002642\s]+$"
)


def is_trivial(text: str) -> bool:
    """Return True if the message is a greeting, thanks, emoji-only, or 'ok'-type."""
    if not text or not text.strip():
        return True
    cleaned = text.strip().lower()
    if cleaned in _OK_WORDS:
        return True
    if cleaned in _GREETING_WORDS or cleaned.rstrip("!. ") in _GREETING_WORDS:
        return True
    if cleaned in _THANKS_WORDS or cleaned.rstrip("!. ") in _THANKS_WORDS:
        return True
    if _EMOJI_PATTERN.match(cleaned):
        return True
    return False
