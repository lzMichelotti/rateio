"""Breaks: conditions the ledger reports to the group and never decides on.

Breaks are derived from the log, never stored as truth. Numbers follow the
architecture's list of breaks.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import ClassVar

from ledger.text import fold

INTENT_DUPLICATE = 1
OUTSIDE_BOOK_DATES = 4
OVERPAYMENT = 7

# "Within 10 minutes" is strict: a proposal exactly 10 minutes later is new.
DUPLICATE_WINDOW = timedelta(minutes=10)


@dataclass(frozen=True)
class Break:
    number: int
    participant_id: str
    position_cents: int


def overpayment_breaks(
    positions_after: Mapping[str, int], *, payer_id: str, payee_id: str
) -> list[Break]:
    """Break 7, after a settlement is confirmed: the payer became a creditor or the
    payee became a debtor. Reported, never blocked: the payment happened.

    This happens when positions moved between declaration and confirmation (an
    expense was reversed, another settlement was confirmed first).
    """
    breaks = []
    payer_position = positions_after.get(payer_id, 0)
    if payer_position > 0:
        breaks.append(Break(OVERPAYMENT, payer_id, payer_position))
    payee_position = positions_after.get(payee_id, 0)
    if payee_position < 0:
        breaks.append(Break(OVERPAYMENT, payee_id, payee_position))
    return breaks


@dataclass(frozen=True)
class ExpenseIntent:
    """An expense someone proposed: who, how much, what, and when they sent it.
    `at` is the message's time, an input like every other clock reading."""

    author_id: str
    amount_cents: int
    description: str
    at: datetime
    code: str = ""  # the confirmation code, once the proposal has one


@dataclass(frozen=True)
class IntentDuplicate:
    """Break 1: the same author proposed the same amount and description less
    than DUPLICATE_WINDOW ago. Two R$ 46,80 tolls on one day do exist, so this
    asks; it never refuses."""

    number: ClassVar[int] = INTENT_DUPLICATE
    previous_code: str
    previous_at: datetime


@dataclass(frozen=True)
class OutsideBookDates:
    """Break 4: the expense's business date is outside the trip. Asks."""

    number: ClassVar[int] = OUTSIDE_BOOK_DATES
    occurred_on: date
    starts_on: date
    ends_on: date


ProposalWarning = IntentDuplicate | OutsideBookDates


def proposal_warnings(
    new: ExpenseIntent,
    recent: Iterable[ExpenseIntent],
    *,
    occurred_on: date,
    starts_on: date,
    ends_on: date,
) -> tuple[ProposalWarning, ...]:
    """Breaks 1 and 4 for an expense proposal. The proposal is made either way:
    a warning travels with it, and the author decides by confirming or not.

    recent holds the author's other live proposals (open or confirmed); a
    discarded one was abandoned on purpose and does not count. Descriptions are
    compared folded and with runs of spaces collapsed: "Jantar" repeats
    "jantar".
    """
    warnings: list[ProposalWarning] = []
    same = _comparable(new.description)
    earlier = [
        p
        for p in recent
        if p.author_id == new.author_id
        and p.amount_cents == new.amount_cents
        and _comparable(p.description) == same
        and timedelta(0) <= new.at - p.at < DUPLICATE_WINDOW
    ]
    if earlier:
        latest = max(earlier, key=lambda p: p.at)
        warnings.append(IntentDuplicate(latest.code, latest.at))
    if not starts_on <= occurred_on <= ends_on:
        warnings.append(OutsideBookDates(occurred_on, starts_on, ends_on))
    return tuple(warnings)


def _comparable(description: str) -> str:
    return " ".join(fold(description).split())
