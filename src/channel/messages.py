"""Every message the bot sends, in Portuguese. The only module with Portuguese.

Pure functions from domain objects to text: no database, no clock. The domain
knows participant ids; `names` maps them to display names here, at the edge.

The rounding remainder is never mentioned: it is settled in the postings and
shows in positions, but a message about stray cents would be noise.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

from channel.grammar import (
    MAX_AMOUNT_CENTS,
    STATEMENT_MAX_LIMIT,
    ParseError,
    ParseReason,
)
from ledger.breaks import Break, IntentDuplicate, OutsideBookDates, ProposalWarning
from ledger.model import EntryKind
from ledger.positions import PositionSummary
from ledger.refusal import Refusal, RefusalReason
from ledger.settlement import DeclaredSettlement
from ledger.settlement_plan import Transfer
from ledger.statement import StatementLine
from ledger.workflow import ConfirmationStatus

Names = Mapping[str, str]

# -- formatting ------------------------------------------------------------------


def amount(cents: int) -> str:
    """1.234,56: dot for thousands, comma for decimals. Never through float."""
    sign = "-" if cents < 0 else ""
    reais, centavos = divmod(abs(cents), 100)
    return f"{sign}{reais:,}".replace(",", ".") + f",{centavos:02d}"


def money(cents: int) -> str:
    """R$ 1.234,56, and −R$ 1.234,56 for a negative amount."""
    if cents < 0:
        return f"−R$ {amount(-cents)}"
    return f"R$ {amount(cents)}"


def day(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}"


def _name(names: Names, participant_id: str) -> str:
    return names.get(participant_id, participant_id)


def _either(people: Sequence[str]) -> str:
    return " ou ".join(people)


# -- proposals -------------------------------------------------------------------


def expense_proposed(
    *,
    author_id: str,
    amount_cents: int,
    description: str,
    occurred_on: date,
    members: int,
    code: str,
    warnings: Sequence[ProposalWarning],
    at: datetime,
    names: Names,
) -> str:
    lines = [
        (
            f"{_name(names, author_id)} lançou {money(amount_cents)} de {description} "
            f"({day(occurred_on)}), dividido entre {members}."
        ),
        f"Confirme com !ok {code} ou cancele com !nao {code}.",
    ]
    lines += [warning(w, at) for w in warnings]
    return "\n".join(lines)


def warning(w: ProposalWarning, at: datetime) -> str:
    if isinstance(w, IntentDuplicate):
        minutes = int((at - w.previous_at).total_seconds() // 60)
        when = "há menos de 1 min" if minutes < 1 else f"há {minutes} min"
        return (
            f"Atenção: você lançou o mesmo valor e a mesma descrição {when} "
            f"(código {w.previous_code}). Se for outro gasto, confirme normalmente."
        )
    if isinstance(w, OutsideBookDates):
        return (
            f"Atenção: a data {day(w.occurred_on)} está fora da viagem "
            f"({day(w.starts_on)} a {day(w.ends_on)})."
        )
    raise TypeError(f"unknown warning {w!r}")


def settlement_declared(
    *, payer_id: str, payee_id: str, amount_cents: int, code: str, names: Names
) -> str:
    payee = _name(names, payee_id)
    return (
        f"{_name(names, payer_id)} diz que mandou um pix de {money(amount_cents)} "
        f"para {payee}.\n"
        f"{payee}, confirme com !ok {code} se chegou, ou !nao {code} se não chegou."
    )


def reversal_proposed(*, target: StatementLine, code: str, names: Names) -> str:
    return (
        f"Estornar L{target.seq} ({_what(target, names)})? "
        f"Confirme com !ok {code} ou cancele com !nao {code}."
    )


# -- resolutions -----------------------------------------------------------------


def entry_recorded(
    line: StatementLine, *, breaks: Sequence[Break] = (), names: Names
) -> str:
    """The !ok that turned a proposal into an entry."""
    if line.kind is EntryKind.REVERSAL:
        text = f"L{line.seq} registrado: estorno de L{line.reverses} ({_what(line, names)})."
    elif line.transfer is not None:
        text = f"L{line.seq} registrado: {_what(line, names)}."
    else:
        text = (
            f"L{line.seq} registrado: {line.description}, {money(line.total_cents)}, "
            f"pago por {_payers(line, names)}."
        )
    return "\n".join([text, *(overpayment(b, names) for b in breaks)])


def overpayment(b: Break, names: Names) -> str:
    """Break 7: reported, never blocking. A positive payer or a negative payee."""
    who = _name(names, b.participant_id)
    if b.position_cents > 0:
        return f"Atenção: com esse pix, {who} pagou {money(b.position_cents)} a mais do que devia."
    return (
        f"Atenção: com esse pix, {who} recebeu {money(-b.position_cents)} a mais "
        "do que tinha a receber."
    )


def proposal_discarded(code: str) -> str:
    return f"{code} cancelado. Nada foi registrado."


def settlement_rejected(
    *, payer_id: str, payee_id: str, amount_cents: int, code: str, names: Names
) -> str:
    return (
        f"{_name(names, payee_id)} disse que o pix de {money(amount_cents)} de "
        f"{_name(names, payer_id)} não chegou ({code}). Nada foi registrado."
    )


def settlement_cancelled(
    *, payer_id: str, amount_cents: int, code: str, names: Names
) -> str:
    return (
        f"{_name(names, payer_id)} cancelou o pix de {money(amount_cents)} ({code}). "
        "Nada foi registrado."
    )


# Keyed by value: refusals carry a confirmation's or a settlement's status as
# text, and a StrEnum member looks up the same as its value.
_STATUS = {
    "open": "aberto",
    "confirmed": "confirmado",
    "discarded": "cancelado",
    "expired": "expirado",
    "declared": "declarado",
    "rejected": "recusado",
    "cancelled": "cancelado",
}


def unchanged(code: str, status: ConfirmationStatus) -> str:
    """The same !ok or !nao again: nothing happened, and saying so is enough."""
    return f"{code} já estava {_STATUS[status]}. Nada mudou."


# -- reading the book ------------------------------------------------------------


def positions(summary: PositionSummary, *, members: Sequence[str], names: Names) -> str:
    return "\n".join(
        [
            f"Total gasto: {money(summary.total_spent_cents)}",
            *_position_lines(summary, members, names),
        ]
    )


def statement(lines: Sequence[StatementLine], *, names: Names) -> str:
    if not lines:
        return "Nenhum lançamento ainda."
    return "\n".join(_statement_line(line, names) for line in lines)


def settlement_plan(
    summary: PositionSummary,
    plan: Sequence[Transfer],
    declared: Sequence[DeclaredSettlement],
    *,
    settled: bool,
    members: Sequence[str],
    names: Names,
) -> str:
    """The !acerto: confirmed positions, the plan on projected ones, and what is
    still waiting for a payee's !ok."""
    if settled:
        return "Viagem quitada: ninguém deve nada."
    lines = _position_lines(summary, members, names)
    if plan:
        lines += ["", "Para zerar todo mundo:"]
        lines += [
            f"• {_name(names, t.payer_id)} paga {money(t.amount_cents)} a "
            f"{_name(names, t.payee_id)}"
            for t in plan
        ]
    else:
        lines += ["", "Nenhum pagamento novo é necessário."]
    if declared:
        lines += ["", "Aguardando confirmação:"]
        lines += [
            f"• pix de {money(d.amount_cents)} de {_name(names, d.payer_id)} para "
            f"{_name(names, d.payee_id)} (código {d.code})"
            for d in declared
        ]
    return "\n".join(lines)


