"""A whole trip, spoken through the cli channel: the same entry point as make chat.

Set up with the operator commands, as production will be. Every line becomes an
inbound_message, the processor reads the inbox, every reply leaves through
outbound_message. Nothing here calls the domain directly to act; it only reads
the book at the end to check what the conversation left behind.

The trip ends on the positions and plan proven minimal in stage 04. The clock
and the codes are fixed: messages carry explicit times, and the code generator
is seeded; codes are read from the replies, never guessed.
"""

import random
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from cli import admin
from cli.chat import Session
from ledger.model import Role
from ledger.positions import positions, projected_positions
from ledger.settlement_plan import Transfer, settlement_plan
from store.books import find_book
from store.confirmations import declared_settlements
from store.ledger import book_entries, book_postings

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


class Trip:
    def __init__(self, conn):
        self.session = Session(conn, chat="carnival", rng=random.Random(0))
        self.at = datetime(2027, 2, 20, 10, 0, tzinfo=SAO_PAULO)
        self.replies: list[str] = []

    def say(self, who: str, text: str) -> str:
        """One message, one minute after the previous; exactly one reply."""
        self.at += timedelta(minutes=1)
        (reply,) = self.session.say(who, text, at=self.at)
        self.replies.append(reply)
        return reply

    def spend(self, who: str, text: str) -> str:
        """!gasto, then the author's !ok with the code the bot gave."""
        proposed = self.say(who, text)
        return self.say(who, f"!ok {code(proposed)}")


def code(reply: str) -> str:
    match = re.search(r"!ok ([A-Z][2-9])", reply)
    assert match, reply
    return match[1]


def set_up(conn):
    for argv in [
        [
            "create-book",
            "Carnival 2027",
            "--starts",
            "2027-02-15",
            "--ends",
            "2027-02-25",
        ],
        ["add-member", "Carnival 2027", *FIVE],
        *(["link-identity", "cli", pid, pid] for pid in FIVE),
        ["link-conversation", "cli", "carnival", "Carnival 2027"],
    ]:
        assert admin.main(argv, conn) == 0
    return find_book(conn, "Carnival 2027")


def test_a_whole_trip_ends_on_the_known_positions_and_plan(conn):
    book = set_up(conn)
    trip = Trip(conn)

    trip.spend("vini", "!gasto 300 gasolina")
    trip.spend("vitor", "!gasto 187,43 mercado")
    trip.spend("lotti", "!gasto 1250 airbnb")

    pix = trip.say("vini", "!pix @lotti 40")
    assert "Vini diz que mandou *R$ 40,00* para Lotti" in pix
    trip.say("lotti", f"!ok {code(pix)}")

    trip.spend("lotti", "!gasto 1200 lanche")
    undo = trip.say("lotti", "!estorna L5")
    assert trip.say("lotti", f"!ok {code(undo)}") == (
        "✅ *Desfeito: L5*\nlanche · R$ 1.200,00 · registrado como L6"
    )
    trip.spend("lotti", "!gasto 120 lanche")

    trip.spend("seph", "!gasto 46,80 pedagio")
    trip.spend("seph", "!gasto 412 jantar")
    again = trip.say("seph", "!gasto 412 jantar")  # two minutes after the first

    trip.spend("luis", "!gasto 83,37 caipirinhas 18/02")
    trip.spend("luis", "!gasto 890 barco")

    acerto = trip.say("lotti", "!acerto")

    # The positions, as replayed from the ledger.
    postings = book_postings(conn, book)
    assert positions(postings) == {
        "lotti": 67208,
        "luis": 31545,
        "seph": -19912,
        "vini": -31792,
        "vitor": -47049,
    }

    # The plan, as data and as the group read it.
    assert settlement_plan(
        projected_positions(postings, declared_settlements(conn, book))
    ) == (
        Transfer("seph", "lotti", 19912),
        Transfer("vini", "lotti", 31792),
        Transfer("vitor", "lotti", 15504),
        Transfer("vitor", "luis", 31545),
    )
    assert acerto.splitlines()[-4:] == [
        "• Seph paga *R$ 199,12* a Lotti",
        "• Vini paga *R$ 317,92* a Lotti",
        "• Vitor paga *R$ 155,04* a Lotti",
        "• Vitor paga *R$ 315,45* a Luis",
    ]

    # The market's three leftover cents went to seph, vini and vitor, by seq 2,
    # and no message ever mentioned them.
    market = book_entries(conn, book)[1]
    assert market.description == "mercado"
    assert {
        p.participant_id: -p.amount_cents
        for p in market.postings
        if p.role is Role.SHARE
    } == {"lotti": 3748, "luis": 3748, "seph": 3749, "vini": 3749, "vitor": 3749}
    assert not any("centavo" in reply for reply in trip.replies)

    # Break 1 asked, with a code, and decided nothing.
    assert "há 2 min" in again
    assert conn.execute(
        "SELECT status FROM confirmation WHERE book_id = %s AND code = %s",
        (book, code(again)),
    ).fetchone() == ("open",)
    assert len(book_entries(conn, book)) == 11

    # Every message was processed and answered exactly once, and every answer sent.
    assert (
        conn.execute(
            """
        SELECT count(*), count(o.id), count(*) FILTER (WHERE o.status = 'sent')
        FROM inbound_message i
        LEFT JOIN outbound_message o ON o.dedupe_key = 'reply:' || i.id
        WHERE i.conversation_external_id = 'carnival' AND i.processed_at IS NOT NULL
        """
        ).fetchone()
        == (len(trip.replies),) * 3
    )
