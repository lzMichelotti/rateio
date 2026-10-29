"""The settlement plan read from the database: confirmed positions, declared
settlements, projection, plan. Nothing here is stored; every plan is recomputed."""

import random
from datetime import date

import pytest

from ledger.positions import positions, projected_positions
from ledger.settlement_plan import Transfer, book_settled, settlement_plan
from ledger.workflow import Action
from store.confirmations import declare_settlement, declared_settlements, resolve
from store.ledger import book_postings

DECLARED_ON = date(2026, 12, 28)
DEBTORS = ["lotti", "luis", "vini", "vitor"]


@pytest.fixture
def seph_paid_dinner(spend):
    """seph paid 500 for the five: seph +400, everyone else -100."""
    return spend("seph", 50000, description="dinner")


def acerto(conn, book):
    """What !acerto reads: confirmed positions, the plan on projected ones, the
    pending declarations, and whether the book is settled."""
    confirmed = positions(book_postings(conn, book))
    declared = declared_settlements(conn, book)
    plan = settlement_plan(projected_positions(book_postings(conn, book), declared))
    return confirmed, plan, declared, book_settled(confirmed, declared)


def pay_seph(conn, book, make_command, payer_id, seed=0):
    return declare_settlement(
        conn,
        book_id=book,
        command_id=make_command(payer_id, kind="declare_settlement"),
        payer_id=payer_id,
        payee_id="seph",
        amount_cents=10000,
        declared_on=DECLARED_ON,
        rng=random.Random(seed),
    )


def test_a_declared_settlement_shrinks_the_plan_and_keeps_the_book_open(
    conn, book, make_command, seph_paid_dinner
):
    confirmed_before, plan_before, _, _ = acerto(conn, book)
    assert plan_before == tuple(Transfer(p, "seph", 10000) for p in DEBTORS)

    pay_seph(conn, book, make_command, "luis")
    confirmed, plan, declared, settled = acerto(conn, book)

    assert confirmed == confirmed_before
    assert plan == tuple(Transfer(p, "seph", 10000) for p in DEBTORS if p != "luis")
    assert [(d.payer_id, d.payee_id, d.amount_cents) for d in declared] == [
        ("luis", "seph", 10000)
    ]
    assert not settled


def test_a_rejected_declaration_brings_its_transfer_back_to_the_plan(
    conn, book, make_command, seph_paid_dinner
):
    _, plan_before, _, _ = acerto(conn, book)
    proposal = pay_seph(conn, book, make_command, "luis")

    resolve(conn, book_id=book, code=proposal.code, action=Action.DECLINE, actor="seph")
    _, plan, declared, settled = acerto(conn, book)

    assert plan == plan_before
    assert declared == []
    assert not settled


def test_once_every_payment_is_confirmed_the_plan_is_empty_and_the_book_settled(
    conn, book, make_command, seph_paid_dinner
):
    for seed, payer_id in enumerate(DEBTORS):
        proposal = pay_seph(conn, book, make_command, payer_id, seed=seed)
        resolve(
            conn, book_id=book, code=proposal.code, action=Action.CONFIRM, actor="seph"
        )

    confirmed, plan, declared, settled = acerto(conn, book)

    assert all(cents == 0 for cents in confirmed.values())
    assert plan == ()
    assert declared == []
    assert settled
