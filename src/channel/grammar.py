"""The command grammar: text in, a typed command or an explained parse error out.

A total function. It never raises for any text: a person's typo is an answer to
give, not an exception. Pure: the members of the book and today's business date
are passed in, so it never reads the database or the clock.

Money is converted on the text itself, straight to integer cents: no float, no
Decimal. Patterns use re.ASCII, because \\d would otherwise match digits of any
script and int() would accept them.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from channel.commands import (
    Command,
    Confirm,
    DeclareSettlement,
    Help,
    RecordExpense,
    Reject,
    Reverse,
    ShowPosition,
    ShowSettlementPlan,
    ShowStatement,
)
from ledger.text import fold

# Above this an amount is a typo on a trip, and well inside bigint.
MAX_AMOUNT_CENTS = 100_000_000  # R$ 1.000.000,00
STATEMENT_DEFAULT_LIMIT = 10
STATEMENT_MAX_LIMIT = 50
# int() refuses strings past sys.get_int_max_str_digits(); stop long before.
_MAX_DIGITS = 12

# Comma is decimal, dot is thousands: 150, 150,5, 1.250, 1.250,00.
_BRAZILIAN = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?", re.ASCII)
# A dot followed by one or two final digits, with no comma, is decimal: 87.50.
_DOT_DECIMAL = re.compile(r"(\d+)\.(\d{1,2})", re.ASCII)
_DATE = re.compile(r"(\d{1,2})/(\d{1,2})", re.ASCII)
# The same 184 codes as the database CHECK: no I, L, O, 0 or 1.
_CODE = re.compile(r"[A-HJKMNP-Z][2-9]", re.ASCII)
_ENTRY = re.compile(r"[Ll]?(\d{1,9})", re.ASCII)
_LIMIT = re.compile(r"\d{1,9}", re.ASCII)


class ParseReason(StrEnum):
    """Why a text is not a command. Not understanding, as opposed to a Refusal:
    understanding and declining."""

    UNKNOWN_COMMAND = "unknown_command"
    UNEXPECTED_ARGUMENTS = "unexpected_arguments"
    MISSING_AMOUNT = "missing_amount"
    INVALID_AMOUNT = "invalid_amount"
    TOO_MANY_DECIMALS = "too_many_decimals"
    NOT_POSITIVE_AMOUNT = "not_positive_amount"
    AMOUNT_TOO_LARGE = "amount_too_large"
    MISSING_DESCRIPTION = "missing_description"
    INVALID_DATE = "invalid_date"
    MISSING_PERSON = "missing_person"
    UNKNOWN_PERSON = "unknown_person"
    AMBIGUOUS_PERSON = "ambiguous_person"
    MISSING_CODE = "missing_code"
    INVALID_CODE = "invalid_code"
    MISSING_ENTRY = "missing_entry"
    INVALID_ENTRY = "invalid_entry"
    INVALID_LIMIT = "invalid_limit"


@dataclass(frozen=True)
class ParseError:
    """A text that is not a command. verb is the command it was read as, if
    any; token is the piece that could not be read, if one is to blame."""

    reason: ParseReason
    verb: str | None = None
    token: str | None = None


@dataclass(frozen=True)
class Member:
    participant_id: str
    display_name: str


def parse(text: str, *, members: Sequence[Member], today: date) -> Command | ParseError:
    """Read one message. today is the business date in America/Sao_Paulo,
    computed at the edge; members are the book's, for resolving @person."""
    tokens = text.split()
    if not tokens:
        return ParseError(ParseReason.UNKNOWN_COMMAND)
    verb = fold(tokens[0])
    read = _VERBS.get(verb)
    if read is None:
        return ParseError(ParseReason.UNKNOWN_COMMAND, token=tokens[0])
    return read(verb, tokens[1:], members, today)


def parse_amount(token: str) -> int | ParseReason:
    """Integer cents from a Brazilian amount, or why it is not one."""
    if token.startswith("-"):
        return ParseReason.NOT_POSITIVE_AMOUNT
    if match := _DOT_DECIMAL.fullmatch(token):
        reais, fraction = match[1], match[2]
    elif match := _BRAZILIAN.fullmatch(token):
        reais, fraction = match[1].replace(".", ""), match[2] or ""
        if len(fraction) > 2:
            return ParseReason.TOO_MANY_DECIMALS
    else:
        return ParseReason.INVALID_AMOUNT
    if len(reais.lstrip("0")) > _MAX_DIGITS:
        return ParseReason.AMOUNT_TOO_LARGE
    cents = int(reais) * 100 + int(fraction.ljust(2, "0"))
    if cents == 0:
        return ParseReason.NOT_POSITIVE_AMOUNT
    if cents > MAX_AMOUNT_CENTS:
        return ParseReason.AMOUNT_TOO_LARGE
    return cents


