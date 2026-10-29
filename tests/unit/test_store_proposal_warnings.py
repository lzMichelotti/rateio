"""Breaks 1 and 4 through the store: the proposal is always made, with a code,
and the warning travels with it. The book runs 2026-12-25 to 2027-01-05."""

import random
from datetime import UTC, date, datetime, timedelta

from ledger.breaks import IntentDuplicate, OutsideBookDates
from ledger.workflow import Action
from store.confirmations import propose_expense, resolve

SENT = datetime(2026, 12, 28, 21, 0, tzinfo=UTC)


def propose(conn, book, make_command, *, at=SENT, occurred_on=date(2026, 12, 28)):
    return propose_expense(
        conn,
        book_id=book,
        command_id=make_command("seph"),
        payer_id="seph",
        total_cents=41200,
        description="jantar",
        occurred_on=occurred_on,
        at=at,
        rng=random.Random(at.minute),
    )


def test_the_same_dinner_two_minutes_later_is_proposed_with_a_warning(
    conn, book, make_command
):
    first = propose(conn, book, make_command)
    resolve(conn, book_id=book, code=first.code, action=Action.CONFIRM, actor="seph")

    again = propose(conn, book, make_command, at=SENT + timedelta(minutes=2))

    assert again.created and again.code != first.code
    assert again.warnings == (IntentDuplicate(first.code, SENT),)


def test_eleven_minutes_later_there_is_no_warning(conn, book, make_command):
    propose(conn, book, make_command)

    later = propose(conn, book, make_command, at=SENT + timedelta(minutes=11))

    assert later.warnings == ()


def test_a_discarded_proposal_is_not_a_duplicate(conn, book, make_command):
    first = propose(conn, book, make_command)
    resolve(conn, book_id=book, code=first.code, action=Action.DECLINE, actor="seph")

    again = propose(conn, book, make_command, at=SENT + timedelta(minutes=2))

    assert again.warnings == ()


def test_a_date_outside_the_trip_is_proposed_with_a_warning(conn, book, make_command):
    proposal = propose(conn, book, make_command, occurred_on=date(2026, 11, 2))

    assert proposal.created
    assert proposal.warnings == (
        OutsideBookDates(date(2026, 11, 2), date(2026, 12, 25), date(2027, 1, 5)),
    )


def test_the_send_time_is_the_proposals_created_at(conn, book, make_command):
    proposal = propose(conn, book, make_command)

    assert conn.execute(
        "SELECT created_at FROM confirmation WHERE id = %s",
        (proposal.confirmation_id,),
    ).fetchone() == (SENT,)
