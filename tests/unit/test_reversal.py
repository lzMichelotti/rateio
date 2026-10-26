from datetime import date

from ledger.expense import record_expense
from ledger.model import EntryKind, Posting, Role
from ledger.positions import positions
from ledger.reversal import reverse

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]

ORIGINAL = record_expense(
    seq=1,
    occurred_on=date(2026, 12, 26),
    payer_id="lotti",
    total_cents=30000,
    description="fuel",
    participant_ids=FIVE,
)


def test_reversal_mirrors_every_posting_with_the_same_role():
    reversal = reverse(ORIGINAL, seq=2, author_id="luis")

    assert reversal.postings == (
        Posting("lotti", -30000, Role.OUTLAY),
        Posting("lotti", 6000, Role.SHARE),
        Posting("luis", 6000, Role.SHARE),
        Posting("seph", 6000, Role.SHARE),
        Posting("vini", 6000, Role.SHARE),
        Posting("vitor", 6000, Role.SHARE),
    )


def test_reversal_points_at_the_original_and_is_authored_by_whoever_asked():
    reversal = reverse(ORIGINAL, seq=2, author_id="luis")

    assert reversal.kind is EntryKind.REVERSAL
    assert reversal.reverses_seq == 1
    assert reversal.seq == 2
    assert reversal.author_id == "luis"


def test_reversal_inherits_the_original_business_date():
    reversal = reverse(ORIGINAL, seq=2, author_id="luis")

    assert reversal.occurred_on == date(2026, 12, 26)


def test_original_plus_reversal_is_zero_for_everyone():
    reversal = reverse(ORIGINAL, seq=2, author_id="luis")

    net = positions(ORIGINAL.postings + reversal.postings)
    assert set(net) == set(FIVE)
    assert set(net.values()) == {0}


def test_outlays_net_out_across_original_and_reversal():
    reversal = reverse(ORIGINAL, seq=2, author_id="luis")

    outlays = [
        p.amount_cents
        for p in ORIGINAL.postings + reversal.postings
        if p.role is Role.OUTLAY
    ]
    assert sum(outlays) == 0
