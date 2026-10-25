from datetime import date

import pytest

from ledger.expense import record_expense
from ledger.model import EntryKind, Posting, Role

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]


def expense(total_cents: int, seq: int = 1, payer_id: str = "lotti"):
    return record_expense(
        seq=seq,
        occurred_on=date(2026, 12, 26),
        payer_id=payer_id,
        total_cents=total_cents,
        description="fuel",
        participant_ids=FIVE,
    )


def test_even_expense_has_one_outlay_and_a_share_each():
    entry = expense(30000)

    assert entry.kind is EntryKind.EXPENSE
    assert entry.author_id == "lotti"
    assert entry.postings == (
        Posting("lotti", 30000, Role.OUTLAY),
        Posting("lotti", -6000, Role.SHARE),
        Posting("luis", -6000, Role.SHARE),
        Posting("seph", -6000, Role.SHARE),
        Posting("vini", -6000, Role.SHARE),
        Posting("vitor", -6000, Role.SHARE),
    )


def test_remainder_offset_is_recorded_on_the_entry():
    entry = expense(18743, seq=2)

    shares = {
        p.participant_id: p.amount_cents for p in entry.postings if p.role is Role.SHARE
    }
    assert entry.remainder_offset == 2
    assert shares == {
        "lotti": -3748,
        "luis": -3748,
        "seph": -3749,
        "vini": -3749,
        "vitor": -3749,
    }


def test_a_share_that_rounds_to_zero_gets_no_posting():
    # 3 cents among 5: seq 1 -> offset 1 -> luis, seph, vini pay 1 cent; lotti and vitor pay 0.
    entry = expense(3, seq=1)

    assert entry.postings == (
        Posting("lotti", 3, Role.OUTLAY),
        Posting("luis", -1, Role.SHARE),
        Posting("seph", -1, Role.SHARE),
        Posting("vini", -1, Role.SHARE),
    )


def test_a_payer_outside_the_group_is_refused():
    with pytest.raises(ValueError):
        expense(30000, payer_id="stranger")