# Examples instead of notation: the group reads "!gasto 45,90 pizza", not
# "<valor> <descrição> [dd/mm]". Every example must parse (a test checks it).
HELP = """Como usar:
!gasto 45,90 pizza — lança uma despesa dividida entre todos
!gasto 45,90 pizza 18/02 — o mesmo, com a data em que aconteceu
!pix @joao 40 — avisa que você pagou alguém (vale quando a pessoa confirmar)
!ok A7 — confirma (use o código que o bot mandar)
!nao A7 — recusa ou cancela
!estorna L5 — desfaz o lançamento L5
!saldo — total gasto e quanto cada um deve ou tem a receber
!extrato — os últimos 10 lançamentos (!extrato 20 para ver mais)
!acerto — quem paga quem para zerar tudo"""


def help_text() -> str:
    return HELP


def unknown_sender() -> str:
    return "Não sei quem é você. Peça para alguém do grupo te cadastrar."


def not_a_member() -> str:
    return "Você não faz parte desta viagem."


# -- what went wrong -------------------------------------------------------------

_EXAMPLES = {
    "!gasto": "!gasto 300 gasolina",
    "!pix": "!pix @lotti 40",
    "!ok": "!ok A7",
    "!nao": "!nao A7",
    "!estorna": "!estorna L5",
    "!extrato": "!extrato 20",
}


