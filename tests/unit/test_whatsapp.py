"""The WhatsApp translator, on payloads shaped like the bridge's (fake ids)."""

import pytest

from channel.inbound import sender_key, text_of
from channel.whatsapp import normalize_jid

LOTTI = "100000000000001@lid"
LUIS = "100000000000002@lid"
BOT = "100000000000009@lid"
STRANGER = "100000000000007@lid"
IDENTITIES = {LOTTI: "lotti", LUIS: "luis"}


def plain(text):
    return {"message": {"conversation": text}}


def mentioning(text, *jids):
    return {
        "message": {
            "extendedTextMessage": {
                "text": text,
                "contextInfo": {"mentionedJid": list(jids)},
            }
        }
    }


def read(payload):
    return text_of("whatsapp_unofficial", payload, IDENTITIES)


def test_a_plain_command_passes_through():
    assert read(plain("!gasto 300 gasolina")) == "!gasto 300 gasolina"


def test_a_mention_of_a_linked_person_becomes_their_participant_id():
    assert read(mentioning("!pix @100000000000002 40", LUIS)) == "!pix @luis 40"


def test_a_mention_of_the_bot_in_front_only_addresses_it():
    assert read(mentioning("@100000000000009 !saldo", BOT)) == "!saldo"


def test_a_mention_with_a_device_suffix_is_the_same_person():
    assert read(mentioning("!pix @100000000000002 40", "100000000000002:3@lid")) == (
        "!pix @luis 40"
    )


def test_an_unlinked_mention_inside_a_command_never_echoes_its_digits():
    assert read(mentioning("!pix @100000000000007 40", STRANGER)) == "!pix @? 40"


def test_digits_typed_after_an_at_sign_without_a_mention_are_left_alone():
    assert read(plain("!gasto 50 presente @123")) == "!gasto 50 presente @123"


def test_mention_and_punctuation_stay_together():
    assert read(mentioning("!pix @100000000000002, 40", LUIS)) == "!pix @luis, 40"


@pytest.mark.parametrize(
    "payload",
    [{}, {"message": None}, {"message": {"imageMessage": {}}}, {"message": "x"}],
)
def test_a_message_without_text_reads_as_empty(payload):
    assert read(payload) == ""


def test_the_device_suffix_is_not_the_person():
    assert normalize_jid("100000000000009:17@lid") == BOT
    assert normalize_jid(BOT) == BOT
    assert sender_key("whatsapp_unofficial", "100000000000001:2@lid") == LOTTI
    assert sender_key("cli", "lotti:2") == "lotti:2"
