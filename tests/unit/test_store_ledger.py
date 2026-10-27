import random
from datetime import date

from ledger.expense import record_expense
from ledger.positions import positions
from ledger.workflow import Action
from store.confirmations import propose_expense, resolve
from store.ledger import book_postings

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]


def expense(seq: int, payer_id: str, total_cents: int):
    """The domain entry the store should have written for this expense."""
    return record_expense(
        seq=seq,
        occurred_on=date(2026, 12, 26),
        payer_id=payer_id,
        total_cents=total_cents,
        description="fuel",
        participant_ids=FIVE,
    )


def test_first_entry_of_a_book_gets_seq_1(spend):
    recorded = spend("lotti", 30000)

    assert recorded.created
    assert recorded.seq == 1


def test_entry_and_postings_are_written_and_read_back(conn, book, spend):
    recorded = spend("lotti", 18743)

    kind, author, payload, confirmation_id = conn.execute(
        """
        SELECT kind, author_id, payload, confirmation_id
        FROM journal_entry WHERE id = %s
        """,
        (recorded.entry_id,),
    ).fetchone()
    assert (kind, author) == ("expense", "lotti")
    assert confirmation_id is not None
    assert payload == {
        "total_cents": 18743,
        "description": "fuel",
        "remainder_offset": 1,
        "split_rule": "even",
    }
    assert book_postings(conn, book) == list(expense(1, "lotti", 18743).postings)


def test_the_same_command_twice_produces_one_entry(conn, book, make_command):
    command_id = make_command()

    def propose_and_confirm():
        proposal = propose_expense(
            conn,
            book_id=book,
            command_id=command_id,
            payer_id="lotti",
            total_cents=30000,
            description="fuel",
            occurred_on=date(2026, 12, 26),
            participant_ids=FIVE,
            rng=random.Random(0),
        )
        return resolve(
            conn,
            book_id=book,
            code=proposal.code,
            action=Action.CONFIRM,
            actor="lotti",
        )

    first, again = propose_and_confirm(), propose_and_confirm()

    entries, postings = conn.execute(
        """
        SELECT (SELECT count(*) FROM journal_entry WHERE book_id = %s),
               (SELECT count(*) FROM posting p JOIN journal_entry e ON e.id = p.entry_id
                WHERE e.book_id = %s)
        """,
        (book, book),
    ).fetchone()
    assert first.changed and not again.changed
    assert (entries, postings) == (1, 6)


def test_consecutive_entries_rotate_the_remainder(conn, book, spend):
    spend("lotti", 18743)
    spend("lotti", 18743)

    rows = conn.execute(
        """
        SELECT e.seq, (e.payload ->> 'remainder_offset')::int, p.participant_id
        FROM journal_entry e JOIN posting p ON p.entry_id = e.id
        WHERE e.book_id = %s AND p.role = 'share' AND p.amount_cents = -3749
        ORDER BY e.seq, p.participant_id
        """,
        (book,),
    ).fetchall()
    assert rows == [
        (1, 1, "luis"),
        (1, 1, "seph"),
        (1, 1, "vini"),
        (2, 2, "seph"),
        (2, 2, "vini"),
        (2, 2, "vitor"),
    ]


def test_positions_from_the_database_match_positions_in_memory(conn, book, spend):
    in_memory = []
    for payer_id, total_cents in [("lotti", 30000), ("luis", 10000), ("vini", 18743)]:
        recorded = spend(payer_id, total_cents)
        in_memory.extend(expense(recorded.seq, payer_id, total_cents).postings)

    assert positions(book_postings(conn, book)) == positions(in_memory)
