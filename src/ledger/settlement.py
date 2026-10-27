"""Settlement: one participant paying another to reduce what is owed.

Validation guards intentions; the ledger records facts. A declaration can be a
typo, so it is validated and may be refused. A confirmation is the payee
attesting that money arrived, so it is never refused on position grounds.
"""

from collections.abc import Mapping
from datetime import date

from ledger.model import Entry, EntryKind, Posting, Role


class DeclarationRefused(ValueError):
    """A settlement declaration the ledger will not open."""


class ExceedsDebtError(DeclarationRefused):
    def __init__(self, payer_id: str, amount_cents: int, debt_cents: int) -> None:
        self.payer_id = payer_id
        self.amount_cents = amount_cents
        self.debt_cents = debt_cents
        super().__init__(
            f"{payer_id} declared {amount_cents} cents but owes {debt_cents}; "
            "check the amount"
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
        raise DeclarationRefused(f"a settlement must be positive, got {amount_cents}")
    if payer_id == payee_id:
        raise DeclarationRefused(f"{payer_id} cannot pay themselves")
    debt_cents = max(0, -positions.get(payer_id, 0))
    if amount_cents > debt_cents:
        raise ExceedsDebtError(payer_id, amount_cents, debt_cents)


def record_settlement(
    *,
    seq: int,
    declared_on: date,
    payer_id: str,
    payee_id: str,
    amount_cents: int,
) -> Entry:
    """The entry for a confirmed payment: two legs, payer up, payee down.

    The payer's debt shrinks (+amount, settlement_paid) and the payee's credit
    shrinks (-amount, settlement_received). occurred_on is the declaration date,
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
        postings=(
            Posting(payer_id, amount_cents, Role.SETTLEMENT_PAID),
            Posting(payee_id, -amount_cents, Role.SETTLEMENT_RECEIVED),
        ),
    )
