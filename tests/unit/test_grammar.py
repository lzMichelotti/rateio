from datetime import date

import pytest

from channel.commands import (
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
from channel.grammar import Member, ParseError, ParseReason, parse, parse_amount

TODAY = date(2027, 2, 20)
# ze/Zé is a test-only member: the seed has no accented names.
MEMBERS = [
    Member("lotti", "Lotti"),
    Member("luis", "Luis"),
    Member("seph", "Seph"),
    Member("ze", "Zé"),
]


def read(text: str, members=MEMBERS):
    return parse(text, members=members, today=TODAY)


# -- amounts ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "cents"),
    [
        ("150", 15000),
        ("150,5", 15050),
        ("150,50", 15050),
        ("1.250", 125000),
        ("1.250,00", 125000),
        ("187,43", 18743),
        ("87.50", 8750),
        ("87.5", 8750),
        ("0,01", 1),
        ("1.000.000", 100_000_000),
    ],
)
def test_accepted_amounts_become_integer_cents(token, cents):
    assert parse_amount(token) == cents


@pytest.mark.parametrize(
    ("token", "reason"),
    [
        ("1,234", ParseReason.TOO_MANY_DECIMALS),
        ("0", ParseReason.NOT_POSITIVE_AMOUNT),
        ("0,00", ParseReason.NOT_POSITIVE_AMOUNT),
        ("-5", ParseReason.NOT_POSITIVE_AMOUNT),
        ("1.000.000,01", ParseReason.AMOUNT_TOO_LARGE),
        ("9" * 5000, ParseReason.AMOUNT_TOO_LARGE),
        ("12,", ParseReason.INVALID_AMOUNT),
        ("1.25.0", ParseReason.INVALID_AMOUNT),
        ("dez", ParseReason.INVALID_AMOUNT),
        ("٣٠٠", ParseReason.INVALID_AMOUNT),  # Arabic-Indic digits
    ],
)
def test_refused_amounts_say_why(token, reason):
    assert parse_amount(token) == reason


def test_a_dot_followed_by_three_digits_is_always_thousands():
    assert parse_amount("87.505") == 8_750_500


# -- expenses and dates ----------------------------------------------------------


def test_an_expense_without_a_date_happened_today():
    assert read("!gasto 300 gasolina") == RecordExpense(30000, "gasolina", TODAY)


def test_the_description_keeps_what_was_typed():
    assert read("!gasto 46,80 Pedágio da   serra") == RecordExpense(
        4680, "Pedágio da serra", TODAY
    )


def test_a_past_date_this_year_is_taken_as_is():
    assert read("!gasto 83,37 caipirinhas 18/02") == RecordExpense(
        8337, "caipirinhas", date(2027, 2, 18)
    )


def test_a_date_ahead_of_today_is_last_years():
    assert read("!gasto 50 presente 25/12").occurred_on == date(2026, 12, 25)


def test_today_itself_is_not_the_future():
    assert read("!gasto 50 lanche 20/02").occurred_on == TODAY


@pytest.mark.parametrize("token", ["31/02", "29/02", "00/01", "12/13"])
def test_a_date_that_does_not_exist_is_refused(token):
    assert read(f"!gasto 50 lanche {token}") == ParseError(
        ParseReason.INVALID_DATE, "!gasto", token
    )


def test_an_expense_needs_an_amount_and_a_description():
    assert read("!gasto").reason is ParseReason.MISSING_AMOUNT
    assert read("!gasto 300").reason is ParseReason.MISSING_DESCRIPTION
    assert read("!gasto 300 12/02").reason is ParseReason.MISSING_DESCRIPTION
    assert read("!gasto trezentos gasolina").reason is ParseReason.INVALID_AMOUNT


# -- people ----------------------------------------------------------------------


@pytest.mark.parametrize("who", ["@ze", "@Zé", "@ZE", "@zé", "@ZÉ"])
def test_a_person_matches_by_id_or_name_ignoring_case_and_accents(who):
    assert read(f"!pix {who} 40") == DeclareSettlement("ze", 4000)


