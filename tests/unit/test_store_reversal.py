import random
from datetime import date

import pytest

from ledger.expense import record_expense
from ledger.model import EntryKind, Posting
from ledger.reversal import AlreadyReversedError
from ledger.workflow import Action
from store.confirmations import propose_reversal, resolve
from store.ledger import EntryNotFoundError, book_entries

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]


def propose(conn, book, make_command, target_seq=1, author_id="luis", command_id=None):
    return propose_reversal(
        conn,
        book_id=book,
        command_id=command_id or make_command(author_id, kind="reverse"),
        target_seq=target_seq,
        author_id=author_id,
        rng=random.Random(0),
    )


def confirm(conn, book, proposal, actor="luis"):
    return resolve(
        conn, book_id=book, code=proposal.code, action=Action.CONFIRM, actor=actor
    )


def test_reversal_is_linked_to_the_original_and_keeps_its_date(conn, book, spend, undo):
    original = spend("lotti", 30000)
    reversal = undo(1)

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


def test_book_entries_reads_back_what_the_domain_built(conn, book, spend, undo):
    spend("lotti", 30000)
    undo(1)

    original, reversal = book_entries(conn, book)
    assert original == record_expense(
        seq=1,
        occurred_on=date(2026, 12, 26),
        payer_id="lotti",
        total_cents=30000,
        description="fuel",
        participant_ids=FIVE,
    )
    assert reversal.kind is EntryKind.REVERSAL
    assert reversal.reverses_seq == 1
    assert reversal.postings == tuple(
        Posting(p.participant_id, -p.amount_cents, p.role) for p in original.postings
    )


def test_an_entry_missing_from_this_book_cannot_be_reversed(
    conn, book, make_book, make_command, spend
):
    spend("lotti", 30000, book_id=make_book())

    with pytest.raises(EntryNotFoundError):
        propose(conn, book, make_command)


def test_the_same_reversal_command_twice_is_one_silent_reversal(
    conn, book, make_command, spend
):
    spend("lotti", 30000)
    command_id = make_command("luis", kind="reverse")
    first = confirm(
        conn, book, propose(conn, book, make_command, command_id=command_id)
    )
    again = confirm(
        conn, book, propose(conn, book, make_command, command_id=command_id)
    )

    assert first.changed and not again.changed
    assert len(book_entries(conn, book)) == 2


def test_a_new_request_to_reverse_the_same_entry_is_refused_at_proposal(
    conn, book, make_command, spend, undo
):
    spend("lotti", 30000)
    undo(1)

    with pytest.raises(AlreadyReversedError):
        propose(conn, book, make_command, author_id="seph")
    assert len(book_entries(conn, book)) == 2


def test_two_open_reversals_of_one_entry_only_the_first_ok_wins(
    conn, book, make_command, spend
):
    # Both proposals are valid when made; the second !ok finds L1 already reversed.
    spend("lotti", 30000)
    by_luis = propose(conn, book, make_command, author_id="luis")
    by_seph = propose(conn, book, make_command, author_id="seph")
    confirm(conn, book, by_luis, actor="luis")

    with pytest.raises(AlreadyReversedError):
        confirm(conn, book, by_seph, actor="seph")
    assert len(book_entries(conn, book)) == 2
