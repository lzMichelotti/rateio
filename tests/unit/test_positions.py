from datetime import date

from ledger.expense import record_expense
from ledger.positions import positions

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]


def expense(seq: int, payer_id: str, total_cents: int):
    return record_expense(
        seq=seq,
        occurred_on=date(2026, 12, 26),
        payer_id=payer_id,
        total_cents=total_cents,
        description="fuel",
        participant_ids=FIVE,
    )


def test_one_expense():
    entry = expense(1, "lotti", 30000)

    assert positions(entry.postings) == {
        "lotti": 24000,
        "luis": -6000,
        "seph": -6000,
        "vini": -6000,
        "vitor": -6000,
    }


def test_two_expenses_accumulate():
    first = expense(1, "lotti", 30000)
    second = expense(2, "luis", 10000)

    assert positions(first.postings + second.postings) == {
        "lotti": 22000,
        "luis": 2000,
        "seph": -8000,
        "vini": -8000,
        "vitor": -8000,
    }


def test_no_postings_no_positions():
    assert positions([]) == {}
