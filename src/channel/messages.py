"""Every message the bot sends, in Portuguese. The only module with Portuguese.

Pure functions from domain objects to text: no database, no clock. The domain
knows participant ids; `names` maps them to display names here, at the edge.

Written to be read on a phone, in a WhatsApp group:

- the first line says what happened, in bold, with one emoji for its kind;
- a blank line separates what happened from what to do;
- a command the reader has to send sits alone on its line, in bold, exactly as
  it is typed;
- only formatting every WhatsApp version shows: *bold*, _italic_, line breaks.
  Lists use a plain "•". (Other channels show the asterisks as they are.)

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


def _blocks(*blocks: Sequence[str]) -> str:
    """Blocks of lines, a blank line between them; empty blocks are dropped."""
    return "\n\n".join("\n".join(block) for block in blocks if block)


def _send(command: str) -> str:
    """A command for the reader to send: alone on its line, in bold."""
    return f"*{command}*"


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
    return _blocks(
        [
            "🧾 *Nova despesa*",
            (
                f"{_name(names, author_id)} pagou *{money(amount_cents)}* de "
                f"{description} ({day(occurred_on)})"
            ),
            f"Dividido entre {members} {'pessoa' if members == 1 else 'pessoas'}",
        ],
        ["Para confirmar, mande:", _send(f"!ok {code}")],
        ["Para cancelar, mande:", _send(f"!nao {code}")],
        *([warning(w, at)] for w in warnings),
    )


def warning(w: ProposalWarning, at: datetime) -> str:
    if isinstance(w, IntentDuplicate):
        minutes = int((at - w.previous_at).total_seconds() // 60)
        when = "há menos de 1 min" if minutes < 1 else f"há {minutes} min"
        return (
            "⚠️ *Parece repetido*\n"
            f"Você lançou o mesmo valor e a mesma descrição {when} "
            f"(código {w.previous_code}).\n"
            "Se for outro gasto, confirme normalmente."
        )
    if isinstance(w, OutsideBookDates):
        return (
            "⚠️ *Data fora da viagem*\n"
            f"A data {day(w.occurred_on)} não está entre {day(w.starts_on)} e "
            f"{day(w.ends_on)}.\n"
            "Se estiver certa, confirme normalmente."
        )
    raise TypeError(f"unknown warning {w!r}")


def settlement_declared(
    *, payer_id: str, payee_id: str, amount_cents: int, code: str, names: Names
) -> str:
    payee = _name(names, payee_id)
    return _blocks(
        [
            "💸 *Pix informado*",
            f"{_name(names, payer_id)} diz que mandou *{money(amount_cents)}* para {payee}",
        ],
        [f"{payee}, se o dinheiro chegou, mande:", _send(f"!ok {code}")],
        ["Se não chegou, mande:", _send(f"!nao {code}")],
    )


def reversal_proposed(*, target: StatementLine, code: str, names: Names) -> str:
    return _blocks(
        ["↩️ *Desfazer lançamento*", f"L{target.seq} · {_what(target, names)}"],
        ["Para confirmar, mande:", _send(f"!ok {code}")],
        ["Para desistir, mande:", _send(f"!nao {code}")],
    )


# -- resolutions -----------------------------------------------------------------


def entry_recorded(
    line: StatementLine, *, breaks: Sequence[Break] = (), names: Names
) -> str:
    """The !ok that turned a proposal into an entry."""
    if line.kind is EntryKind.REVERSAL:
        head = f"✅ *Desfeito: L{line.reverses}*"
        detail = f"{_what(line, names)} · registrado como L{line.seq}"
    elif line.transfer is not None:
        t = line.transfer
        head = f"✅ *Pix confirmado: L{line.seq}*"
        detail = (
            f"{_name(names, t.payer_id)} pagou {money(t.amount_cents)} a "
            f"{_name(names, t.payee_id)}"
        )
    else:
        head = f"✅ *Registrado: L{line.seq}*"
        detail = (
            f"{line.description} · {money(line.total_cents)} · "
            f"pago por {_payers(line, names)}"
        )
    return _blocks([head, detail], *([overpayment(b, names)] for b in breaks))


def overpayment(b: Break, names: Names) -> str:
    """Break 7: reported, never blocking. A positive payer or a negative payee."""
    who = _name(names, b.participant_id)
    if b.position_cents > 0:
        return (
            "⚠️ *Pagou a mais*\n"
            f"Com esse pix, {who} pagou {money(b.position_cents)} a mais do que devia."
        )
    return (
        "⚠️ *Recebeu a mais*\n"
        f"Com esse pix, {who} recebeu {money(-b.position_cents)} a mais "
        "do que tinha a receber."
    )


def proposal_discarded(code: str) -> str:
    return f"❌ *{code} cancelado*\nNada foi registrado."


def settlement_rejected(
    *, payer_id: str, payee_id: str, amount_cents: int, code: str, names: Names
) -> str:
    return (
        "❌ *Pix não chegou*\n"
        f"{_name(names, payee_id)} disse que os {money(amount_cents)} de "
        f"{_name(names, payer_id)} não chegaram ({code}).\n"
        "Nada foi registrado."
    )


def settlement_cancelled(
    *, payer_id: str, amount_cents: int, code: str, names: Names
) -> str:
    return (
        "❌ *Pix cancelado*\n"
        f"{_name(names, payer_id)} cancelou o pix de {money(amount_cents)} ({code}).\n"
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
    return _blocks(
        ["💰 *Saldo*", f"Total gasto: *{money(summary.total_spent_cents)}*"],
        _position_lines(summary, members, names),
    )


def statement(lines: Sequence[StatementLine], *, names: Names) -> str:
    if not lines:
        return "📋 *Últimos lançamentos*\nNenhum lançamento ainda."
    return _blocks(
        ["📋 *Últimos lançamentos*"], *(_statement_line(line, names) for line in lines)
    )


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
        return "🤝 *Acerto*\nViagem quitada: ninguém deve nada. 🎉"
    transfers = (
        [
            "*Para zerar todo mundo*",
            *(
                f"• {_name(names, t.payer_id)} paga *{money(t.amount_cents)}* a "
                f"{_name(names, t.payee_id)}"
                for t in plan
            ),
        ]
        if plan
        else ["*Para zerar todo mundo*", "Nenhum pagamento novo é necessário."]
    )
    pending = (
        [
            "*Aguardando confirmação*",
            *(
                f"• Pix de {money(d.amount_cents)} de {_name(names, d.payer_id)} para "
                f"{_name(names, d.payee_id)} (código {d.code})"
                for d in declared
            ),
        ]
        if declared
        else []
    )
    return _blocks(
        ["🤝 *Acerto*"],
        ["*Quem deve e quem recebe*", *_position_lines(summary, members, names)],
        transfers,
        pending,
    )


# Examples instead of notation: the group reads "!gasto 45,90 pizza", not
# "<valor> <descrição> [dd/mm]". Every line starting with "!" must parse (a
# test checks it), up to " ou " or " · ".
HELP = """👋 *Como usar o bot*

