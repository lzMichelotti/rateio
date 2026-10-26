from datetime import date

import pytest

from ledger.expense import record_expense
from ledger.model import Entry, EntryKind, Posting, Role
from ledger.positions import positions
from ledger.reversal import AlreadyReversedError, ReversalOfReversalError, reverse

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]

ORIGINAL = record_expense(
    seq=1,
    occurred_on=date(2026, 12, 26),
    payer_id="lotti",
    total_cents=30000,
    description="fuel",
    participant_ids=FIVE,
)
REVERSAL = reverse(ORIGINAL, seq=2, author_id="luis", book_entries=[ORIGINAL])


def test_reversal_mirrors_every_posting_with_the_same_role():
    assert REVERSAL.postings == (
        Posting("lotti", -30000, Role.OUTLAY),
        Posting("lotti", 6000, Role.SHARE),
        Posting("luis", 6000, Role.SHARE),
        Posting("seph", 6000, Role.SHARE),
        Posting("vini", 6000, Role.SHARE),
        Posting("vitor", 6000, Role.SHARE),
    )


def test_reversal_points_at_the_original_and_is_authored_by_whoever_asked():
    assert REVERSAL.kind is EntryKind.REVERSAL
    assert REVERSAL.reverses_seq == 1
    assert REVERSAL.seq == 2
    assert REVERSAL.author_id == "luis"


def test_reversal_inherits_the_original_business_date():
    assert REVERSAL.occurred_on == date(2026, 12, 26)


def test_original_plus_reversal_is_zero_for_everyone():
    net = positions(ORIGINAL.postings + REVERSAL.postings)

    assert set(net) == set(FIVE)
    assert set(net.values()) == {0}


def test_outlays_net_out_across_original_and_reversal():
    outlays = [
        p.amount_cents
        for p in ORIGINAL.postings + REVERSAL.postings
        if p.role is Role.OUTLAY
    ]

    assert sum(outlays) == 0


def test_an_entry_already_reversed_cannot_be_reversed_again():
    with pytest.raises(AlreadyReversedError) as refused:
        reverse(ORIGINAL, seq=3, author_id="seph", book_entries=[ORIGINAL, REVERSAL])

    assert (refused.value.original_seq, refused.value.reversal_seq) == (1, 2)
    assert "already reversed by L2" in str(refused.value)


def test_a_reversal_cannot_be_reversed():
    with pytest.raises(ReversalOfReversalError) as refused:
        reverse(REVERSAL, seq=3, author_id="seph", book_entries=[ORIGINAL, REVERSAL])

    assert (refused.value.seq, refused.value.reverses_seq) == (2, 1)
    assert "record it again as a new expense" in str(refused.value)


def test_a_reversal_without_a_link_cannot_exist():
    with pytest.raises(ValueError):
        Entry(
            seq=2,
            kind=EntryKind.REVERSAL,
            occurred_on=date(2026, 12, 26),
            author_id="luis",
            description="fuel",
            postings=REVERSAL.postings,
        )