def test_an_unknown_person_is_refused():
    assert read("!pix @pedro 40") == ParseError(
        ParseReason.UNKNOWN_PERSON, "!pix", "@pedro"
    )


def test_a_name_that_matches_two_members_is_never_guessed():
    members = [Member("ana", "Bia"), Member("bia", "Beatriz")]

    assert read("!pix @bia 40", members).reason is ParseReason.AMBIGUOUS_PERSON


@pytest.mark.parametrize(
    "text", ["!pix @ze 40", "!pix 40 @ze", "!pix ze 40", "!pix 40 ze", "!pix Zé 40"]
)
def test_a_settlement_reads_the_person_and_the_amount_in_either_order(text):
    # How people typed it on a real group: amount first, or the name without @.
    assert read(text) == DeclareSettlement("ze", 4000)


def test_a_settlement_needs_a_person_and_an_amount():
    assert read("!pix").reason is ParseReason.MISSING_PERSON
    assert read("!pix 40").reason is ParseReason.MISSING_PERSON
    assert read("!pix 40 50").reason is ParseReason.MISSING_PERSON
    assert read("!pix @ze").reason is ParseReason.MISSING_AMOUNT
    assert read("!pix ze").reason is ParseReason.MISSING_AMOUNT
    assert read("!pix @ ze").reason is ParseReason.UNKNOWN_PERSON
    assert read("!pix @dudu 40") == ParseError(
        ParseReason.UNKNOWN_PERSON, "!pix", "@dudu"
    )
    assert read("!pix @ze 40 50").reason is ParseReason.UNEXPECTED_ARGUMENTS
    assert read("!pix @ze quarenta").reason is ParseReason.INVALID_AMOUNT


# -- codes, entries, statement ---------------------------------------------------


def test_codes_are_case_insensitive():
    assert read("!ok a7") == read("!ok A7") == Confirm("A7")


@pytest.mark.parametrize("verb", ["!nao", "!não", "!NÃO", "!Nao"])
def test_the_decline_verb_reads_with_or_without_accent(verb):
    assert read(f"{verb} A7") == Reject("A7")


@pytest.mark.parametrize("code", ["O7", "A1", "AA", "A", "A77"])
def test_a_code_outside_the_184_is_refused(code):
    assert read(f"!ok {code}").reason is ParseReason.INVALID_CODE


@pytest.mark.parametrize("token", ["L12", "l12", "12"])
def test_an_entry_is_named_with_or_without_its_l(token):
    assert read(f"!estorna {token}") == Reverse(12)


@pytest.mark.parametrize("token", ["L0", "Lx", "-3", "L"])
def test_an_invalid_entry_is_refused(token):
    assert read(f"!estorna {token}").reason is ParseReason.INVALID_ENTRY


def test_the_statement_shows_ten_unless_told_otherwise():
    assert read("!extrato") == ShowStatement(10)
    assert read("!extrato 3") == ShowStatement(3)


@pytest.mark.parametrize("token", ["0", "51", "dez"])
def test_a_statement_limit_outside_one_to_fifty_is_refused(token):
    assert read(f"!extrato {token}").reason is ParseReason.INVALID_LIMIT


# -- the rest --------------------------------------------------------------------


def test_commands_without_arguments():
    assert read("!saldo") == ShowPosition()
    assert read("!acerto") == ShowSettlementPlan()
    assert read("!ajuda") == Help()


def test_extra_words_are_never_silently_ignored():
    assert read("!saldo agora").reason is ParseReason.UNEXPECTED_ARGUMENTS
    assert read("!ok A7 valeu").reason is ParseReason.UNEXPECTED_ARGUMENTS


@pytest.mark.parametrize("text", ["", "   ", "oi", "!fechar", "gasto 300 x"])
def test_anything_else_is_an_unknown_command(text):
    assert read(text).reason is ParseReason.UNKNOWN_COMMAND


def test_the_command_payload_holds_the_participant_id_not_the_text():
    assert read("!pix @Zé 40").payload() == {"counterparty": "ze", "amount_cents": 4000}