def _example(e: ParseError) -> str:
    example = _EXAMPLES.get(e.verb or "")
    return f" Exemplo: {example}" if example else ""


_PARSE_ERRORS: dict[ParseReason, Callable[[ParseError], str]] = {
    ParseReason.UNKNOWN_COMMAND: lambda e: (
        "Não entendi. Mande !ajuda para ver os comandos."
    ),
    ParseReason.UNEXPECTED_ARGUMENTS: lambda e: (
        f"Sobrou “{e.token}” no {e.verb}." + _example(e)
    ),
    ParseReason.MISSING_AMOUNT: lambda e: "Faltou o valor." + _example(e),
    ParseReason.INVALID_AMOUNT: lambda e: (
        f"Não entendi o valor “{e.token}”. Use 150, 150,50 ou 1.250,00."
    ),
    ParseReason.TOO_MANY_DECIMALS: lambda e: (
        f"“{e.token}” tem mais de duas casas decimais."
    ),
    ParseReason.NOT_POSITIVE_AMOUNT: lambda e: "O valor precisa ser maior que zero.",
    ParseReason.AMOUNT_TOO_LARGE: lambda e: (
        f"“{e.token}” passa do limite de {money(MAX_AMOUNT_CENTS)}. Confira o valor."
    ),
    ParseReason.MISSING_DESCRIPTION: lambda e: (
        "Faltou dizer com o que foi." + _example(e)
    ),
    ParseReason.INVALID_DATE: lambda e: (
        f"A data “{e.token}” não existe ou ainda não chegou. Use dd/mm, como 18/02."
    ),
    ParseReason.MISSING_PERSON: lambda e: "Faltou para quem." + _example(e),
    ParseReason.UNKNOWN_PERSON: lambda e: f"Não achei {e.token} nesta viagem.",
    ParseReason.AMBIGUOUS_PERSON: lambda e: (
        f"{e.token} serve para mais de uma pessoa. Use o apelido exato."
    ),
    ParseReason.MISSING_CODE: lambda e: "Faltou o código." + _example(e),
    ParseReason.INVALID_CODE: lambda e: (
        f"“{e.token}” não é um código. Os códigos têm uma letra e um número, como A7."
    ),
    ParseReason.MISSING_ENTRY: lambda e: "Faltou o lançamento." + _example(e),
    ParseReason.INVALID_ENTRY: lambda e: (
        f"“{e.token}” não é um lançamento. Use o número do !extrato, como L5."
    ),
    ParseReason.INVALID_LIMIT: lambda e: (
        f"Use um número de 1 a {STATEMENT_MAX_LIMIT}." + _example(e)
    ),
}


def parse_error(e: ParseError) -> str:
    return _PARSE_ERRORS[e.reason](e)


