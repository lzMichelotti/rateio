"""Role totals add up to positions, across trips of expenses, reversals and
payments, built in the domain alone."""

from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from ledger.expense import record_expense
from ledger.model import Entry, EntryKind, Role
from ledger.positions import position_summary, positions
from ledger.reversal import reverse
from ledger.settlement import record_settlement

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]
DAY = date(2026, 12, 26)

spend_step = st.tuples(
    st.just("spend"),
    st.sampled_from(FIVE),
    st.integers(min_value=1, max_value=1_000_000),
)
# Which still-reversible entry to reverse, as an index into the candidates.
undo_step = st.tuples(st.just("reverse"), st.integers(min_value=0, max_value=1_000))
# Any positive amount between two different people: record_settlement does not
# check debts, so overpayments that flip signs are generated too.
pay_step = st.tuples(
    st.just("pay"),
    st.sampled_from(FIVE),
    st.integers(min_value=1, max_value=len(FIVE) - 1),
    st.integers(min_value=1, max_value=1_000_000),
)
trips = st.lists(st.one_of(spend_step, undo_step, pay_step), max_size=20)


def build(trip) -> list[Entry]:
    entries: list[Entry] = []
    reversible: list[Entry] = []
    for step in trip:
        seq = len(entries) + 1
        if step[0] == "spend":
            _, payer_id, total_cents = step
            entry = record_expense(
                seq=seq,
                occurred_on=DAY,
                payer_id=payer_id,
                total_cents=total_cents,
                description="expense",
                participant_ids=FIVE,
            )
        elif step[0] == "pay":
            _, payer_id, offset, amount_cents = step
            payee_id = FIVE[(FIVE.index(payer_id) + offset) % len(FIVE)]
            entry = record_settlement(
                seq=seq,
                declared_on=DAY,
                payer_id=payer_id,
                payee_id=payee_id,
                amount_cents=amount_cents,
            )
        elif reversible:
            original = reversible.pop(step[1] % len(reversible))
            entry = reverse(original, seq=seq, author_id="luis", book_entries=entries)
        else:
            continue
        entries.append(entry)
        if entry.kind is not EntryKind.REVERSAL:
            reversible.append(entry)
    return entries


@given(trip=trips)
def test_role_totals_add_up_to_each_position_and_outlays_to_minus_shares(trip):
    postings = [p for entry in build(trip) for p in entry.postings]

    summary = position_summary(postings)

    # Against positions(), not the summary's own sum: two paths over the legs.
    assert {
        p.participant_id: p.position_cents for p in summary.participants
    } == positions(postings)
    assert summary.total_spent_cents == sum(
        p.amount_cents for p in postings if p.role is Role.OUTLAY
    )
    assert summary.total_spent_cents == -sum(
        p.share_cents for p in summary.participants
    )
