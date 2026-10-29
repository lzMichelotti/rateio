"""The confirmation workflow in SQL: propose, then resolve with !ok or !nao.

Every financial fact goes command -> open confirmation -> !ok -> entry. A
settlement is the same mechanism with the payee as confirmer.

confirmation and settlement are workflow state, updated in place. Their updates
are conditional (`WHERE status = 'open'`) and the affected row count says who
won: 1 means this call resolved it, 0 means someone else did first.
"""

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg import errors
from psycopg.types.json import Jsonb

from ledger.breaks import (
    DUPLICATE_WINDOW,
    Break,
    ExpenseIntent,
    ProposalWarning,
    overpayment_breaks,
    proposal_warnings,
)
from ledger.expense import record_expense
from ledger.model import Entry
from ledger.positions import positions
from ledger.refusal import Refusal, RefusalReason
from ledger.reversal import reverse
from ledger.settlement import (
    DeclaredSettlement,
    record_settlement,
    validate_declaration,
)
from ledger.workflow import (
    Action,
    ConfirmationKind,
    ConfirmationStatus,
    SettlementStatus,
    transition_confirmation,
    transition_settlement,
)
from store.books import book_members
from store.ledger import (
    EntryNotFoundError,
    RecordedEntry,
    append_entry,
    book_entries,
    book_postings,
)

# One letter and one digit, without the ambiguous I, L, O, 0 and 1: 23 x 8 = 184.
LETTERS = "ABCDEFGHJKMNPQRSTUVWXYZ"
DIGITS = "23456789"
ALL_CODES = tuple(letter + digit for letter in LETTERS for digit in DIGITS)

# A code resolved this recently is not handed out again, so a repeated !ok A7
# cannot land on a new confirmation that just received the recycled A7.
RECENTLY_RESOLVED = "24 hours"
MAX_CODE_ATTEMPTS = 5


class NoFreeCodeError(Refusal):
    """Every code is open or recently resolved in this book: too much is pending."""

    reason = RefusalReason.NO_FREE_CODE

    def __init__(self, book_id: UUID) -> None:
        self.book_id = book_id
        super().__init__(f"no free confirmation code in book {book_id}")


class ConfirmationNotFoundError(Refusal, LookupError):
    reason = RefusalReason.CONFIRMATION_NOT_FOUND

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"no confirmation {code} in this book")


class ResolvedConcurrentlyError(RuntimeError):
    """Someone else resolved this confirmation between our read and our update.
    The transaction is rolled back; their resolution stands."""


@dataclass(frozen=True)
class Proposal:
    confirmation_id: UUID
    code: str
    created: bool  # False: the proposing command was seen before
    # Breaks 1 and 4 for a new expense proposal: reported, never blocking.
    warnings: tuple[ProposalWarning, ...] = ()


@dataclass(frozen=True)
class Resolution:
    confirmation_id: UUID
    status: ConfirmationStatus
    changed: bool  # False: the same action repeated, nothing happened
    # What was resolved, as proposed, so the reply can describe it without a
    # second lookup by code that could land on a recycled one.
    kind: ConfirmationKind
    payload: Mapping[str, Any]
    entry: RecordedEntry | None = None
    breaks: tuple[Break, ...] = ()


def propose(
    conn: psycopg.Connection,
    *,
    book_id: UUID,
    command_id: UUID,
    kind: ConfirmationKind,
    created_by: str,
    confirmer: str,
    payload: Mapping[str, Any],
    rng: random.Random,
) -> Proposal:
    """Open a confirmation for a proposing command, with a fresh two-character code.

    Idempotent: the same command proposed again returns its existing
    confirmation. payload holds everything the !ok needs to build the entry, so
    what gets confirmed is exactly what was proposed.
    """
    with conn.transaction():
        _lock_book(conn, book_id)
        return _insert_confirmation(
            conn, book_id, command_id, kind, created_by, confirmer, payload, rng
        )


