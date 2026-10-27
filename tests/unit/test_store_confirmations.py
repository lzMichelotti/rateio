import random
import re
from datetime import date

import pytest

from ledger.breaks import OVERPAYMENT, Break
from ledger.expense import record_expense
from ledger.positions import positions
from ledger.settlement import ExceedsDebtError
from ledger.workflow import (
    Action,
    ConfirmationKind,
    ConfirmationStatus,
    NotAPartyError,
    NotTheConfirmerError,
)
from store.confirmations import (
    ALL_CODES,
    declare_settlement,
    pick_code,
    propose,
    resolve,
)
from store.ledger import append_entry, append_reversal, book_postings

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]
DECLARED_ON = date(2026, 12, 28)


@pytest.fixture
def seph_paid_dinner(conn, book, make_command):
    """seph paid 500 for the five: seph +400, everyone else -100."""
    return append_entry(
        conn,
        book_id=book,
        command_id=make_command("seph"),
        build=lambda seq: record_expense(
            seq=seq,
            occurred_on=date(2026, 12, 26),
            payer_id="seph",
            total_cents=50000,
            description="dinner",
            participant_ids=FIVE,
        ),
    )


def declare(conn, book, make_command, amount_cents=10000, seed=0):
    return declare_settlement(
        conn,
        book_id=book,
        command_id=make_command("luis", kind="declare_settlement"),
        payer_id="luis",
        payee_id="seph",
        amount_cents=amount_cents,
        declared_on=DECLARED_ON,
        rng=random.Random(seed),
    )


def settlement_row(conn, confirmation_id):
    return conn.execute(
        "SELECT status, entry_id FROM settlement WHERE confirmation_id = %s",
        (confirmation_id,),
    ).fetchone()


# -- codes -----------------------------------------------------------------------


def test_there_are_184_codes_and_all_match_the_database_rule():
    assert len(ALL_CODES) == 184 == len(set(ALL_CODES))
    assert all(re.fullmatch(r"[A-HJKMNP-Z][2-9]", code) for code in ALL_CODES)


def test_a_picked_code_is_never_open_or_recently_resolved(conn, book, make_command):
    taken = set()
    for _ in range(20):
        taken.add(
            propose(
                conn,
                book_id=book,
                command_id=make_command(),
                kind=ConfirmationKind.EXPENSE_PROPOSAL,
                created_by="lotti",
                confirmer="lotti",
                payload={},
                rng=random.Random(len(taken)),
            ).code
        )
    resolve(
        conn, book_id=book, code=next(iter(taken)), action=Action.DECLINE, actor="lotti"
    )

    rng = random.Random(1)
    assert all(pick_code(conn, book, rng) not in taken for _ in range(200))


def test_proposing_the_same_command_twice_opens_one_confirmation(
    conn, book, make_command
):
    command_id = make_command()
    proposals = [
        propose(
            conn,
            book_id=book,
            command_id=command_id,
            kind=ConfirmationKind.EXPENSE_PROPOSAL,
            created_by="lotti",
            confirmer="lotti",
            payload={},
            rng=random.Random(seed),
        )
        for seed in (1, 2)
    ]

    assert proposals[0].created and not proposals[1].created
    assert proposals[0].code == proposals[1].code


# -- settlement ------------------------------------------------------------------


def test_declaring_changes_no_position(conn, book, make_command, seph_paid_dinner):
    before = positions(book_postings(conn, book))
    proposal = declare(conn, book, make_command)

    assert positions(book_postings(conn, book)) == before
    assert settlement_row(conn, proposal.confirmation_id) == ("declared", None)


def test_the_payee_confirms_and_only_then_the_entry_exists(
    conn, book, make_command, seph_paid_dinner
):
    proposal = declare(conn, book, make_command)
    resolution = resolve(
        conn, book_id=book, code=proposal.code, action=Action.CONFIRM, actor="seph"
    )

    assert resolution.status is ConfirmationStatus.CONFIRMED
    assert resolution.breaks == ()
    net = positions(book_postings(conn, book))
    assert (net["luis"], net["seph"]) == (0, 30000)
    assert settlement_row(conn, proposal.confirmation_id) == (
        "confirmed",
        resolution.entry.entry_id,
    )
    occurred_on, command_id = conn.execute(
        "SELECT occurred_on, command_id FROM journal_entry WHERE id = %s",
        (resolution.entry.entry_id,),
    ).fetchone()
    assert occurred_on == DECLARED_ON
    proposing = conn.execute(
        "SELECT command_id FROM confirmation WHERE id = %s",
        (proposal.confirmation_id,),
    ).fetchone()[0]
    assert command_id == proposing


