"""The core: one inbound message in, its command acted on, one reply out.

Everything a message causes is written in one transaction: the command, its
ledger effects, the reply in the outbox, and processed_at. Either all of it
happened or none did and the message will be processed again. At-least-once
delivery plus that, plus the idempotency gates, is exactly-once in effect.

A Refusal is an answer: the store's own transaction blocks are savepoints inside
this one, so a refusal undoes only its step, the command stays recorded, and the
reply explains. Anything else is a bug: the whole transaction is undone, the
exception propagates, and the message stays unprocessed.

The connection must be in autocommit mode, so that each message's
`conn.transaction()` is a real transaction that commits on its own; inside an
already open transaction psycopg only manages a savepoint.
"""

import random
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg

from channel import messages
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
from channel.grammar import Member, ParseError, parse
from channel.inbound import sender_key, text_of
from ledger.positions import position_summary, positions, projected_positions
from ledger.refusal import Refusal
from ledger.settlement_plan import book_settled, settlement_plan
from ledger.statement import StatementLine, statement
from ledger.workflow import Action, ConfirmationKind, ConfirmationStatus
from store import books, inbox
from store.confirmations import (
    Resolution,
    declare_settlement,
    declared_settlements,
    propose_expense,
    propose_reversal,
    resolve,
)
from store.ledger import book_entries, book_postings

# The business date is Sao Paulo's: an expense at 23:30 there is already the next
# day in UTC, and belongs to the day the person lived it.
BUSINESS_TZ = ZoneInfo("America/Sao_Paulo")


def business_date(at: datetime) -> date:
    return at.astimezone(BUSINESS_TZ).date()


def process_pending(conn: psycopg.Connection, *, rng: random.Random) -> int:
    """Process unprocessed messages oldest first, one transaction each, until
    none is left. Returns how many were processed. Stops at the first bug."""
    count = 0
    while True:
        with conn.transaction():
            inbound_id = inbox.next_pending(conn)
            if inbound_id is None:
                return count
            _process(conn, inbound_id, rng)
        count += 1


def process(conn: psycopg.Connection, inbound_id: UUID, *, rng: random.Random) -> bool:
    """Process one message in its own transaction. False if it was already
    processed: nothing is written twice."""
    with conn.transaction():
        return _process(conn, inbound_id, rng)


@dataclass(frozen=True)
class _Context:
    message: inbox.Inbound
    book_id: UUID
    author_id: str
    members: list[Member]
    names: dict[str, str]
    today: date
    rng: random.Random


def _process(conn: psycopg.Connection, inbound_id: UUID, rng: random.Random) -> bool:
    message = inbox.lock_unprocessed(conn, inbound_id)
    if message is None:
        return False
    conversation = books.conversation_book(
        conn, message.channel, message.conversation_external_id
    )
    if conversation is not None:
        conversation_id, book_id = conversation
        body = _reply(conn, message, book_id, rng)
        inbox.enqueue_reply(
            conn, conversation_id=conversation_id, inbound_id=message.id, body=body
        )
    # An unknown chat has nowhere to be answered: processed, in silence.
    inbox.mark_processed(conn, message.id)
    return True


def _reply(
    conn: psycopg.Connection, message: inbox.Inbound, book_id: UUID, rng: random.Random
) -> str:
    author_id = books.participant_for(
        conn, message.channel, sender_key(message.channel, message.sender_external_id)
    )
    if author_id is None:
        return messages.unknown_sender()
    members = [Member(pid, name) for pid, name in books.member_names(conn, book_id)]
    if author_id not in {m.participant_id for m in members}:
        return messages.not_a_member()

    today = business_date(message.received_at)
    parsed = parse(
        text_of(
            message.channel,
            message.raw_payload,
            books.identities(conn, message.channel),
        ),
        members=members,
        today=today,
    )
    if isinstance(parsed, ParseError):
        return messages.parse_error(parsed)

    ctx = _Context(
        message,
        book_id,
        author_id,
        members,
        {m.participant_id: m.display_name for m in members},
        today,
        rng,
    )
    command_id = inbox.record_command(
        conn,
        inbound_id=message.id,
        book_id=book_id,
        participant_id=author_id,
        kind=parsed.kind.value,
        payload=parsed.payload(),
    )
    try:
        return _execute(conn, parsed, command_id, ctx)
    except Refusal as refused:
        return messages.refusal(refused, names=ctx.names)