def propose_expense(
    conn: psycopg.Connection,
    *,
    book_id: UUID,
    command_id: UUID,
    payer_id: str,
    total_cents: int,
    description: str,
    occurred_on: date,
    at: datetime,
    rng: random.Random,
) -> Proposal:
    """A !gasto: open the author's own confirmation for an expense, split among
    the book's members, with breaks 1 and 4 attached as warnings.

    The members are captured now, so the !ok confirms exactly what was proposed
    even if someone joins meanwhile. The expense is built once here only to
    validate it. at is when the message was sent; it becomes the confirmation's
    created_at, the time break 1 compares, because the database clock is frozen
    for the whole transaction and the domain never reads a clock.
    """
    with conn.transaction():
        starts_on, ends_on = _lock_book(conn, book_id)
        # A redelivered command answers in silence before any validation.
        existing = _existing_proposal(conn, command_id)
        if existing is not None:
            return existing
        ids = book_members(conn, book_id)
        record_expense(
            seq=1,
            occurred_on=occurred_on,
            payer_id=payer_id,
            total_cents=total_cents,
            description=description,
            participant_ids=ids,
        )
        warnings = proposal_warnings(
            ExpenseIntent(payer_id, total_cents, description, at),
            _live_expense_proposals(conn, book_id, payer_id, at),
            occurred_on=occurred_on,
            starts_on=starts_on,
            ends_on=ends_on,
        )
        proposal = _insert_confirmation(
            conn,
            book_id,
            command_id,
            ConfirmationKind.EXPENSE_PROPOSAL,
            created_by=payer_id,
            confirmer=payer_id,
            payload={
                "payer_id": payer_id,
                "total_cents": total_cents,
                "description": description,
                "occurred_on": occurred_on.isoformat(),
                "participant_ids": ids,
            },
            rng=rng,
            created_at=at,
        )
        return replace(proposal, warnings=warnings)


def propose_reversal(
    conn: psycopg.Connection,
    *,
    book_id: UUID,
    command_id: UUID,
    target_seq: int,
    author_id: str,
    rng: random.Random,
) -> Proposal:
    """A !estorna L<n>: refuse now what is already impossible (no such entry in this
    book, a reversal, an already reversed entry), then open the author's own
    confirmation. The !ok checks again, since the book may change meanwhile."""
    with conn.transaction():
        _lock_book(conn, book_id)
        # A redelivered command answers in silence before any validation: by now
        # its own reversal may be what makes the check fail.
        existing = _existing_proposal(conn, command_id)
        if existing is not None:
            return existing
        _reversal_of(conn, book_id, target_seq, author_id, seq=0)
        return _insert_confirmation(
            conn,
            book_id,
            command_id,
            ConfirmationKind.REVERSAL_PROPOSAL,
            created_by=author_id,
            confirmer=author_id,
            payload={"target_seq": target_seq},
            rng=rng,
        )