def test_confirming_twice_creates_one_entry(conn, book, make_command, seph_paid_dinner):
    proposal = declare(conn, book, make_command)
    first = resolve(
        conn, book_id=book, code=proposal.code, action=Action.CONFIRM, actor="seph"
    )
    again = resolve(
        conn, book_id=book, code=proposal.code, action=Action.CONFIRM, actor="seph"
    )

    assert first.changed and not again.changed
    (settlements,) = conn.execute(
        "SELECT count(*) FROM journal_entry WHERE book_id = %s AND kind = 'settlement'",
        (book,),
    ).fetchone()
    assert settlements == 1


@pytest.mark.parametrize("actor", ["luis", "vini"])
def test_only_the_payee_can_confirm(conn, book, make_command, seph_paid_dinner, actor):
    proposal = declare(conn, book, make_command)

    with pytest.raises(NotTheConfirmerError):
        resolve(
            conn, book_id=book, code=proposal.code, action=Action.CONFIRM, actor=actor
        )
    assert settlement_row(conn, proposal.confirmation_id) == ("declared", None)


@pytest.mark.parametrize(
    ("actor", "settlement_status"), [("seph", "rejected"), ("luis", "cancelled")]
)
def test_decline_from_the_payee_rejects_and_from_the_payer_cancels(
    conn, book, make_command, seph_paid_dinner, actor, settlement_status
):
    before = positions(book_postings(conn, book))
    proposal = declare(conn, book, make_command)
    resolution = resolve(
        conn, book_id=book, code=proposal.code, action=Action.DECLINE, actor=actor
    )

    assert resolution.status is ConfirmationStatus.DISCARDED
    assert settlement_row(conn, proposal.confirmation_id) == (settlement_status, None)
    assert positions(book_postings(conn, book)) == before


def test_decline_from_a_third_person_is_refused(
    conn, book, make_command, seph_paid_dinner
):
    proposal = declare(conn, book, make_command)

    with pytest.raises(NotAPartyError):
        resolve(
            conn, book_id=book, code=proposal.code, action=Action.DECLINE, actor="vini"
        )


def test_declaring_above_the_debt_is_refused_and_writes_nothing(
    conn, book, make_command, seph_paid_dinner
):
    with pytest.raises(ExceedsDebtError):
        declare(conn, book, make_command, amount_cents=10001)

    (count,) = conn.execute("SELECT count(*) FROM settlement").fetchone()
    assert count == 0


def test_confirming_after_positions_moved_records_and_reports_break_7(
    conn, book, make_command, seph_paid_dinner
):
    proposal = declare(conn, book, make_command)
    # The dinner is reversed before seph confirms: luis no longer owes anything.
    append_reversal(
        conn,
        book_id=book,
        command_id=make_command(kind="reverse"),
        target_seq=1,
        author_id="lotti",
    )
    resolution = resolve(
        conn, book_id=book, code=proposal.code, action=Action.CONFIRM, actor="seph"
    )

    assert resolution.entry is not None
    assert resolution.breaks == (
        Break(OVERPAYMENT, "luis", 10000),
        Break(OVERPAYMENT, "seph", -10000),
    )


def test_a_code_taken_meanwhile_is_retried_with_another(
    conn, book, make_command, monkeypatch
):
    first = propose(
        conn,
        book_id=book,
        command_id=make_command(),
        kind=ConfirmationKind.EXPENSE_PROPOSAL,
        created_by="lotti",
        confirmer="lotti",
        payload={},
        rng=random.Random(0),
    )
    # Simulate a race: the first draw returns a code another proposal holds.
    draws = iter([first.code, "Z9" if first.code != "Z9" else "Y9"])
    monkeypatch.setattr(
        "store.confirmations.pick_code", lambda conn, book_id, rng: next(draws)
    )

    second = propose(
        conn,
        book_id=book,
        command_id=make_command(),
        kind=ConfirmationKind.EXPENSE_PROPOSAL,
        created_by="lotti",
        confirmer="lotti",
        payload={},
        rng=random.Random(0),
    )

    assert second.created
    assert second.code != first.code
