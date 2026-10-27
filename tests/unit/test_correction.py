"""The full correction flow, end to end through the store: record a wrong amount,
reverse it, record the right one."""

from datetime import date

import pytest

from ledger.expense import record_expense
from ledger.model import EntryKind
from ledger.positions import positions
from ledger.reversal import ReversalOfReversalError
from ledger.statement import statement
from store.ledger import append_entry, append_reversal, book_entries, book_postings

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


def correct_300_to_30(conn, book, make_command):
    append_entry(conn, book_id=book, command_id=make_command(), build=fuel(30000))
    append_reversal(
        conn,
        book_id=book,
        command_id=make_command("luis", kind="reverse"),
        target_seq=1,
        author_id="luis",
    )
    append_entry(conn, book_id=book, command_id=make_command(), build=fuel(3000))


def test_after_the_correction_positions_are_those_of_the_right_amount(
    conn, book, make_command
):
    correct_300_to_30(conn, book, make_command)

    net = positions(book_postings(conn, book))
    assert {k: v for k, v in net.items() if v} == {
        "lotti": 2400,
        "luis": -600,
        "seph": -600,
        "vini": -600,
        "vitor": -600,
    }


def test_the_statement_shows_all_three_lines_marked_on_both_sides(
    conn, book, make_command
):
    correct_300_to_30(conn, book, make_command)

    lines = statement(book_entries(conn, book))
    assert [
        (line.seq, line.kind, line.total_cents, line.reversed_by, line.reverses)
        for line in lines
    ] == [
        (1, EntryKind.EXPENSE, 30000, 2, None),
        (2, EntryKind.REVERSAL, -30000, None, 1),
        (3, EntryKind.EXPENSE, 3000, None, None),
    ]


def test_reversing_a_reversal_is_refused_through_the_store(conn, book, make_command):
    correct_300_to_30(conn, book, make_command)

    with pytest.raises(ReversalOfReversalError):
        append_reversal(
            conn,
            book_id=book,
            command_id=make_command("seph", kind="reverse"),
            target_seq=2,
            author_id="seph",
        )
    assert len(book_entries(conn, book)) == 3
