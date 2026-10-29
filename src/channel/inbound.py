"""Where each channel keeps the text in its raw payload.

The raw payload is stored as the channel delivered it; reading the text out of
it is the channel's knowledge, not the core's. The bridge's shape arrives in
05b.
"""

from collections.abc import Mapping
from typing import Any


def text_of(channel: str, payload: Mapping[str, Any]) -> str:
    """The message's text, or "" when this channel or payload carries none."""
    if channel == "cli":
        text = payload.get("text")
        return text if isinstance(text, str) else ""
    return ""
