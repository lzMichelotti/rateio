"""The settlement plan: the fewest transfers that zero every position.

Advice, never state. It is computed on projected positions (confirmed facts plus
declared settlements), creates no entry, and is recomputed on every request.

Greedy matching (largest creditor against largest debtor) is not optimal:
+4, +3, +2, -5, -4 settles in three transfers, because -4 and +4 close on their
own, but greedy spends four. The minimum is the number of non-zero positions
minus the largest number of disjoint groups that each sum to zero. Laying the
creditors and the debtors out in every order and filling them by the
northwest-corner rule finds it: any partition into zero-sum groups is some pair
of orderings, one consecutive block per group.

Cost is creditors! x debtors!: 24 orderings at most for five participants,
about 1.6 billion for sixteen split eight and eight.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from itertools import permutations

from ledger.settlement import DeclaredSettlement


class UnbalancedPositionsError(ValueError):
    """Positions that do not sum to zero: no plan can zero them. Impossible
    while every entry is balanced, so it means break #6, not bad input."""


@dataclass(frozen=True, order=True)
class Transfer:
    """One payment the plan advises: payer_id sends amount_cents to payee_id."""

    payer_id: str
    payee_id: str
    amount_cents: int


def settlement_plan(positions: Mapping[str, int]) -> tuple[Transfer, ...]:
    """The best plan that zeroes every position, sorted by payer then payee.

    Best means, in this order: fewest transfers; then the largest smallest
    transfer, so no R$ 2,47 PIX when an equally short plan avoids it; then the
    lexicographically smallest plan, so the same positions always give the same
    plan, whatever order they arrive in.

    Criterion 1 is exact at any size. Criterion 2 is exact up to six non-zero
    positions: the northwest-corner rule only builds caterpillar trees, and
    every tree is one below seven nodes.
    """
    total = sum(positions.values())
    if total != 0:
        raise UnbalancedPositionsError(f"positions sum to {total}, not 0")
    creditors = sorted(p for p, cents in positions.items() if cents > 0)
    debtors = sorted(p for p, cents in positions.items() if cents < 0)
    return min(
        (
            _northwest_corner(ordered_creditors, ordered_debtors, positions)
            for ordered_creditors in permutations(creditors)
            for ordered_debtors in permutations(debtors)
        ),
        key=_rank,
    )


def book_settled(
    positions: Mapping[str, int], declared: Collection[DeclaredSettlement]
) -> bool:
    """Every confirmed position is zero and no settlement is waiting for its !ok.

    Derived on demand, never stored: a stored "settled" would be a second source
    of truth that a late receipt or a reversal could contradict. Not the same as
    an empty plan: a declared settlement can zero the projection while the payee
    has yet to confirm the money arrived. A book with no entries is settled.
    """
    return not declared and all(cents == 0 for cents in positions.values())


def _northwest_corner(
    creditors: Sequence[str], debtors: Sequence[str], positions: Mapping[str, int]
) -> tuple[Transfer, ...]:
    """Fill the first creditor from the first debtor until one is exhausted,
    advance past whoever is, repeat. When both run out together a zero-sum group
    has closed, and that is what saves a transfer."""
    owed = [positions[p] for p in creditors]
    owing = [-positions[p] for p in debtors]
    transfers = []
    c = d = 0
    while c < len(creditors) and d < len(debtors):
        amount = min(owed[c], owing[d])
        transfers.append(Transfer(debtors[d], creditors[c], amount))
        owed[c] -= amount
        owing[d] -= amount
        if owed[c] == 0:
            c += 1
        if owing[d] == 0:
            d += 1
    return tuple(sorted(transfers))


def _rank(plan: tuple[Transfer, ...]) -> tuple[int, int, tuple[Transfer, ...]]:
    smallest = min((t.amount_cents for t in plan), default=0)
    return (len(plan), -smallest, plan)
