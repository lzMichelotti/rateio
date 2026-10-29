"""Formatting money and reading it back are inverses."""

from hypothesis import given
from hypothesis import strategies as st

from channel.grammar import MAX_AMOUNT_CENTS, parse_amount
from channel.messages import amount


@given(cents=st.integers(min_value=1, max_value=MAX_AMOUNT_CENTS))
def test_formatting_then_parsing_returns_the_same_cents(cents):
    assert parse_amount(amount(cents)) == cents
