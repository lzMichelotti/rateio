from datetime import date

from ledger.expense import record_expense
from ledger.positions import positions
from store.ledger import append_entry, book_postings

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]


def expense(payer_id: str, total_cents: int):
    """A builder: the store hands it the seq, it returns the domain entry."""
    return lambda seq: record_expense(
        seq=seq,
        occurred_on=date(2026, 12, 26),
        payer_id=payer_id,
        total_cents=total_cents,
        description="fuel",
        participant_ids=FIVE,
    )


def test_first_entry_of_a_book_gets_seq_1(conn, book, make_command):
    recorded = append_entry(
        conn, book_id=book, command_id=make_command(), build=expense("lotti", 30000)
    )

    assert recorded.created
    assert recorded.seq == 1


def test_entry_and_postings_are_written_and_read_back(conn, book, make_command):
    build = expense("lotti", 18743)
    recorded = append_entry(conn, book_id=book, command_id=make_command(), build=build)

    kind, author, payload = conn.execute(
        "SELECT kind, author_id, payload FROM journal_entry WHERE id = %s",
        (recorded.entry_id,),
    ).fetchone()
    assert (kind, author) == ("expense", "lotti")
    assert payload == {
        "total_cents": 18743,
        "description": "fuel",
        "remainder_offset": 1,
        "split_rule": "even",
    }
    assert book_postings(conn, book) == list(build(1).postings)


def test_the_same_command_twice_produces_one_entry(conn, book, make_command):
    command_id = make_command()
    first = append_entry(
        conn, book_id=book, command_id=command_id, build=expense("lotti", 30000)
    )
    again = append_entry(
        conn, book_id=book, command_id=command_id, build=expense("lotti", 30000)
    )

    entries, postings = conn.execute(
        """
        SELECT (SELECT count(*) FROM journal_entry WHERE book_id = %s),
               (SELECT count(*) FROM posting p JOIN journal_entry e ON e.id = p.entry_id
                WHERE e.book_id = %s)
        """,
        (book, book),
    ).fetchone()
    assert first.created and not again.created
    assert (again.entry_id, again.seq) == (first.entry_id, first.seq)
    assert (entries, postings) == (1, 6)


def test_consecutive_entries_rotate_the_remainder(conn, book, make_command):
    for _ in range(2):
        append_entry(
            conn, book_id=book, command_id=make_command(), build=expense("lotti", 18743)
        )

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


def test_positions_from_the_database_match_positions_in_memory(
    conn, book, make_command
):
    builds = [expense("lotti", 30000), expense("luis", 10000), expense("vini", 18743)]
    in_memory = []
    for build in builds:
        recorded = append_entry(
            conn, book_id=book, command_id=make_command(), build=build
        )
        in_memory.extend(build(recorded.seq).postings)

    assert positions(book_postings(conn, book)) == positions(in_memory)
