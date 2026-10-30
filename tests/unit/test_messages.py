from datetime import UTC, date, datetime, timedelta

import pytest

from channel import messages
from channel.grammar import Member, ParseError, ParseReason, parse
from ledger.breaks import OVERPAYMENT, Break, IntentDuplicate, OutsideBookDates
from ledger.expense import record_expense
from ledger.positions import position_summary
from ledger.refusal import RefusalReason
from ledger.reversal import AlreadyReversedError, reverse
from ledger.settlement import DeclaredSettlement, ExceedsDebtError, record_settlement
from ledger.settlement_plan import Transfer
from ledger.statement import statement
from ledger.workflow import ConfirmationStatus

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]
NAMES = {pid: pid.capitalize() for pid in FIVE}
DAY = date(2027, 2, 20)
SENT = datetime(2027, 2, 20, 21, 0, tzinfo=UTC)


def expense(seq, payer_id, cents, description):
    return record_expense(
        seq=seq,
        occurred_on=DAY,
        payer_id=payer_id,
        total_cents=cents,
        description=description,
        participant_ids=FIVE,
    )


# -- money -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cents", "text"),
    [
        (123456, "R$ 1.234,56"),
        (18743, "R$ 187,43"),
        (1, "R$ 0,01"),
        (0, "R$ 0,00"),
        (100_000_000, "R$ 1.000.000,00"),
        (-120000, "−R$ 1.200,00"),
    ],
)
def test_money_is_brazilian(cents, text):
    assert messages.money(cents) == text


# -- proposals -------------------------------------------------------------------


def test_an_expense_proposal_names_its_code_and_never_the_remainder():
    text = messages.expense_proposed(
        author_id="vitor",
        amount_cents=18743,
        description="mercado",
        occurred_on=DAY,
        members=5,
        code="A7",
        warnings=(),
        at=SENT,
        names=NAMES,
    )

    assert text == (
        "🧾 *Nova despesa*\n"
        "Vitor pagou *R$ 187,43* de mercado (20/02)\n"
        "Dividido entre 5 pessoas\n"
        "\n"
        "Para confirmar, mande:\n"
        "*!ok A7*\n"
        "\n"
        "Para cancelar, mande:\n"
        "*!nao A7*"
    )
    assert "centavo" not in text


def test_warnings_follow_the_proposal():
    text = messages.expense_proposed(
        author_id="seph",
        amount_cents=41200,
        description="jantar",
        occurred_on=date(2026, 11, 2),
        members=5,
        code="M5",
        warnings=(
            IntentDuplicate("K4", SENT - timedelta(minutes=2)),
            OutsideBookDates(date(2026, 11, 2), date(2027, 2, 15), date(2027, 2, 25)),
        ),
        at=SENT,
        names=NAMES,
    )

    assert text.split("\n\n")[3:] == [
        (
            "⚠️ *Parece repetido*\n"
            "Você lançou o mesmo valor e a mesma descrição há 2 min (código K4).\n"
            "Se for outro gasto, confirme normalmente."
        ),
        (
            "⚠️ *Data fora da viagem*\n"
            "A data 02/11 não está entre 15/02 e 25/02.\n"
            "Se estiver certa, confirme normalmente."
        ),
    ]


def test_a_settlement_declaration_calls_the_payee():
    assert messages.settlement_declared(
        payer_id="vini", payee_id="lotti", amount_cents=4000, code="B3", names=NAMES
    ) == (
        "💸 *Pix informado*\n"
        "Vini diz que mandou *R$ 40,00* para Lotti\n"
        "\n"
        "Lotti, se o dinheiro chegou, mande:\n"
        "*!ok B3*\n"
        "\n"
        "Se não chegou, mande:\n"
        "*!nao B3*"
    )


# -- resolutions -----------------------------------------------------------------


def test_a_recorded_expense_says_what_and_who_but_not_the_remainder():
    (line,) = statement([expense(2, "vitor", 18743, "mercado")])

    assert messages.entry_recorded(line, names=NAMES) == (
        "✅ *Registrado: L2*\nmercado · R$ 187,43 · pago por Vitor"
    )


def test_a_recorded_settlement_and_its_overpayment():
    paid = record_settlement(
        seq=4, declared_on=DAY, payer_id="vini", payee_id="lotti", amount_cents=4000
    )
    (line,) = statement([paid])

    text = messages.entry_recorded(
        line, breaks=[Break(OVERPAYMENT, "vini", 1000)], names=NAMES
    )

    assert text == (
        "✅ *Pix confirmado: L4*\n"
        "Vini pagou R$ 40,00 a Lotti\n"
        "\n"
        "⚠️ *Pagou a mais*\n"
        "Com esse pix, Vini pagou R$ 10,00 a mais do que devia."
    )