def declare_settlement(
    conn: psycopg.Connection,
    *,
    book_id: UUID,
    command_id: UUID,
    payer_id: str,
    payee_id: str,
    amount_cents: int,
    declared_on: date,
    rng: random.Random,
) -> Proposal:
    """A !pix: validate against current positions, open the payee's confirmation
    and the settlement row. Changes no position: the ledger learns nothing until
    the payee confirms."""
    with conn.transaction():
        _lock_book(conn, book_id)
        # A redelivered !pix answers in silence before validation: positions may
        # have moved since, and the declaration was valid when it was made.
        existing = _existing_proposal(conn, command_id)
        if existing is not None:
            return existing
        validate_declaration(
            positions(book_postings(conn, book_id)),
            payer_id=payer_id,
            payee_id=payee_id,
            amount_cents=amount_cents,
        )
        proposal = _insert_confirmation(
            conn,
            book_id,
            command_id,
            ConfirmationKind.SETTLEMENT_DECLARATION,
            created_by=payer_id,
            confirmer=payee_id,
            payload={
                "payer_id": payer_id,
                "payee_id": payee_id,
                "amount_cents": amount_cents,
                "declared_on": declared_on.isoformat(),
            },
            rng=rng,
        )
        if proposal.created:
            conn.execute(
                """
                INSERT INTO settlement
                    (book_id, payer_id, payee_id, amount_cents, confirmation_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (book_id, payer_id, payee_id, amount_cents, proposal.confirmation_id),
            )
        return proposal


def resolve(
    conn: psycopg.Connection,
    *,
    book_id: UUID,
    code: str,
    action: Action,
    actor: str | None,
) -> Resolution:
    """Apply !ok, !nao or expiry to the confirmation with this code, in one
    transaction.

    The state machines decide; this carries it out. On !ok the entry is written
    with the proposing command and linked both ways; for a settlement, the
    overpayment check runs on the positions after it, and is reported, never
    blocking.
    """
    with conn.transaction():
        row = conn.execute(
            """
            SELECT id, kind, status, command_id, created_by, confirmer, payload
            FROM confirmation
            WHERE book_id = %s AND code = %s
            ORDER BY status = 'open' DESC, resolved_at DESC
            LIMIT 1
            """,
            (book_id, code),
        ).fetchone()
        if row is None:
            raise ConfirmationNotFoundError(code)
        confirmation_id, kind, status, command_id, created_by, confirmer, payload = row
        kind, status = ConfirmationKind(kind), ConfirmationStatus(status)

        transition = transition_confirmation(
            kind,
            status,
            action,
            actor=actor,
            created_by=created_by,
            confirmer=confirmer,
        )
        settlement = None
        if kind is ConfirmationKind.SETTLEMENT_DECLARATION:
            settlement = transition_settlement(
                SettlementStatus(
                    conn.execute(
                        "SELECT status FROM settlement WHERE confirmation_id = %s",
                        (confirmation_id,),
                    ).fetchone()[0]
                ),
                action,
                actor=actor,
                payer_id=payload["payer_id"],
                payee_id=payload["payee_id"],
            )

        if not transition.changed:
            return Resolution(
                confirmation_id,
                transition.status,
                changed=False,
                kind=kind,
                payload=payload,
            )

        entry = None
        breaks: tuple[Break, ...] = ()
        if transition.status is ConfirmationStatus.CONFIRMED:
            # The entry first: a confirmed confirmation must point at an existing
            # entry. Same transaction, so a lost race below undoes it too.
            entry = append_entry(
                conn,
                book_id=book_id,
                command_id=command_id,
                build=_builder(conn, book_id, kind, payload, created_by),
                confirmation_id=confirmation_id,
            )

        updated = conn.execute(
            """
            UPDATE confirmation
            SET status = %s, resolved_at = now(), entry_id = %s
            WHERE id = %s AND status = 'open'
            """,
            (
                transition.status.value,
                entry.entry_id if entry else None,
                confirmation_id,
            ),
        ).rowcount
        if updated != 1:
            raise ResolvedConcurrentlyError(
                f"confirmation {code} was resolved meanwhile"
            )

        if settlement is not None:
            conn.execute(
                """
                UPDATE settlement
                SET status = %s,
                    entry_id = %s,
                    confirmed_at = CASE WHEN %s THEN now() END
                WHERE confirmation_id = %s AND status = 'declared'
                """,
                (
                    settlement.status.value,
                    entry.entry_id if entry else None,
                    entry is not None,
                    confirmation_id,
                ),
            )
            if entry is not None:
                breaks = tuple(
                    overpayment_breaks(
                        positions(book_postings(conn, book_id)),
                        payer_id=payload["payer_id"],
                        payee_id=payload["payee_id"],
                    )
                )

        return Resolution(
            confirmation_id, transition.status, True, kind, payload, entry, breaks
        )


def declared_settlements(
    conn: psycopg.Connection, book_id: UUID
) -> list[DeclaredSettlement]:
    """Every payment in this book still waiting for the payee's !ok, oldest first.

    Read for the settlement plan's projection and its pending list; never an
    input to positions(). declared_on is the business date from the proposal,
    the one the entry would carry, not the database clock's declared_at.
    """
    rows = conn.execute(
        """
        SELECT c.code, s.payer_id, s.payee_id, s.amount_cents,
               c.payload ->> 'declared_on'
        FROM settlement s
        JOIN confirmation c ON c.id = s.confirmation_id
        WHERE s.book_id = %s AND s.status = 'declared'
        ORDER BY s.declared_at, c.code
        """,
        (book_id,),
    ).fetchall()
    return [
        DeclaredSettlement(
            code=code,
            payer_id=payer_id,
            payee_id=payee_id,
            amount_cents=amount_cents,
            declared_on=date.fromisoformat(declared_on),
        )
        for code, payer_id, payee_id, amount_cents, declared_on in rows
    ]


def pick_code(conn: psycopg.Connection, book_id: UUID, rng: random.Random) -> str:
    """A random code that is neither open nor recently resolved in this book."""
    taken = {
        code
        for (code,) in conn.execute(
            """
            SELECT code FROM confirmation
            WHERE book_id = %s
              AND (status = 'open' OR resolved_at > now() - %s::interval)
            """,
            (book_id, RECENTLY_RESOLVED),
        )
    }
    free = [code for code in ALL_CODES if code not in taken]
    if not free:
        raise NoFreeCodeError(book_id)
    return rng.choice(free)


def _existing_proposal(conn: psycopg.Connection, command_id: UUID) -> Proposal | None:
    row = conn.execute(
        "SELECT id, code FROM confirmation WHERE command_id = %s", (command_id,)
    ).fetchone()
    return None if row is None else Proposal(row[0], row[1], created=False)


def _insert_confirmation(
    conn: psycopg.Connection,
    book_id: UUID,
    command_id: UUID,
    kind: ConfirmationKind,
    created_by: str,
    confirmer: str,
    payload: Mapping[str, Any],
    rng: random.Random,
    created_at: datetime | None = None,
) -> Proposal:
    existing = _existing_proposal(conn, command_id)
    if existing is not None:
        return existing

    for _ in range(MAX_CODE_ATTEMPTS):
        code = pick_code(conn, book_id, rng)
        try:
            # A savepoint per attempt: a unique violation aborts only this insert.
            with conn.transaction():
                row = conn.execute(
                    """
                    INSERT INTO confirmation
                        (code, book_id, command_id, kind, payload, created_by,
                         confirmer, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, coalesce(%s, now()))
                    ON CONFLICT (command_id) DO NOTHING
                    RETURNING id
                    """,
                    (
                        code,
                        book_id,
                        command_id,
                        kind.value,
                        Jsonb(dict(payload)),
                        created_by,
                        confirmer,
                        created_at,
                    ),
                ).fetchone()
        except errors.UniqueViolation as violation:
            if violation.diag.constraint_name != "confirmation_open_code":
                raise
            continue  # the code was taken meanwhile: draw another
        if row is None:  # the same command was proposed meanwhile
            existing = conn.execute(
                "SELECT id, code FROM confirmation WHERE command_id = %s", (command_id,)
            ).fetchone()
            return Proposal(existing[0], existing[1], created=False)
        return Proposal(row[0], code, created=True)
    raise NoFreeCodeError(book_id)


def _builder(
    conn: psycopg.Connection,
    book_id: UUID,
    kind: ConfirmationKind,
    payload: Mapping[str, Any],
    author_id: str,
) -> Callable[[int], Entry]:
    """The domain function that turns a confirmed proposal into an entry.

    It runs inside append_entry's transaction, after the book is locked, so a
    reversal re-checks the book as it is at the moment of confirming.
    """
    if kind is ConfirmationKind.SETTLEMENT_DECLARATION:
        return lambda seq: record_settlement(
            seq=seq,
            declared_on=date.fromisoformat(payload["declared_on"]),
            payer_id=payload["payer_id"],
            payee_id=payload["payee_id"],
            amount_cents=payload["amount_cents"],
        )
    if kind is ConfirmationKind.EXPENSE_PROPOSAL:
        return lambda seq: record_expense(
            seq=seq,
            occurred_on=date.fromisoformat(payload["occurred_on"]),
            payer_id=payload["payer_id"],
            total_cents=payload["total_cents"],
            description=payload["description"],
            participant_ids=payload["participant_ids"],
        )
    return lambda seq: _reversal_of(
        conn, book_id, payload["target_seq"], author_id, seq
    )


def _reversal_of(
    conn: psycopg.Connection, book_id: UUID, target_seq: int, author_id: str, seq: int
) -> Entry:
    entries = book_entries(conn, book_id)
    original = next((e for e in entries if e.seq == target_seq), None)
    if original is None:
        raise EntryNotFoundError(book_id, target_seq)
    return reverse(original, seq=seq, author_id=author_id, book_entries=entries)


def _lock_book(conn: psycopg.Connection, book_id: UUID) -> tuple[date, date]:
    """Lock the book row for this transaction; return its dates."""
    row = conn.execute(
        "SELECT starts_on, ends_on FROM book WHERE id = %s FOR UPDATE", (book_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"book {book_id} does not exist")
    return row[0], row[1]


def _live_expense_proposals(
    conn: psycopg.Connection, book_id: UUID, author_id: str, at: datetime
) -> list[ExpenseIntent]:
    """The author's open or confirmed expense proposals from the window before
    at: the candidates for break 1. The domain applies the exact rule."""
    return [
        ExpenseIntent(author_id, cents, description, created_at, code)
        for code, created_at, cents, description in conn.execute(
            """
            SELECT code, created_at, (payload ->> 'total_cents')::bigint,
                   payload ->> 'description'
            FROM confirmation
            WHERE book_id = %s
              AND kind = 'expense_proposal'
              AND created_by = %s
              AND status IN ('open', 'confirmed')
              AND created_at > %s - %s::interval
              AND created_at <= %s
            """,
            (book_id, author_id, at, DUPLICATE_WINDOW, at),
        )
    ]
