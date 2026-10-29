"""The book's statement: every entry, in order, with reversals marked on both sides.

Structured data only. Turning a line into text for the group is the channel's job.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from ledger.model import Entry, EntryKind, Role


@dataclass(frozen=True)
class StatementTransfer:
    """The payment on a settlement line: who paid whom, and how much. Signed
    like total_cents, so the reversal of a payment shows a negative amount."""

    payer_id: str
    payee_id: str
    amount_cents: int


@dataclass(frozen=True)
class StatementLine:
    seq: int
    kind: EntryKind
    occurred_on: date
    description: str
    total_cents: int  # signed: the reversal of a 30000 expense shows -30000
    paid_by: tuple[str, ...]  # participants with an outlay leg, sorted
    reversed_by: int | None  # on an original: the seq of the entry reversing it
    reverses: int | None  # on a reversal: the seq of the entry it reverses
    # On a settlement, or its reversal: a payment is not spending, so its
    # total_cents is 0 and paid_by is empty; the transfer is shown here instead.
    transfer: StatementTransfer | None = None


def statement(entries: Iterable[Entry]) -> list[StatementLine]:
    """One line per entry, ordered by seq. Nothing is hidden: reversed entries stay,
    next to the reversal that cancels them, so summing total_cents gives the real
    amount spent."""
    ordered = sorted(entries, key=lambda e: e.seq)
    reversed_by = {e.reverses_seq: e.seq for e in ordered if e.reverses_seq is not None}

    return [
        StatementLine(
            seq=entry.seq,
            kind=entry.kind,
            occurred_on=entry.occurred_on,
            description=entry.description,
            total_cents=sum(
                p.amount_cents for p in entry.postings if p.role is Role.OUTLAY
            ),
            paid_by=tuple(
                sorted(
                    {p.participant_id for p in entry.postings if p.role is Role.OUTLAY}
                )
            ),
            reversed_by=reversed_by.get(entry.seq),
            reverses=entry.reverses_seq,
            transfer=_transfer(entry),
        )
        for entry in ordered
    ]


def _transfer(entry: Entry) -> StatementTransfer | None:
    paid = [p for p in entry.postings if p.role is Role.SETTLEMENT_PAID]
    received = [p for p in entry.postings if p.role is Role.SETTLEMENT_RECEIVED]
    if not paid or not received:
        return None
    return StatementTransfer(
        payer_id=paid[0].participant_id,
        payee_id=received[0].participant_id,
        amount_cents=sum(p.amount_cents for p in paid),
    )
