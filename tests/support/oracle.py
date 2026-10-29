"""An independent oracle for the length of the settlement plan.

It shares nothing with ledger.settlement_plan: no orderings, no northwest
corner, no transfers. It counts groups instead. A zero-sum group of k people
needs at least k - 1 transfers to connect them, and k - 1 suffice, so over the
best split into zero-sum groups the minimum is (non-zero positions) - (groups).

Brute force over every set partition: Bell(n) of them, 52 for five positions,
4140 for eight. Lives in tests/ and is never imported from src/.
"""

from collections.abc import Iterator, Mapping


def minimum_transfers(positions: Mapping[str, int]) -> int:
    """The fewest transfers that can zero these positions."""
    amounts = [cents for cents in positions.values() if cents != 0]
    assert sum(amounts) == 0, "the oracle only judges balanced positions"
    most_groups = max(
        len(partition)
        for partition in partitions(amounts)
        if all(sum(group) == 0 for group in partition)
    )
    return len(amounts) - most_groups


def partitions(items: list[int]) -> Iterator[list[list[int]]]:
    """Every way to split items into groups: the first item joins one of the
    groups of a partition of the rest, or starts a group of its own."""
    if not items:
        yield []
        return
    first, rest = items[0], items[1:]
    for partition in partitions(rest):
        for i, group in enumerate(partition):
            yield [*partition[:i], [first, *group], *partition[i + 1 :]]
        yield [[first], *partition]
