"""Settlement: one participant paying another to reduce what is owed.

Validation guards intentions; the ledger records facts. A declaration can be a
typo, so it is validated and may be refused. A confirmation is the payee
attesting that money arrived, so it is never refused on position grounds.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from ledger.model import Entry, EntryKind, Posting, Role
from ledger.refusal import NotPositiveAmountError, Refusal, RefusalReason


@dataclass(frozen=True)
class DeclaredSettlement:
    """A payment the payer announced and the payee has not confirmed yet.

    Workflow state, not a fact: it never reaches positions(). The settlement
    plan applies it as if confirmed, so nobody is told to pay twice.
    """

    code: str
    payer_id: str
    payee_id: str
    amount_cents: int
    declared_on: date


class DeclarationRefused(Refusal):
    """A settlement declaration the ledger will not open."""


class SelfPaymentError(DeclarationRefused):
    reason = RefusalReason.SELF_PAYMENT

    def __init__(self, participant_id: str) -> None:
        self.participant_id = participant_id
        super().__init__(f"{participant_id} declared a payment to themselves")


class ExceedsDebtError(DeclarationRefused):
    reason = RefusalReason.EXCEEDS_DEBT

    def __init__(self, payer_id: str, amount_cents: int, debt_cents: int) -> None:
        self.payer_id = payer_id
        self.amount_cents = amount_cents
        self.debt_cents = debt_cents
        super().__init__(
            f"{payer_id} declared {amount_cents} cents but owes {debt_cents}"
        )


def validate_declaration(
    positions: Mapping[str, int],
    *,
    payer_id: str,
    payee_id: str,
    amount_cents: int,
) -> None:
    """Refuse a declaration that pays more than the payer owes, or makes no sense.

    The payer's debt is the negative of their position (zero if they owe
    nothing). Positions are taken at declaration time; by confirmation they may
    have moved, and that is the overpayment break's concern, not this one's.
    """
    if amount_cents <= 0:
        raise NotPositiveAmountError(amount_cents)
    if payer_id == payee_id:
        raise SelfPaymentError(payer_id)
    debt_cents = max(0, -positions.get(payer_id, 0))
    if amount_cents > debt_cents:
        raise ExceedsDebtError(payer_id, amount_cents, debt_cents)


def settlement_postings(
    payer_id: str, payee_id: str, amount_cents: int
) -> tuple[Posting, Posting]:
    """The two legs of a payment: the payer's debt shrinks (+amount,
    settlement_paid) and the payee's credit shrinks (-amount,
    settlement_received). The one place that decides their signs."""
    return (
        Posting(payer_id, amount_cents, Role.SETTLEMENT_PAID),
        Posting(payee_id, -amount_cents, Role.SETTLEMENT_RECEIVED),
    )


def record_settlement(
    *,
    seq: int,
    declared_on: date,
    payer_id: str,
    payee_id: str,
    amount_cents: int,
) -> Entry:
    """The entry for a confirmed payment: two legs, payer up, payee down.

    occurred_on is the declaration date,
    when the money moved, passed in because the domain never reads the clock;
    recorded_at, assigned by the store, is when the payee confirmed. The author
    is the payer, whose !pix is the proposing command the entry carries.
    """
    return Entry(
        seq=seq,
        kind=EntryKind.SETTLEMENT,
        occurred_on=declared_on,
        author_id=payer_id,
        description="",
        postings=settlement_postings(payer_id, payee_id, amount_cents),
    )
