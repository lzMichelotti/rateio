from datetime import date

import pytest

from ledger.settlement import DeclaredSettlement
from ledger.settlement_plan import (
    Transfer,
    UnbalancedPositionsError,
    book_settled,
    settlement_plan,
)

LUIS_PAYS_LOTTI = DeclaredSettlement("A7", "luis", "lotti", 6000, date(2026, 12, 27))


def test_everyone_at_zero_needs_no_transfer():
    assert settlement_plan({"lotti": 0, "luis": 0}) == ()
    assert settlement_plan({}) == ()


def test_one_debtor_pays_one_creditor():
    assert settlement_plan({"lotti": 6000, "luis": -6000}) == (
        Transfer("luis", "lotti", 6000),
    )


def test_a_pair_that_closes_on_its_own_saves_a_transfer():
    # Greedy would match +4 with -5 first and spend four transfers.
    plan = settlement_plan({"lotti": 4, "luis": 3, "seph": 2, "vini": -5, "vitor": -4})

    assert len(plan) == 3
    assert Transfer("vitor", "lotti", 4) in plan


def test_the_order_positions_arrive_in_does_not_change_the_plan():
    positions = {"lotti": 4, "luis": 3, "seph": 2, "vini": -5, "vitor": -4}

    assert settlement_plan(dict(reversed(positions.items()))) == settlement_plan(
        positions
    )


def test_positions_that_do_not_sum_to_zero_are_refused():
    with pytest.raises(UnbalancedPositionsError):
        settlement_plan({"lotti": 100, "luis": -99})


def test_a_pair_closing_on_its_own_and_one_debtor_paying_two():
    plan = settlement_plan(
        {"lotti": 400, "luis": 300, "seph": 200, "vini": -500, "vitor": -400}
    )

    assert plan == (
        Transfer("vini", "luis", 300),
        Transfer("vini", "seph", 200),
        Transfer("vitor", "lotti", 400),
    )


CRUMBS = {
    "lotti": 67208,
    "luis": 31545,
    "seph": -19912,
    "vini": -31792,
    "vitor": -47049,
}
# What largest-creditor-against-largest-debtor produces for CRUMBS, checked by
# hand: as short as the best plan, but with a R$ 2,47 transfer.
GREEDY_FOR_CRUMBS = (
    Transfer("seph", "lotti", 19912),
    Transfer("vini", "lotti", 247),
    Transfer("vini", "luis", 31545),
    Transfer("vitor", "lotti", 47049),
)


def zeroes(positions, plan):
    after = dict(positions)
    for t in plan:
        after[t.payer_id] += t.amount_cents
        after[t.payee_id] -= t.amount_cents
    return all(cents == 0 for cents in after.values())


def test_among_equally_short_plans_the_largest_smallest_transfer_wins():
    plan = settlement_plan(CRUMBS)

    assert plan == (
        Transfer("seph", "lotti", 19912),
        Transfer("vini", "lotti", 31792),
        Transfer("vitor", "lotti", 15504),
        Transfer("vitor", "luis", 31545),
    )
    assert min(t.amount_cents for t in plan) == 15504

    # Greedy's plan is valid and just as short: criterion 2 is what chose.
    assert zeroes(CRUMBS, GREEDY_FOR_CRUMBS)
    assert len(GREEDY_FOR_CRUMBS) == len(plan)
    assert min(t.amount_cents for t in GREEDY_FOR_CRUMBS) == 247


def test_everyone_at_zero_has_an_empty_plan_and_a_settled_book():
    positions = dict.fromkeys(["lotti", "luis", "seph", "vini", "vitor"], 0)

    assert settlement_plan(positions) == ()
    assert book_settled(positions, [])


def test_all_positions_at_zero_and_nothing_declared_is_settled():
    assert book_settled({"lotti": 0, "luis": 0}, [])


def test_a_non_zero_position_is_not_settled():
    assert not book_settled({"lotti": 6000, "luis": -6000}, [])


def test_a_declared_settlement_keeps_the_book_open_even_at_zero():
    # luis declared the whole debt, then the expense was reversed.
    assert not book_settled({"lotti": 0, "luis": 0}, [LUIS_PAYS_LOTTI])


def test_a_book_with_no_entries_is_settled():
    assert book_settled({}, [])