# Each function receives the refusal itself: its fields are the data to explain.
_REFUSALS: dict[RefusalReason, Callable[[Any, Names], str]] = {
    RefusalReason.NOT_POSITIVE_AMOUNT: lambda r, n: (
        "O valor precisa ser maior que zero."
    ),
    RefusalReason.SELF_PAYMENT: lambda r, n: "Não dá para mandar pix para você mesmo.",
    RefusalReason.EXCEEDS_DEBT: lambda r, n: (
        f"{_name(n, r.payer_id)} não deve nada no momento."
        if r.debt_cents == 0
        else f"{_name(n, r.payer_id)} deve {money(r.debt_cents)}, e o pix de "
        f"{money(r.amount_cents)} é maior que isso. Confira o valor."
    ),
    RefusalReason.PAYER_NOT_MEMBER: lambda r, n: (
        f"{_name(n, r.payer_id)} não faz parte desta viagem."
    ),
    RefusalReason.ALREADY_REVERSED: lambda r, n: (
        f"L{r.original_seq} já foi estornado por L{r.reversal_seq}. Para corrigir "
        "de novo, lance a despesa com o valor certo."
    ),
    RefusalReason.REVERSAL_OF_REVERSAL: lambda r, n: (
        f"L{r.seq} é o estorno de L{r.reverses_seq} e não pode ser estornado. "
        f"Para refazer L{r.reverses_seq}, lance a despesa de novo."
    ),
    RefusalReason.NOT_THE_CONFIRMER: lambda r, n: (
        f"Só {_name(n, r.confirmer)} pode confirmar isso."
    ),
    RefusalReason.NOT_A_PARTY: lambda r, n: (
        f"Só {_either([_name(n, p) for p in r.allowed])} pode recusar isso."
    ),
    RefusalReason.ALREADY_RESOLVED: lambda r, n: (
        f"Isso já foi {_STATUS[r.status]} e não muda mais."
    ),
    RefusalReason.SETTLEMENT_NEVER_EXPIRES: lambda r, n: (
        "Um pix declarado não expira: ele pode ser um pagamento de verdade."
    ),
    RefusalReason.ENTRY_NOT_FOUND: lambda r, n: (
        f"Não existe L{r.seq} nesta viagem. Veja os números no !extrato."
    ),
    RefusalReason.CONFIRMATION_NOT_FOUND: lambda r, n: (
        f"Não encontrei o código {r.code}."
    ),
    RefusalReason.NO_FREE_CODE: lambda r, n: (
        "Há pendências demais em aberto. Confirme ou cancele algumas antes de "
        "lançar mais."
    ),
}


def refusal(r: Refusal, *, names: Names) -> str:
    return _REFUSALS[r.reason](r, names)


# -- helpers ---------------------------------------------------------------------


def _position_lines(
    summary: PositionSummary, members: Sequence[str], names: Names
) -> list[str]:
    by_id = {p.participant_id: p.position_cents for p in summary.participants}
    lines = []
    for pid in sorted(members):
        cents = by_id.get(pid, 0)
        if cents > 0:
            state = f"a receber {money(cents)}"
        elif cents < 0:
            state = f"deve {money(-cents)}"
        else:
            state = "quite"
        lines.append(f"{_name(names, pid)}: {state}")
    return lines


def _payers(line: StatementLine, names: Names) -> str:
    return " e ".join(_name(names, p) for p in line.paid_by)


def _what(line: StatementLine, names: Names) -> str:
    """What an entry was, for naming it: the expense, or the payment."""
    if line.transfer is not None:
        t = line.transfer
        return (
            f"pix de {money(abs(t.amount_cents))} de {_name(names, t.payer_id)} "
            f"para {_name(names, t.payee_id)}"
        )
    return f"{line.description}, {money(abs(line.total_cents))}"


def _statement_line(line: StatementLine, names: Names) -> str:
    when = day(line.occurred_on)
    if line.kind is EntryKind.REVERSAL:
        shown = line.transfer.amount_cents if line.transfer else line.total_cents
        text = f"L{line.seq}  {when}  estorno de L{line.reverses} ({_what(line, names)})  {money(shown)}"
    elif line.transfer is not None:
        text = f"L{line.seq}  {when}  {_what(line, names)}"
    else:
        text = (
            f"L{line.seq}  {when}  {line.description}  {money(line.total_cents)}  "
            f"pago por {_payers(line, names)}"
        )
    if line.reversed_by is not None:
        text += f"  (estornado por L{line.reversed_by})"
    return text
