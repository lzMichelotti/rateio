"""The processor through the inbox, the way the CLI and the bridge feed it.

The book runs 2026-12-25 to 2027-01-05; its members are the five seeded people,
each linked on the cli channel by their own id.
"""

import random
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from core import processor
from ledger.positions import positions
from store import inbox
from store.ledger import book_postings

START = datetime(2026, 12, 26, 15, 0, tzinfo=UTC)


@pytest.fixture
def chat(conn, book):
    conversation_id = conn.execute(
        """
        INSERT INTO conversation (channel, external_id, kind, book_id)
        VALUES ('cli', 'trip', 'group', %s)
        RETURNING id
        """,
        (book,),
    ).fetchone()[0]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO channel_identity (channel, external_id, participant_id) "
            "VALUES ('cli', %s, %s)",
            [(pid, pid) for pid in ["lotti", "luis", "seph", "vini", "vitor"]],
        )
    return Chat(conn, conversation_id)


class Chat:
    """Say something as someone; get the bot's reply to exactly that message."""

    def __init__(self, conn, conversation_id):
        self.conn = conn
        self.conversation_id = conversation_id
        self.clock = (START + timedelta(minutes=i) for i in count())
        self.keys = count()

    def send(self, who, text, at=None, conversation="trip"):
        return inbox.receive(
            self.conn,
            channel="cli",
            conversation_external_id=conversation,
            sender_external_id=who,
            dedupe_key=f"test:{next(self.keys)}",
            raw_payload={"text": text},
            received_at=at or next(self.clock),
        )

    def say(self, who, text, at=None):
        inbound_id = self.send(who, text, at)
        processor.process_pending(self.conn, rng=random.Random(0))
        return self.reply(inbound_id)

    def reply(self, inbound_id):
        row = self.conn.execute(
            "SELECT body FROM outbound_message WHERE dedupe_key = %s",
            (f"reply:{inbound_id}",),
        ).fetchone()
        return None if row is None else row[0]

    def count(self, table, inbound_id):
        column = "inbound_message_id" if table == "command" else "dedupe_key"
        value = inbound_id if table == "command" else f"reply:{inbound_id}"
        return self.conn.execute(
            f"SELECT count(*) FROM {table} WHERE {column} = %s", (value,)
        ).fetchone()[0]


def code_in(reply):
    return reply.split("!ok ")[1].split()[0]


def test_an_expense_is_proposed_then_recorded(chat, conn, book):
    proposed = chat.say("lotti", "!gasto 300 gasolina")
    recorded = chat.say("lotti", f"!ok {code_in(proposed)}")

    assert proposed.startswith("Lotti lançou R$ 300,00 de gasolina (26/12)")
    assert recorded == "L1 registrado: gasolina, R$ 300,00, pago por Lotti."
    assert positions(book_postings(conn, book))["lotti"] == 24000


def test_the_same_message_processed_twice_is_one_command_and_one_reply(chat, conn):
    inbound_id = chat.send("lotti", "!gasto 300 gasolina")

    assert processor.process(conn, inbound_id, rng=random.Random(0)) is True
    assert processor.process(conn, inbound_id, rng=random.Random(0)) is False
    assert chat.count("command", inbound_id) == 1
    assert chat.count("outbound_message", inbound_id) == 1


def test_a_text_that_is_not_a_command_is_answered_without_a_command(chat):
    inbound_id = chat.send("lotti", "oi bot")
    processor.process_pending(chat.conn, rng=random.Random(0))

    assert "!ajuda" in chat.reply(inbound_id)
    assert chat.count("command", inbound_id) == 0


def test_a_refusal_is_answered_and_its_command_kept(chat):
    inbound_id = chat.send("lotti", "!pix @luis 50")
    processor.process_pending(chat.conn, rng=random.Random(0))

    assert chat.reply(inbound_id) == "Lotti não deve nada no momento."
    assert chat.count("command", inbound_id) == 1


def test_a_crash_after_the_entry_leaves_nothing_and_a_retry_does_it_once(
    chat, conn, book, monkeypatch
):
    proposed = chat.say("lotti", "!gasto 300 gasolina")
    inbound_id = chat.send("lotti", f"!ok {code_in(proposed)}")

    def crash(*args, **kwargs):
        raise RuntimeError("the process died before writing the reply")

    with monkeypatch.context() as patched:
        patched.setattr(inbox, "enqueue_reply", crash)
        with pytest.raises(RuntimeError):
            processor.process_pending(conn, rng=random.Random(0))

    assert conn.execute(
        "SELECT count(*) FROM journal_entry WHERE book_id = %s", (book,)
    ).fetchone() == (0,)
    assert chat.count("command", inbound_id) == 0
    assert chat.reply(inbound_id) is None

    processor.process_pending(conn, rng=random.Random(0))

    assert conn.execute(
        "SELECT count(*) FROM journal_entry WHERE book_id = %s", (book,)
    ).fetchone() == (1,)
    assert (
        chat.reply(inbound_id) == "L1 registrado: gasolina, R$ 300,00, pago por Lotti."
    )


def test_half_past_eleven_at_night_in_sao_paulo_is_still_that_day(chat):
    # 02:30 UTC on the 27th is 23:30 on the 26th in Sao Paulo.
    late = datetime(2026, 12, 27, 2, 30, tzinfo=UTC)

    assert "(26/12)" in chat.say("lotti", "!gasto 80 pizza", at=late)


def test_the_payee_rejects_and_the_payer_cancels(chat):
    chat.say("lotti", f"!ok {code_in(chat.say('lotti', '!gasto 500 jantar'))}")
    first = code_in(chat.say("luis", "!pix @lotti 100"))
    second = code_in(chat.say("vini", "!pix @lotti 100"))

    assert chat.say("lotti", f"!nao {first}").startswith(
        "Lotti disse que o pix de R$ 100,00 de Luis não chegou"
    )
    assert chat.say("vini", f"!nao {second}").startswith("Vini cancelou o pix")


def test_repeating_an_ok_says_nothing_changed(chat):
    code = code_in(chat.say("lotti", "!gasto 300 gasolina"))
    chat.say("lotti", f"!ok {code}")

    assert (
        chat.say("lotti", f"!ok {code}") == f"{code} já estava confirmado. Nada mudou."
    )


def test_strangers_and_non_members_are_answered_without_touching_the_book(
    chat, conn, make_book
):
    other_book = make_book(["luis"])
    conn.execute(
        "UPDATE conversation SET book_id = %s WHERE id = %s",
        (other_book, chat.conversation_id),
    )

    assert chat.say("nobody", "!saldo").startswith("Não sei quem é você")
    assert chat.say("lotti", "!saldo") == "Você não faz parte desta viagem."


def test_an_unknown_chat_is_processed_in_silence(chat):
    inbound_id = chat.send("lotti", "!saldo", conversation="elsewhere")
    processor.process_pending(chat.conn, rng=random.Random(0))

    assert chat.reply(inbound_id) is None
    assert chat.conn.execute(
        "SELECT processed_at IS NOT NULL FROM inbound_message WHERE id = %s",
        (inbound_id,),
    ).fetchone() == (True,)


def test_the_read_commands_answer(chat):
    chat.say("lotti", f"!ok {code_in(chat.say('lotti', '!gasto 300 gasolina'))}")

    assert chat.say("vini", "!saldo").startswith("Total gasto: R$ 300,00")
    assert chat.say("vini", "!extrato").startswith("L1  26/12  gasolina")
    assert "Para zerar todo mundo:" in chat.say("vini", "!acerto")
    assert chat.say("vini", "!ajuda").startswith("Comandos:")