def _execute(
    conn: psycopg.Connection, command: Command, command_id: UUID, ctx: _Context
) -> str:
    names = ctx.names
    match command:
        case RecordExpense(amount_cents, description, occurred_on):
            proposal = propose_expense(
                conn,
                book_id=ctx.book_id,
                command_id=command_id,
                payer_id=ctx.author_id,
                total_cents=amount_cents,
                description=description,
                occurred_on=occurred_on,
                at=ctx.message.received_at,
                rng=ctx.rng,
            )
            return messages.expense_proposed(
                author_id=ctx.author_id,
                amount_cents=amount_cents,
                description=description,
                occurred_on=occurred_on,
                members=len(ctx.members),
                code=proposal.code,
                warnings=proposal.warnings,
                at=ctx.message.received_at,
                names=names,
            )
        case DeclareSettlement(payee_id, amount_cents):
            proposal = declare_settlement(
                conn,
                book_id=ctx.book_id,
                command_id=command_id,
                payer_id=ctx.author_id,
                payee_id=payee_id,
                amount_cents=amount_cents,
                declared_on=ctx.today,
                rng=ctx.rng,
            )
            return messages.settlement_declared(
                payer_id=ctx.author_id,
                payee_id=payee_id,
                amount_cents=amount_cents,
                code=proposal.code,
                names=names,
            )
        case Confirm(code) | Reject(code):
            action = Action.CONFIRM if isinstance(command, Confirm) else Action.DECLINE
            resolution = resolve(
                conn, book_id=ctx.book_id, code=code, action=action, actor=ctx.author_id
            )
            return _resolved(conn, resolution, code, ctx)
        case Reverse(seq):
            proposal = propose_reversal(
                conn,
                book_id=ctx.book_id,
                command_id=command_id,
                target_seq=seq,
                author_id=ctx.author_id,
                rng=ctx.rng,
            )
            return messages.reversal_proposed(
                target=_line(conn, ctx.book_id, seq), code=proposal.code, names=names
            )
        case ShowPosition():
            return messages.positions(
                position_summary(book_postings(conn, ctx.book_id)),
                members=list(names),
                names=names,
            )
        case ShowStatement(limit):
            lines = statement(book_entries(conn, ctx.book_id))
            return messages.statement(lines[-limit:], names=names)
        case ShowSettlementPlan():
            postings = book_postings(conn, ctx.book_id)
            declared = declared_settlements(conn, ctx.book_id)
            return messages.settlement_plan(
                position_summary(postings),
                settlement_plan(projected_positions(postings, declared)),
                declared,
                settled=book_settled(positions(postings), declared),
                members=list(names),
                names=names,
            )
        case Help():
            return messages.help_text()
    raise TypeError(f"unhandled command {command!r}")


def _resolved(
    conn: psycopg.Connection, resolution: Resolution, code: str, ctx: _Context
) -> str:
    if not resolution.changed:
        return messages.unchanged(code, resolution.status)
    if resolution.entry is not None:
        return messages.entry_recorded(
            _line(conn, ctx.book_id, resolution.entry.seq),
            breaks=resolution.breaks,
            names=ctx.names,
        )
    if (
        resolution.status is ConfirmationStatus.DISCARDED
        and resolution.kind is ConfirmationKind.SETTLEMENT_DECLARATION
    ):
        payload = resolution.payload
        if ctx.author_id == payload["payee_id"]:
            return messages.settlement_rejected(
                payer_id=payload["payer_id"],
                payee_id=payload["payee_id"],
                amount_cents=payload["amount_cents"],
                code=code,
                names=ctx.names,
            )
        return messages.settlement_cancelled(
            payer_id=payload["payer_id"],
            amount_cents=payload["amount_cents"],
            code=code,
            names=ctx.names,
        )
    return messages.proposal_discarded(code)


def _line(conn: psycopg.Connection, book_id: UUID, seq: int) -> StatementLine:
    return next(
        line for line in statement(book_entries(conn, book_id)) if line.seq == seq
    )
