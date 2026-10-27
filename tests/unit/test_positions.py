from datetime import date

from ledger.expense import record_expense
from ledger.positions import ParticipantSummary, position_summary, positions
from ledger.reversal import reverse
from ledger.settlement import record_settlement

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


def test_summary_of_one_expense_splits_outlay_from_share():
    summary = position_summary(expense(1, "lotti", 30000).postings)

    assert summary.participants == (
        ParticipantSummary("lotti", 30000, -6000, 0, 0),
        ParticipantSummary("luis", 0, -6000, 0, 0),
        ParticipantSummary("seph", 0, -6000, 0, 0),
        ParticipantSummary("vini", 0, -6000, 0, 0),
        ParticipantSummary("vitor", 0, -6000, 0, 0),
    )
    assert [p.position_cents for p in summary.participants] == [
        24000,
        -6000,
        -6000,
        -6000,
        -6000,
    ]
    assert summary.total_spent_cents == 30000


def test_a_reversal_zeroes_every_role_total_with_no_special_case():
    original = expense(1, "lotti", 30000)
    reversal = reverse(original, seq=2, author_id="luis", book_entries=[original])

    summary = position_summary(original.postings + reversal.postings)

    assert all(
        p == ParticipantSummary(p.participant_id, 0, 0, 0, 0)
        for p in summary.participants
    )
    assert summary.total_spent_cents == 0


def test_a_settlement_moves_positions_but_not_the_total_spent():
    spent = expense(1, "lotti", 30000)
    paid = record_settlement(
        seq=2,
        declared_on=date(2026, 12, 27),
        payer_id="luis",
        payee_id="lotti",
        amount_cents=6000,
    )

    summary = position_summary(spent.postings + paid.postings)
    by_id = {p.participant_id: p for p in summary.participants}

    assert by_id["lotti"] == ParticipantSummary("lotti", 30000, -6000, 0, -6000)
    assert by_id["luis"] == ParticipantSummary("luis", 0, -6000, 6000, 0)
    assert by_id["luis"].position_cents == 0
    assert summary.total_spent_cents == 30000


def test_total_spent_is_the_sum_of_outlays_and_minus_the_sum_of_shares():
    summary = position_summary(
        expense(1, "lotti", 30000).postings + expense(2, "seph", 18743).postings
    )

    assert summary.total_spent_cents == 48743
    assert summary.total_spent_cents == -sum(
        p.share_cents for p in summary.participants
    )


def test_summary_positions_match_positions():
    postings = expense(1, "lotti", 30000).postings + expense(2, "luis", 10000).postings

    summary = position_summary(postings)

    assert {p.participant_id: p.position_cents for p in summary.participants} == (
        positions(postings)
    )


def test_no_postings_empty_summary():
    summary = position_summary([])

    assert summary.participants == ()
    assert summary.total_spent_cents == 0
