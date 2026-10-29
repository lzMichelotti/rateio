"""The settlement plan against generated positions built from zero-sum groups."""

from collections import Counter

from hypothesis import given, settings
from hypothesis import strategies as st
from oracle import minimum_transfers
from plan_strategies import zero_sum_positions

from ledger.settlement import settlement_postings
from ledger.settlement_plan import settlement_plan


@given(positions=zero_sum_positions())
def test_executing_the_plan_zeroes_every_position(positions):
    plan = settlement_plan(positions)

    # Executed as the !ok of each transfer would write it, legs and signs included.
    after = Counter(positions)
    for transfer in plan:
        for leg in settlement_postings(
            transfer.payer_id, transfer.payee_id, transfer.amount_cents
        ):
            after[leg.participant_id] += leg.amount_cents

    assert all(cents == 0 for cents in after.values())
    assert all(t.amount_cents > 0 and t.payer_id != t.payee_id for t in plan)


# 500 examples: with ~6% of cases tripping greedy, a wrong plan escapes with
# probability around 1e-14. No deadline: the oracle walks up to 4140 partitions.
@settings(max_examples=500, deadline=None)
@given(positions=zero_sum_positions())
def test_the_plan_uses_the_minimum_number_of_transfers(positions):
    assert len(settlement_plan(positions)) == minimum_transfers(positions)


@given(positions=zero_sum_positions(), data=st.data())
def test_the_same_positions_in_any_order_give_the_same_plan(positions, data):
    shuffled = data.draw(st.permutations(list(positions.items())))

    assert settlement_plan(dict(shuffled)) == settlement_plan(positions)
