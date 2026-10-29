import random
from datetime import date

import pytest

from ledger.positions import positions
from ledger.workflow import Action
from store.books import book_members
from store.confirmations import propose_expense, resolve
from store.ledger import book_postings


def test_members_are_this_books_only_sorted_by_id(conn, make_book):
    book_id = make_book(["vini", "lotti", "seph"])
    make_book(["luis"])

    assert book_members(conn, book_id) == ["lotti", "seph", "vini"]


def test_an_expense_is_split_among_the_members_not_every_participant(
    conn, make_book, spend
):
    book_id = make_book(["lotti", "luis", "seph"])

    spend("lotti", 30000, book_id=book_id)

    assert positions(book_postings(conn, book_id)) == {
        "lotti": 20000,
        "luis": -10000,
        "seph": -10000,
    }


def test_a_payer_who_is_not_a_member_is_refused(conn, make_book, make_command):
    book_id = make_book(["lotti", "luis"])

    with pytest.raises(ValueError):
        propose_expense(
            conn,
            book_id=book_id,
            command_id=make_command("vini", book_id=book_id),
            payer_id="vini",
            total_cents=10000,
            description="fuel",
            occurred_on=date(2026, 12, 26),
            rng=random.Random(0),
        )


def test_someone_joining_before_the_ok_is_not_in_that_expense(
    conn, make_book, make_command
):
    book_id = make_book(["lotti", "luis"])
    proposal = propose_expense(
        conn,
        book_id=book_id,
        command_id=make_command("lotti", book_id=book_id),
        payer_id="lotti",
        total_cents=10000,
        description="fuel",
        occurred_on=date(2026, 12, 26),
        rng=random.Random(0),
    )
    conn.execute(
        "INSERT INTO book_member (book_id, participant_id) VALUES (%s, 'seph')",
        (book_id,),
    )

    resolve(
        conn, book_id=book_id, code=proposal.code, action=Action.CONFIRM, actor="lotti"
    )

    assert positions(book_postings(conn, book_id)) == {"lotti": 5000, "luis": -5000}
