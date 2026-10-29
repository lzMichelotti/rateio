from datetime import date

from ledger.expense import record_expense
from ledger.model import EntryKind
from ledger.reversal import reverse
from ledger.settlement import record_settlement
from ledger.statement import StatementLine, StatementTransfer, statement

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]
DAY = date(2026, 12, 26)


def fuel(seq: int, total_cents: int):
    return record_expense(
        seq=seq,
        occurred_on=DAY,
        payer_id="lotti",
        total_cents=total_cents,
        description="fuel",
        participant_ids=FIVE,
    )


WRONG = fuel(1, 30000)
REVERSAL = reverse(WRONG, seq=2, author_id="luis", book_entries=[WRONG])
RIGHT = fuel(3, 3000)


def test_a_correction_shows_three_lines_marked_on_both_sides():
    assert statement([WRONG, REVERSAL, RIGHT]) == [
        StatementLine(1, EntryKind.EXPENSE, DAY, "fuel", 30000, ("lotti",), 2, None),
        StatementLine(2, EntryKind.REVERSAL, DAY, "fuel", -30000, ("lotti",), None, 1),
        StatementLine(3, EntryKind.EXPENSE, DAY, "fuel", 3000, ("lotti",), None, None),
    ]


def test_summing_the_totals_gives_what_was_really_spent():
    assert sum(line.total_cents for line in statement([WRONG, REVERSAL, RIGHT])) == 3000


def test_lines_follow_seq_whatever_order_the_entries_arrive_in():
    lines = statement([RIGHT, WRONG, REVERSAL])

    assert [line.seq for line in lines] == [1, 2, 3]


def test_an_empty_book_has_an_empty_statement():
    assert statement([]) == []


def test_a_settlement_line_shows_the_transfer_and_spends_nothing():
    paid = record_settlement(
        seq=4, declared_on=DAY, payer_id="vini", payee_id="lotti", amount_cents=4000
    )
    undone = reverse(paid, seq=5, author_id="lotti", book_entries=[paid])

    settlement, reversal = statement([paid, undone])

    assert settlement.transfer == StatementTransfer("vini", "lotti", 4000)
    assert (settlement.total_cents, settlement.paid_by) == (0, ())
    assert reversal.transfer == StatementTransfer("vini", "lotti", -4000)


def test_an_expense_line_has_no_transfer():
    assert statement([WRONG])[0].transfer is None
