"""Invariants of an expense, checked against generated trips."""

from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from ledger.expense import record_expense
from ledger.model import Role
from ledger.split import split_evenly

participant_ids = st.lists(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8),
    min_size=1,
    max_size=8,
    unique=True,
)


@st.composite
def expenses(draw):
    """A plausible expense: a group, one of them pays, any amount up to R$ 100k."""
    ids = draw(participant_ids)
    return record_expense(
        seq=draw(st.integers(min_value=1, max_value=10_000)),
        occurred_on=draw(
            st.dates(min_value=date(2026, 12, 25), max_value=date(2027, 1, 5))
        ),
        payer_id=draw(st.sampled_from(ids)),
        total_cents=draw(st.integers(min_value=1, max_value=10_000_000)),
        description="expense",
        participant_ids=ids,
    )


@given(expenses())
def test_postings_of_every_entry_sum_to_zero(entry):
    assert sum(p.amount_cents for p in entry.postings) == 0


@given(expenses())
def test_shares_sum_to_exactly_the_total(entry):
    (outlay,) = [p for p in entry.postings if p.role is Role.OUTLAY]
    shares = [p.amount_cents for p in entry.postings if p.role is Role.SHARE]

    assert -sum(shares) == outlay.amount_cents


@given(
    total_cents=st.integers(min_value=1, max_value=10_000_000),
    ids=participant_ids,
    seq=st.integers(min_value=1, max_value=10_000),
)
def test_no_one_pays_more_than_one_cent_above_anyone_else(total_cents, ids, seq):
    # Tested on the split, not the entry: zero shares have no posting.
    shares = [cents for _, cents in split_evenly(total_cents, ids, seq).shares]

    assert max(shares) - min(shares) <= 1
