"""Breaks: conditions the ledger reports to the group and never decides on.

Breaks are derived from the log, never stored as truth. Numbers follow the
architecture's list of breaks.
"""

from collections.abc import Mapping
from dataclasses import dataclass

OVERPAYMENT = 7


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
