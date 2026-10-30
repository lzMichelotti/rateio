"""The worker's log: one line per message, written only after it committed,
carrying our ids and nothing personal."""

import logging
import random
from datetime import UTC, datetime

import pytest

from core import processor
from store import inbox
from store.books import link_conversation, link_identity

SENT = datetime(2026, 12, 26, 15, 0, tzinfo=UTC)


@pytest.fixture
def say(conn, book, caplog):
    caplog.set_level(logging.INFO, logger="rateio")
    link_conversation(conn, channel="cli", external_id="trip", book_id=book)
    link_identity(conn, channel="cli", external_id="seph", participant_id="seph")
    keys = iter(range(100))

    def send(text):
        inbound_id = inbox.receive(
            conn,
            channel="cli",
            conversation_external_id="trip",
            sender_external_id="seph",
            dedupe_key=f"test:{next(keys)}",
            raw_payload={"text": text},
            received_at=SENT,
        )
        caplog.clear()
        processor.process_pending(conn, rng=random.Random(0))
        return inbound_id, [r.getMessage() for r in caplog.records]

    return send


def fields(line):
    name, *pairs = line.split()
    return name, dict(pair.split("=", 1) for pair in pairs)


def test_a_confirmed_expense_logs_its_whole_path_once(conn, say):
    say("!gasto 300 jantar especial")
    code = conn.execute("SELECT code FROM confirmation").fetchone()[0]

    inbound_id, (line,) = say(f"!ok {code}")

    name, f = fields(line)
    entry_id, outbound_id = conn.execute(
        """
        SELECT e.id, o.id FROM journal_entry e, outbound_message o
        WHERE o.dedupe_key = %s
        """,
        (f"reply:{inbound_id}",),
    ).fetchone()
    assert name == "message.done"
    assert f["inbound"] == str(inbound_id)
    assert f["kind"] == "confirm"
    assert f["entry"] == str(entry_id)
    assert f["seq"] == "1"
    assert f["outbound"] == str(outbound_id)
    assert int(f["ms"]) >= 0


def test_refusals_and_parse_errors_say_why(say):
    _, (refused,) = say("!pix @lotti 50")
    _, (unread,) = say("!gasto trezentos jantar")

    assert fields(refused)[1]["refusal"] == "exceeds_debt"
    assert fields(unread)[1]["parse_error"] == "invalid_amount"


def test_a_rolled_back_message_never_logs_as_done(say, monkeypatch, caplog):
    def crash(*args, **kwargs):
        raise RuntimeError("died before the reply")

    monkeypatch.setattr(inbox, "enqueue_reply", crash)

    with pytest.raises(RuntimeError):
        say("!saldo")

    (line,) = [r.getMessage() for r in caplog.records]
    name, f = fields(line)
    assert name == "message.rolled_back"
    assert f["error"] == "RuntimeError"
    assert "inbound" in f


def test_nothing_personal_reaches_the_log(say):
    _, lines = say("!gasto 300 jantar especial")

    text = " ".join(lines)
    assert "jantar" not in text
    assert "Seph" not in text and "seph" not in text
    assert "300" not in text
