"""What each channel's raw payload says, in the grammar's terms.

The raw payload is stored as the channel delivered it; reading the text out of
it, and turning the channel's way of naming people into participants, is the
channel's knowledge, not the core's.
"""

from collections.abc import Mapping
from typing import Any

from channel import whatsapp


def text_of(
    channel: str, payload: Mapping[str, Any], identities: Mapping[str, str]
) -> str:
    """The message's text for the grammar, or "" when it carries none.

    identities maps the channel's identifiers to participant ids; a channel
    that has mentions uses it to name people the way the grammar reads them.
    """
    if channel == "cli":
        text = payload.get("text")
        return text if isinstance(text, str) else ""
    if channel == "whatsapp_unofficial":
        return whatsapp.text_of(payload, identities)
    return ""


def sender_key(channel: str, external_id: str) -> str:
    """The identifier to look the sender up by in channel_identity."""
    if channel == "whatsapp_unofficial":
        return whatsapp.normalize_jid(external_id)
    return external_id
