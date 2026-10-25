"""The ledger's core records: an entry and its postings.

Pure data. No database, no clock, no I/O: identity (id, command_id) and
recorded_at are assigned by the store when the entry is written.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class EntryKind(StrEnum):
    EXPENSE = "expense"
    SETTLEMENT = "settlement"
    REVERSAL = "reversal"


class Role(StrEnum):
    OUTLAY = "outlay"
    SHARE = "share"
    SETTLEMENT_PAID = "settlement_paid"
    SETTLEMENT_RECEIVED = "settlement_received"
    REVERSAL = "reversal"


class UnbalancedEntryError(ValueError):
    """An entry whose postings do not sum to exactly zero."""


@dataclass(frozen=True)
class Posting:
    """One leg of an entry. Positive means the book owes this participant more."""

    participant_id: str
    amount_cents: int
    role: Role

    def __post_init__(self) -> None:
        if self.amount_cents == 0:
            raise ValueError("a posting cannot be zero")


@dataclass(frozen=True)
class Entry:
    """An immutable financial fact. It cannot exist unbalanced."""

    seq: int
    kind: EntryKind
    occurred_on: date
    author_id: str
    description: str
    postings: tuple[Posting, ...]
    remainder_offset: int | None = None

    def __post_init__(self) -> None:
        if not self.postings:
            raise UnbalancedEntryError("an entry needs at least one posting")
        total = sum(p.amount_cents for p in self.postings)
        if total != 0:
            raise UnbalancedEntryError(f"postings sum to {total}, not 0")
