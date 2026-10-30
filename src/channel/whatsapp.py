"""The WhatsApp channel's translator: the bridge's raw message into grammar text.

The bridge stores each message as WhatsApp delivered it, mentions included, and
knows nothing about people. Here a mention becomes the participant it names, so
the grammar reads `!pix @luis 40` and never learns where the text came from.

A mention in the text is the digits of a JID (`@100000000000002`), while the
message lists the JIDs it mentions apart (`contextInfo.mentionedJid`):

- a mention of someone linked in `channel_identity` becomes `@<participant_id>`;
- an unlinked mention at the very start is removed: it is how a message is
  addressed to the bot (`@bot !saldo`), which the bridge already used to let
  the message in, and the bot is not a participant;
- an unlinked mention anywhere else becomes `@?`, so a reply never echoes the
  digits of someone's identifier back to the group.
"""

import re
from collections.abc import Mapping
from typing import Any

_MENTION = re.compile(r"@(\d+)(.*)", re.ASCII)
UNKNOWN_MENTION = "@?"


def normalize_jid(jid: str) -> str:
    """The person, without the device: "100000000000009:17@lid" is
    "100000000000009@lid". A JID names one account on several devices."""
    user, at, server = jid.partition("@")
    return f"{user.split(':')[0]}{at}{server}"


def text_of(payload: Mapping[str, Any], identities: Mapping[str, str]) -> str:
    """The grammar's text for a raw WhatsApp message, or "" if it carries none.

    identities maps a normalized JID to the participant it is linked to.
    """
    message = payload.get("message")
    if not isinstance(message, Mapping):
        return ""
    extended = message.get("extendedTextMessage")
    extended = extended if isinstance(extended, Mapping) else {}
    text = message.get("conversation")
    if not isinstance(text, str):
        text = extended.get("text")
    if not isinstance(text, str):
        return ""
    return _resolve_mentions(text, _mentioned(extended), identities)


def _mentioned(extended: Mapping[str, Any]) -> dict[str, str]:
    """Digits as they appear in the text -> the normalized JID mentioned."""
    context = extended.get("contextInfo")
    jids = context.get("mentionedJid") if isinstance(context, Mapping) else None
    if not isinstance(jids, list):
        return {}
    by_digits = {}
    for jid in jids:
        if isinstance(jid, str):
            normalized = normalize_jid(jid)
            by_digits[normalized.partition("@")[0]] = normalized
    return by_digits


def _resolve_mentions(
    text: str, mentioned: Mapping[str, str], identities: Mapping[str, str]
) -> str:
    words: list[str] = []
    leading = True  # nothing but mentions so far
    for word in text.split():
        match = _MENTION.fullmatch(word)
        if match is None or match[1] not in mentioned:
            words.append(word)  # plain text, or "@123" typed without mentioning
            leading = False
            continue
        participant_id = identities.get(mentioned[match[1]])
        if participant_id is not None:
            words.append(f"@{participant_id}{match[2]}")
            leading = False
        elif not leading:
            words.append(f"{UNKNOWN_MENTION}{match[2]}")
        # an unlinked mention while leading addresses the bot: dropped
    return " ".join(words)