*Lançar uma despesa*
!gasto 45,90 pizza
Com outra data:
!gasto 45,90 pizza 18/02

*Avisar que pagou alguém*
!pix @joao 40
Vale quando a pessoa confirmar.

*Confirmar ou cancelar*
!ok A7 ou !nao A7
Use o código que o bot mandar.

*Desfazer um lançamento*
!estorna L5

*Consultar*
!saldo · quanto cada um deve ou recebe
!extrato · os últimos lançamentos
!acerto · quem paga quem para zerar tudo"""


def help_text() -> str:
    return HELP


def unknown_sender() -> str:
    return "Não sei quem é você. Peça para alguém do grupo te cadastrar."


def not_a_member() -> str:
    return "Você não faz parte desta viagem."


# -- what went wrong -------------------------------------------------------------

_EXAMPLES = {
    "!gasto": "!gasto 45,90 pizza",
    "!pix": "!pix @joao 40",
    "!ok": "!ok A7",
    "!nao": "!nao A7",
    "!estorna": "!estorna L5",
    "!extrato": "!extrato 20",
}


def _example(e: ParseError) -> str:
    example = _EXAMPLES.get(e.verb or "")
    return f"\nExemplo: {_send(example)}" if example else ""


_PARSE_ERRORS: dict[ParseReason, Callable[[ParseError], str]] = {
    ParseReason.UNKNOWN_COMMAND: lambda e: (
        f"Não entendi. Para ver os comandos, mande:\n{_send('!ajuda')}"
    ),
    ParseReason.UNEXPECTED_ARGUMENTS: lambda e: (
        f"Sobrou “{e.token}” no {e.verb}." + _example(e)
    ),
    ParseReason.MISSING_AMOUNT: lambda e: "Faltou o valor." + _example(e),
    ParseReason.INVALID_AMOUNT: lambda e: (
        f"Não entendi o valor “{e.token}”." + _example(e)
    ),
    ParseReason.TOO_MANY_DECIMALS: lambda e: (
        f"“{e.token}” tem mais de duas casas decimais." + _example(e)
    ),
    ParseReason.NOT_POSITIVE_AMOUNT: lambda e: "O valor precisa ser maior que zero.",
    ParseReason.AMOUNT_TOO_LARGE: lambda e: (
        f"“{e.token}” passa do limite de {money(MAX_AMOUNT_CENTS)}. Confira o valor."
    ),
    ParseReason.MISSING_DESCRIPTION: lambda e: (
        "Faltou dizer com o que foi." + _example(e)
    ),
    ParseReason.INVALID_DATE: lambda e: (
        f"A data “{e.token}” não existe ou ainda não chegou.\n"
        f"Use dia/mês, como {_send('!gasto 45,90 pizza 18/02')}"
    ),
    ParseReason.MISSING_PERSON: lambda e: "Faltou para quem." + _example(e),
    ParseReason.UNKNOWN_PERSON: lambda e: f"Não achei {e.token} nesta viagem.",
    ParseReason.AMBIGUOUS_PERSON: lambda e: (
        f"{e.token} serve para mais de uma pessoa. Use o apelido exato."
    ),
    ParseReason.MISSING_CODE: lambda e: "Faltou o código." + _example(e),
    ParseReason.INVALID_CODE: lambda e: (
        f"“{e.token}” não é um código. Os códigos têm uma letra e um número."
        + _example(e)
    ),
    ParseReason.MISSING_ENTRY: lambda e: "Faltou o lançamento." + _example(e),
    ParseReason.INVALID_ENTRY: lambda e: (
        f"“{e.token}” não é um lançamento. Use o número do !extrato." + _example(e)
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
        f"{money(r.amount_cents)} é maior que isso.\nConfira o valor."
    ),
    RefusalReason.PAYER_NOT_MEMBER: lambda r, n: (
        f"{_name(n, r.payer_id)} não faz parte desta viagem."
    ),
    RefusalReason.ALREADY_REVERSED: lambda r, n: (
        f"L{r.original_seq} já foi desfeito pelo L{r.reversal_seq}.\n"
        "Para corrigir de novo, lance a despesa com o valor certo."
    ),
    RefusalReason.REVERSAL_OF_REVERSAL: lambda r, n: (
        f"L{r.seq} já desfaz o L{r.reverses_seq} e não pode ser desfeito.\n"
        f"Para refazer o L{r.reverses_seq}, lance a despesa de novo."
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
        "Um pix informado não expira: ele pode ser um pagamento de verdade."
    ),
    RefusalReason.ENTRY_NOT_FOUND: lambda r, n: (
        f"Não existe L{r.seq} nesta viagem. Veja os números no !extrato."
    ),
    RefusalReason.CONFIRMATION_NOT_FOUND: lambda r, n: (
        f"Não encontrei o código {r.code}."
    ),
    RefusalReason.NO_FREE_CODE: lambda r, n: (
        "Há pendências demais em aberto.\n"
        "Confirme ou cancele algumas antes de lançar mais."
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
            state = f"recebe {money(cents)}"
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
    return f"{line.description} · {money(abs(line.total_cents))}"


def _statement_line(line: StatementLine, names: Names) -> list[str]:
    """One entry as two or three short lines."""
    head = f"*L{line.seq}* · {day(line.occurred_on)}"
    if line.kind is EntryKind.REVERSAL:
        shown = line.transfer.amount_cents if line.transfer else line.total_cents
        what = line.description or "pix"
        block = [f"{head} · desfaz o L{line.reverses} ({what})", money(shown)]
    elif line.transfer is not None:
        t = line.transfer
        block = [
            f"{head} · pix de {_name(names, t.payer_id)} para {_name(names, t.payee_id)}",
            money(t.amount_cents),
        ]
    else:
        block = [
            f"{head} · {line.description}",
            f"{money(line.total_cents)} · pago por {_payers(line, names)}",
        ]
    if line.reversed_by is not None:
        block.append(f"_desfeito pelo L{line.reversed_by}_")
    return block
