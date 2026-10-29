"""The strategy that feeds the plan's properties is checked too."""

from hypothesis import given
from plan_strategies import MAX_NON_ZERO, zero_sum_positions


@given(zero_sum_positions())
def test_generated_positions_are_balanced_and_bounded(positions):
    non_zero = [cents for cents in positions.values() if cents != 0]

    assert sum(positions.values()) == 0
    assert 2 <= len(non_zero) <= MAX_NON_ZERO
    assert any(cents > 0 for cents in non_zero)
    assert any(cents < 0 for cents in non_zero)