def test_a_recorded_reversal_names_what_it_undoes():
    wrong = expense(5, "lotti", 120000, "lanche")
    undo = reverse(wrong, seq=6, author_id="lotti", book_entries=[wrong])
    _, line = statement([wrong, undo])

    assert messages.entry_recorded(line, names=NAMES) == (
        "✅ *Desfeito: L5*\nlanche · R$ 1.200,00 · registrado como L6"
    )


def test_repeating_a_resolution_says_nothing_changed():
    assert messages.unchanged("A7", ConfirmationStatus.CONFIRMED) == (
        "A7 já estava confirmado. Nada mudou."
    )


# -- reading the book ------------------------------------------------------------


def test_positions_use_words_not_signs():
    postings = expense(1, "lotti", 30000, "gasolina").postings

    assert messages.positions(
        position_summary(postings), members=FIVE, names=NAMES
    ).splitlines() == [
        "💰 *Saldo*",
        "Total gasto: *R$ 300,00*",
        "",
        "Lotti: recebe R$ 240,00",
        "Luis: deve R$ 60,00",
        "Seph: deve R$ 60,00",
        "Vini: deve R$ 60,00",
        "Vitor: deve R$ 60,00",
    ]


def test_the_statement_marks_reversals_on_both_sides_and_shows_payments():
    wrong = expense(5, "lotti", 120000, "lanche")
    undo = reverse(wrong, seq=6, author_id="lotti", book_entries=[wrong])
    paid = record_settlement(
        seq=7, declared_on=DAY, payer_id="vini", payee_id="lotti", amount_cents=4000
    )

    assert messages.statement(
        statement([wrong, undo, paid]), names=NAMES
    ).splitlines() == [
        "📋 *Últimos lançamentos*",
        "",
        "*L5* · 20/02 · lanche",
        "R$ 1.200,00 · pago por Lotti",
        "_desfeito pelo L6_",
        "",
        "*L6* · 20/02 · desfaz o L5 (lanche)",
        "−R$ 1.200,00",
        "",
        "*L7* · 20/02 · pix de Vini para Lotti",
        "R$ 40,00",
    ]


def test_an_empty_statement():
    assert messages.statement([], names=NAMES).endswith("Nenhum lançamento ainda.")


def test_the_settlement_plan_lists_transfers_and_pending_payments():
    postings = expense(1, "seph", 50000, "jantar").postings

    text = messages.settlement_plan(
        position_summary(postings),
        [Transfer("lotti", "seph", 10000)],
        [DeclaredSettlement("B3", "luis", "seph", 10000, DAY)],
        settled=False,
        members=["lotti", "luis", "seph"],
        names=NAMES,
    )

    assert text.splitlines()[-5:] == [
        "*Para zerar todo mundo*",
        "• Lotti paga *R$ 100,00* a Seph",
        "",
        "*Aguardando confirmação*",
        "• Pix de R$ 100,00 de Luis para Seph (código B3)",
    ]


def test_a_settled_trip_says_so():
    assert messages.settlement_plan(
        position_summary([]), [], [], settled=True, members=FIVE, names=NAMES
    ).endswith("Viagem quitada: ninguém deve nada. 🎉")


# -- what went wrong -------------------------------------------------------------


def test_every_parse_reason_has_a_message():
    for reason in ParseReason:
        text = messages.parse_error(ParseError(reason, "!gasto", "x"))
        assert text and "None" not in text


def test_an_unknown_command_points_to_help():
    assert "!ajuda" in messages.parse_error(ParseError(ParseReason.UNKNOWN_COMMAND))


def test_every_refusal_reason_has_a_message():
    assert set(messages._REFUSALS) == set(RefusalReason)


def test_refusals_are_explained_from_their_fields():
    assert messages.refusal(ExceedsDebtError("vini", 50000, 31792), names=NAMES) == (
        "Vini deve R$ 317,92, e o pix de R$ 500,00 é maior que isso.\nConfira o valor."
    )
    assert messages.refusal(AlreadyReversedError(5, 6), names=NAMES).startswith(
        "L5 já foi desfeito pelo L6."
    )


def test_help_shows_every_command_but_itself():
    # Whoever reads the help already found !ajuda.
    for verb in [
        "!gasto",
        "!pix",
        "!ok",
        "!nao",
        "!estorna",
        "!saldo",
        "!extrato",
        "!acerto",
    ]:
        assert verb in messages.help_text()


def test_every_example_in_the_help_is_a_command_the_grammar_reads():
    members = [Member("joao", "João"), Member("lotti", "Lotti")]
    examples = [
        part
        for line in messages.help_text().splitlines()
        if line.startswith("!")
        for part in line.split(" · ")[0].split(" ou ")
    ]
    assert len(examples) >= 9

    for example in examples:
        assert not isinstance(parse(example, members=members, today=DAY), ParseError), (
            example
        )
