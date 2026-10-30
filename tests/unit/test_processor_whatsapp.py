"""The processor reading WhatsApp messages as the bridge lands them (fake ids)."""

import random
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from core import processor
from store import inbox
from store.books import link_conversation, link_identity

GROUP = "120000000000000001@g.us"
LID = {"lotti": "100000000000001@lid", "luis": "100000000000002@lid"}
BOT = "100000000000009@lid"
START = datetime(2026, 12, 26, 15, 0, tzinfo=UTC)


@pytest.fixture
def group(conn, book):
    link_conversation(
        conn, channel="whatsapp_unofficial", external_id=GROUP, book_id=book
    )
    for pid, lid in LID.items():
        link_identity(
            conn, channel="whatsapp_unofficial", external_id=lid, participant_id=pid
        )
    keys = count()
    clock = (START + timedelta(minutes=i) for i in count())

    def say(sender, text, *mentions):
        message = (
            {"conversation": text}
            if not mentions
            else {
                "extendedTextMessage": {
                    "text": text,
                    "contextInfo": {"mentionedJid": list(mentions)},
                }
            }
        )
        inbound_id = inbox.receive(
            conn,
            channel="whatsapp_unofficial",
            conversation_external_id=GROUP,
            sender_external_id=sender,
            dedupe_key=f"wa:{GROUP}:FAKE{next(keys)}",
            raw_payload={
                "key": {"remoteJid": GROUP, "participant": sender},
                "message": message,
            },
            received_at=next(clock),
        )
        processor.process_pending(conn, rng=random.Random(0))
        return conn.execute(
            "SELECT body FROM outbound_message WHERE dedupe_key = %s",
            (f"reply:{inbound_id}",),
        ).fetchone()[0]

    return say


def test_a_sender_with_a_device_suffix_is_recognised(group):
    assert group("100000000000001:4@lid", "!saldo").startswith("Total gasto")


def test_a_pix_mentioning_a_friend_is_declared_to_that_participant(group, conn):
    code = group(LID["luis"], "!gasto 500 jantar").split("!ok ")[1].split()[0]
    group(LID["luis"], f"!ok {code}")

    reply = group(LID["lotti"], "!pix @100000000000002 100", LID["luis"])

    assert reply.startswith("Lotti diz que mandou um pix de R$ 100,00 para Luis.")
    assert conn.execute(
        "SELECT payer_id, payee_id, amount_cents FROM settlement"
    ).fetchall() == [("lotti", "luis", 10000)]


def test_mentioning_the_bot_in_front_of_a_command_runs_the_command(group):
    assert group(LID["lotti"], "@100000000000009 !saldo", BOT).startswith("Total gasto")


def test_mentioning_the_bot_with_free_text_points_to_help(group):
    assert "!ajuda" in group(LID["lotti"], "@100000000000009 quanto eu devo?", BOT)
