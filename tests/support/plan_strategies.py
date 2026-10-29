"""Hypothesis strategies for the settlement plan.

Random positions almost never contain a subgroup that sums to zero, and that is
exactly where a wrong plan (greedy, say) spends an extra transfer: a test fed
random positions passes without proving anything. So positions are built from
zero-sum groups and then scattered over shuffled ids, so a group's members are
not neighbours in the sorted order the plan starts from.
"""

from itertools import pairwise

from hypothesis import strategies as st

IDS = tuple(f"p{i}" for i in range(10))  # neutral fake ids: up to 10 per case
MAX_NON_ZERO = 8  # oracle: Bell(8) = 4140 partitions; plan: at most 7! orderings

# Small totals first: they shrink better, and they produce coincidental
# subgroups and ties that exercise criteria 2 and 3.
totals = st.one_of(st.integers(1, 20), st.integers(1, 200_000))


def _cut(draw, total: int, parts: int) -> list[int]:
    """Split total into `parts` positive integers, at distinct cut points."""
    if parts == 1:
        return [total]
    cuts = sorted(
        draw(
            st.lists(
                st.integers(1, total - 1),
                min_size=parts - 1,
                max_size=parts - 1,
                unique=True,
            )
        )
    )
    bounds = [0, *cuts, total]
    return [high - low for low, high in pairwise(bounds)]


def _zero_sum_group(draw, size: int) -> list[int]:
    """size non-zero amounts with both signs, summing to exactly zero."""
    creditors = draw(st.integers(1, size - 1))
    debtors = size - creditors
    # Large enough to cut into the larger side with every part at least 1.
    total = draw(totals) + max(creditors, debtors)
    return _cut(draw, total, creditors) + [-part for part in _cut(draw, total, debtors)]


@st.composite
def zero_sum_positions(draw) -> dict[str, int]:
    """Balanced positions made of one to four zero-sum groups, at most
    MAX_NON_ZERO of them non-zero, plus up to two participants at zero."""
    groups = draw(st.integers(1, MAX_NON_ZERO // 2))
    amounts: list[int] = []
    remaining = MAX_NON_ZERO
    for groups_after in reversed(range(groups)):
        # Leave room for the groups still to come, at least two members each.
        size = draw(st.integers(2, remaining - 2 * groups_after))
        amounts += _zero_sum_group(draw, size)
        remaining -= size
    amounts += [0] * draw(st.integers(0, 2))
    ids = draw(st.permutations(IDS))
    return dict(zip(ids, amounts))