def resolve_date(token: str, today: date) -> date | None:
    """The most recent dd/mm that is not in the future: this year's, or last
    year's when this year's is ahead or does not exist. None if neither is."""
    match = _DATE.fullmatch(token)
    if match is None:
        return None
    day, month = int(match[1]), int(match[2])
    for year in (today.year, today.year - 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate <= today:
            return candidate
    return None


def _expense(
    verb: str, args: list[str], members: Sequence[Member], today: date
) -> Command | ParseError:
    if not args:
        return ParseError(ParseReason.MISSING_AMOUNT, verb)
    amount = parse_amount(args[0])
    if isinstance(amount, ParseReason):
        return ParseError(amount, verb, args[0])
    words = args[1:]
    occurred_on = today
    if words and _DATE.fullmatch(words[-1]):
        resolved = resolve_date(words[-1], today)
        if resolved is None:
            return ParseError(ParseReason.INVALID_DATE, verb, words[-1])
        occurred_on, words = resolved, words[:-1]
    if not words:
        return ParseError(ParseReason.MISSING_DESCRIPTION, verb)
    return RecordExpense(amount, " ".join(words), occurred_on)


def _settlement(
    verb: str, args: list[str], members: Sequence[Member], today: date
) -> Command | ParseError:
    if not args or not args[0].startswith("@"):
        return ParseError(ParseReason.MISSING_PERSON, verb)
    if len(args) < 2:
        return ParseError(ParseReason.MISSING_AMOUNT, verb)
    if len(args) > 2:
        return ParseError(ParseReason.UNEXPECTED_ARGUMENTS, verb, " ".join(args[2:]))
    wanted = fold(args[0][1:])
    matches = {
        m.participant_id
        for m in members
        if wanted and wanted in (fold(m.participant_id), fold(m.display_name))
    }
    if not matches:
        return ParseError(ParseReason.UNKNOWN_PERSON, verb, args[0])
    if len(matches) > 1:
        return ParseError(ParseReason.AMBIGUOUS_PERSON, verb, args[0])
    amount = parse_amount(args[1])
    if isinstance(amount, ParseReason):
        return ParseError(amount, verb, args[1])
    return DeclareSettlement(matches.pop(), amount)


def _code(
    make: Callable[[str], Command],
) -> Callable[[str, list[str], Sequence[Member], date], Command | ParseError]:
    def read(
        verb: str, args: list[str], members: Sequence[Member], today: date
    ) -> Command | ParseError:
        if not args:
            return ParseError(ParseReason.MISSING_CODE, verb)
        if len(args) > 1:
            return ParseError(
                ParseReason.UNEXPECTED_ARGUMENTS, verb, " ".join(args[1:])
            )
        code = args[0].upper()
        if not _CODE.fullmatch(code):
            return ParseError(ParseReason.INVALID_CODE, verb, args[0])
        return make(code)

    return read


def _reverse(
    verb: str, args: list[str], members: Sequence[Member], today: date
) -> Command | ParseError:
    if not args:
        return ParseError(ParseReason.MISSING_ENTRY, verb)
    if len(args) > 1:
        return ParseError(ParseReason.UNEXPECTED_ARGUMENTS, verb, " ".join(args[1:]))
    match = _ENTRY.fullmatch(args[0])
    if match is None or int(match[1]) < 1:
        return ParseError(ParseReason.INVALID_ENTRY, verb, args[0])
    return Reverse(int(match[1]))


def _statement(
    verb: str, args: list[str], members: Sequence[Member], today: date
) -> Command | ParseError:
    if not args:
        return ShowStatement(STATEMENT_DEFAULT_LIMIT)
    if len(args) > 1:
        return ParseError(ParseReason.UNEXPECTED_ARGUMENTS, verb, " ".join(args[1:]))
    if not _LIMIT.fullmatch(args[0]) or not (1 <= int(args[0]) <= STATEMENT_MAX_LIMIT):
        return ParseError(ParseReason.INVALID_LIMIT, verb, args[0])
    return ShowStatement(int(args[0]))


def _bare(
    make: Callable[[], Command],
) -> Callable[[str, list[str], Sequence[Member], date], Command | ParseError]:
    def read(
        verb: str, args: list[str], members: Sequence[Member], today: date
    ) -> Command | ParseError:
        if args:
            return ParseError(ParseReason.UNEXPECTED_ARGUMENTS, verb, " ".join(args))
        return make()

    return read


# Keys are folded, so !nao typed with a tilde, in capitals or plain is one verb.
_VERBS: dict[
    str, Callable[[str, list[str], Sequence[Member], date], Command | ParseError]
] = {
    "!gasto": _expense,
    "!pix": _settlement,
    "!ok": _code(Confirm),
    "!nao": _code(Reject),
    "!estorna": _reverse,
    "!saldo": _bare(ShowPosition),
    "!extrato": _statement,
    "!acerto": _bare(ShowSettlementPlan),
    "!ajuda": _bare(Help),
}
