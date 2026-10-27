"""The full correction flow, end to end through the store: record a wrong amount,
reverse it, record the right one."""

import random

import pytest

from ledger.model import EntryKind
from ledger.positions import positions
from ledger.reversal import ReversalOfReversalError
from ledger.statement import statement
from store.confirmations import propose_reversal
from store.ledger import book_entries, book_postings


@pytest.fixture
def corrected_300_to_30(spend, undo):
    spend("lotti", 30000)
    undo(1)
    spend("lotti", 3000)


def test_after_the_correction_positions_are_those_of_the_right_amount(
    conn, book, corrected_300_to_30
):
    net = positions(book_postings(conn, book))
    assert {k: v for k, v in net.items() if v} == {
        "lotti": 2400,
        "luis": -600,
        "seph": -600,
        "vini": -600,
        "vitor": -600,
    }


def test_the_statement_shows_all_three_lines_marked_on_both_sides(
    conn, book, corrected_300_to_30
):
    lines = statement(book_entries(conn, book))
    assert [
        (line.seq, line.kind, line.total_cents, line.reversed_by, line.reverses)
        for line in lines
    ] == [
        (1, EntryKind.EXPENSE, 30000, 2, None),
        (2, EntryKind.REVERSAL, -30000, None, 1),
        (3, EntryKind.EXPENSE, 3000, None, None),
    ]


def test_reversing_a_reversal_is_refused_through_the_store(
    conn, book, make_command, corrected_300_to_30
):
    with pytest.raises(ReversalOfReversalError):
        propose_reversal(
            conn,
            book_id=book,
            command_id=make_command("seph", kind="reverse"),
            target_seq=2,
            author_id="seph",
            rng=random.Random(0),
        )
    assert len(book_entries(conn, book)) == 3
