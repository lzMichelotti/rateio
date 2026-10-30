import random

import pytest

from cli.chat import Session, UnknownChatError, run
from store.books import link_conversation, link_identity

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]


@pytest.fixture
def session(conn, book):
    link_conversation(conn, channel="cli", external_id="trip", book_id=book)
    for pid in FIVE:
        link_identity(conn, channel="cli", external_id=pid, participant_id=pid)
    return Session(conn, chat="trip", rng=random.Random(0))


def reader(lines):
    pending = iter(lines)
    return lambda prompt: next(pending, None)


def test_a_line_said_gets_its_reply_and_the_reply_is_marked_sent(session, conn):
    (reply,) = session.say("lotti", "!ajuda")

    assert reply.startswith("Como usar:")
    assert conn.execute(
        "SELECT status, sent_at IS NOT NULL, attempts FROM outbound_message "
        "WHERE conversation_id = %s",
        (session.conversation_id,),
    ).fetchall() == [("sent", True, 1)]
    assert session.deliver() == []


def test_only_this_chats_replies_are_delivered(session, conn, make_book):
    other = make_book()
    link_conversation(conn, channel="cli", external_id="other", book_id=other)
    Session(conn, chat="other", rng=random.Random(0)).say("lotti", "!saldo")

    assert session.deliver() == []


def test_an_unknown_chat_is_refused(conn):
    with pytest.raises(UnknownChatError):
        Session(conn, chat="nowhere", rng=random.Random(0))


def test_switching_member_mid_conversation(session):
    out = []

    run(
        reader(["!gasto 300 gasolina", "/as luis", "!saldo"]),
        session,
        handle="lotti",
        write=out.append,
    )

    assert out[0].startswith("  bot: Lotti lançou R$ 300,00 de gasolina")
    assert out[1].startswith("  bot: Total gasto: R$ 0,00")


def test_terminal_lines_are_never_sent_to_the_bot(session, conn):
    out = []

    run(
        reader(["/help", "/as luis", "", "/quit", "!saldo"]),
        session,
        handle="lotti",
        write=out.append,
    )

    assert out == ["(terminal commands: /as <handle>, /quit)"]
    assert conn.execute("SELECT count(*) FROM inbound_message").fetchone() == (0,)
