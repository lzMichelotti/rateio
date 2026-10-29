"""The parser is total: whatever is typed, it answers instead of raising."""

from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from channel.commands import Command
from channel.grammar import Member, ParseError, parse

MEMBERS = [Member("lotti", "Lotti"), Member("luis", "Luis"), Member("ze", "Zé")]
VERBS = [
    "!gasto",
    "!pix",
    "!ok",
    "!nao",
    "!não",
    "!estorna",
    "!saldo",
    "!extrato",
    "!acerto",
    "!ajuda",
]

# Pieces that look like arguments, so generated text gets past the verb and
# into each command's own reading; plain text alone almost never would.
pieces = st.one_of(
    st.text(max_size=12),
    st.from_regex(r"-?[0-9.,]{1,25}", fullmatch=True),
    st.from_regex(r"[0-9]{1,3}/[0-9]{1,3}", fullmatch=True),
    st.from_regex(r"@[\w]{0,6}", fullmatch=True),
    st.from_regex(r"[A-Za-z][0-9]", fullmatch=True),
    st.from_regex(r"[Ll]?[0-9]{1,12}", fullmatch=True),
)
commandish = st.builds(
    lambda verb, args: " ".join([verb, *args]),
    st.sampled_from(VERBS),
    st.lists(pieces, max_size=5),
)
days = st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))


@given(text=st.one_of(st.text(), commandish), today=days)
def test_the_parser_never_raises(text, today):
    result = parse(text, members=MEMBERS, today=today)

    assert isinstance(result, Command | ParseError)
