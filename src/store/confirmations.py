"""The confirmation workflow in SQL: propose, then resolve with !ok or !nao.

Every financial fact goes command -> open confirmation -> !ok -> entry. A
settlement is the same mechanism with the payee as confirmer.

confirmation and settlement are workflow state, updated in place. Their updates
are conditional (`WHERE status = 'open'`) and the affected row count says who
won: 1 means this call resolved it, 0 means someone else did first.
"""

import random
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

import psycopg
from psycopg import errors
from psycopg.types.json import Jsonb

from ledger.breaks import Break, overpayment_breaks
from ledger.expense import record_expense
from ledger.model import Entry
from ledger.positions import positions
from ledger.reversal import reverse
from ledger.settlement import record_settlement, validate_declaration
from ledger.workflow import (
    Action,
    ConfirmationKind,
    ConfirmationStatus,
    SettlementStatus,
    transition_confirmation,
    transition_settlement,
)
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


class NoFreeCodeError(RuntimeError):
    """Every code is open or recently resolved in this book."""


class ConfirmationNotFoundError(LookupError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"there is no confirmation {code} in this book")


class ResolvedConcurrentlyError(RuntimeError):
    """Someone else resolved this confirmation between our read and our update.
    The transaction is rolled back; their resolution stands."""


@dataclass(frozen=True)
class Proposal:
    confirmation_id: UUID
    code: str
    created: bool  # False: the proposing command was seen before


@dataclass(frozen=True)
class Resolution:
    confirmation_id: UUID
    status: ConfirmationStatus
    changed: bool  # False: the same action repeated, nothing happened
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
    participant_ids: Iterable[str],
    rng: random.Random,
) -> Proposal:
    """A !gasto: open the author's own confirmation for an expense.

    The participants are captured now, so the !ok confirms exactly what was
    proposed. The expense is built once here only to validate it.
    """
    ids = sorted(participant_ids)
    record_expense(
        seq=1,
        occurred_on=occurred_on,
        payer_id=payer_id,
        total_cents=total_cents,
        description=description,
        participant_ids=ids,
    )
    return propose(
        conn,
        book_id=book_id,
        command_id=command_id,
        kind=ConfirmationKind.EXPENSE_PROPOSAL,
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
    )


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
            return Resolution(confirmation_id, transition.status, changed=False)

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

        return Resolution(confirmation_id, transition.status, True, entry, breaks)


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
        raise NoFreeCodeError(f"no free confirmation code in book {book_id}")
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
                        (code, book_id, command_id, kind, payload, created_by, confirmer)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
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
    raise NoFreeCodeError(f"no free code after {MAX_CODE_ATTEMPTS} attempts")


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


def _lock_book(conn: psycopg.Connection, book_id: UUID) -> None:
    if (
        conn.execute(
            "SELECT id FROM book WHERE id = %s FOR UPDATE", (book_id,)
        ).fetchone()
        is None
    ):
        raise LookupError(f"book {book_id} does not exist")
