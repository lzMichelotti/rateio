"""Refusals: what a person asked for that the system will not do.

A refusal is data, never prose. Each kind carries a machine-readable reason and
the fields needed to explain it; turning that into Portuguese is the job of
src/channel/messages.py alone. str() of a refusal is an English diagnostic for
logs, not a sentence for the group.

Programming errors (an unbalanced entry, a zero posting) are not refusals: they
stay plain exceptions and are never translated for a user.
"""

from enum import StrEnum
from typing import ClassVar


class RefusalReason(StrEnum):
    NOT_POSITIVE_AMOUNT = "not_positive_amount"
    SELF_PAYMENT = "self_payment"
    EXCEEDS_DEBT = "exceeds_debt"
    PAYER_NOT_MEMBER = "payer_not_member"
    ALREADY_REVERSED = "already_reversed"
    REVERSAL_OF_REVERSAL = "reversal_of_reversal"
    NOT_THE_CONFIRMER = "not_the_confirmer"
    NOT_A_PARTY = "not_a_party"
    ALREADY_RESOLVED = "already_resolved"
    SETTLEMENT_NEVER_EXPIRES = "settlement_never_expires"
    # Raised by the store, which looks things up; defined here so the domain
    # owns the closed list of reasons.
    ENTRY_NOT_FOUND = "entry_not_found"
    CONFIRMATION_NOT_FOUND = "confirmation_not_found"
    NO_FREE_CODE = "no_free_code"


class Refusal(ValueError):
    """Base of every refusal. Concrete kinds set `reason` and carry its fields."""

    reason: ClassVar[RefusalReason]


class NotPositiveAmountError(Refusal):
    """An expense total or a payment of zero or less. Shared by both."""

    reason = RefusalReason.NOT_POSITIVE_AMOUNT

    def __init__(self, amount_cents: int) -> None:
        self.amount_cents = amount_cents
        super().__init__(f"amount must be positive, got {amount_cents}")
