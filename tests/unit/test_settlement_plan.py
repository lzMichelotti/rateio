import pytest

from ledger.settlement_plan import Transfer, UnbalancedPositionsError, settlement_plan


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
