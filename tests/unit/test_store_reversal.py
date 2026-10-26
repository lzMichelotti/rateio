from datetime import date

import pytest

from ledger.expense import record_expense
from ledger.model import EntryKind, Posting
from ledger.reversal import AlreadyReversedError
from store.ledger import (
    EntryNotFoundError,
    append_entry,
    append_reversal,
    book_entries,
)

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]


def fuel(total_cents: int):
    return lambda seq: record_expense(
        seq=seq,
        occurred_on=date(2026, 12, 26),
        payer_id="lotti",
        total_cents=total_cents,
        description="fuel",
        participant_ids=FIVE,
    )


def record(conn, book, make_command, total_cents=30000):
    return append_entry(
        conn, book_id=book, command_id=make_command(), build=fuel(total_cents)
    )


def reversal_command(make_command, **kwargs):
    return make_command("luis", kind="reverse", **kwargs)


def test_reversal_is_linked_to_the_original_and_keeps_its_date(
    conn, book, make_command
):
    original = record(conn, book, make_command)
    reversal = append_reversal(
        conn,
        book_id=book,
        command_id=reversal_command(make_command),
        target_seq=1,
        author_id="luis",
    )

    kind, occurred_on, reverses_entry_id, payload = conn.execute(
        """
        SELECT kind, occurred_on, reverses_entry_id, payload
        FROM journal_entry WHERE id = %s
        """,
        (reversal.entry_id,),
    ).fetchone()
    assert (kind, occurred_on) == ("reversal", date(2026, 12, 26))
    assert reverses_entry_id == original.entry_id
    assert payload["total_cents"] == -30000


def test_book_entries_reads_back_what_the_domain_built(conn, book, make_command):
    record(conn, book, make_command)
    append_reversal(
        conn,
        book_id=book,
        command_id=reversal_command(make_command),
        target_seq=1,
        author_id="luis",
    )

    original, reversal = book_entries(conn, book)
    assert original == fuel(30000)(1)
    assert reversal.kind is EntryKind.REVERSAL
    assert reversal.reverses_seq == 1
    assert reversal.postings == tuple(
        Posting(p.participant_id, -p.amount_cents, p.role) for p in original.postings
    )


def test_an_entry_missing_from_this_book_cannot_be_reversed(
    conn, book, make_book, make_command
):
    other_book = make_book()
    append_entry(
        conn,
        book_id=other_book,
        command_id=make_command(book_id=other_book),
        build=fuel(30000),
    )

    with pytest.raises(EntryNotFoundError):
        append_reversal(
            conn,
            book_id=book,
            command_id=reversal_command(make_command),
            target_seq=1,
            author_id="luis",
        )


def test_the_same_reversal_command_twice_is_one_silent_reversal(
    conn, book, make_command
):
    record(conn, book, make_command)
    command_id = reversal_command(make_command)
    first = append_reversal(
        conn, book_id=book, command_id=command_id, target_seq=1, author_id="luis"
    )
    again = append_reversal(
        conn, book_id=book, command_id=command_id, target_seq=1, author_id="luis"
    )

    assert first.created and not again.created
    assert again.entry_id == first.entry_id
    assert len(book_entries(conn, book)) == 2


def test_a_new_request_to_reverse_the_same_entry_is_refused(conn, book, make_command):
    record(conn, book, make_command)
    append_reversal(
        conn,
        book_id=book,
        command_id=reversal_command(make_command),
        target_seq=1,
        author_id="luis",
    )

    with pytest.raises(AlreadyReversedError):
        append_reversal(
            conn,
            book_id=book,
            command_id=reversal_command(make_command),
            target_seq=1,
            author_id="seph",
        )
    assert len(book_entries(conn, book)) == 2
