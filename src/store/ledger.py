"""Writing and reading the ledger: the only code that knows the journal_entry and
posting SQL. Append-only: nothing here updates or deletes an entry or a posting.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from ledger.model import Entry, EntryKind, Posting, Role
from ledger.reversal import reverse


class EntryNotFoundError(LookupError):
    """No entry with that seq in this book. Entries of other books are never
    found, which is how a reversal across books is refused."""

    def __init__(self, book_id: UUID, seq: int) -> None:
        self.book_id = book_id
        self.seq = seq
        super().__init__(
            f"there is no L{seq} in this book; check the entry number in the statement"
        )


@dataclass(frozen=True)
class RecordedEntry:
    """An entry as the store knows it. created is False when the command had
    already produced this entry: a redelivery, reported as success."""

    entry_id: UUID
    seq: int
    recorded_at: datetime
    created: bool


def append_entry(
    conn: psycopg.Connection,
    *,
    book_id: UUID,
    command_id: UUID,
    build: Callable[[int], Entry],
) -> RecordedEntry:
    """Assign the book's next seq, build the entry for it, and write the entry and
    its postings in one transaction. One command never produces two entries.

    build receives the seq and returns the domain entry (which refuses to exist
    unbalanced), so the store decides the number and the domain does the maths.
    """
    with conn.transaction():
        # Lock the book row: concurrent writers to the same book queue here, so
        # max(seq) + 1 cannot be read twice. UNIQUE (book_id, seq) stays as backstop.
        if (
            conn.execute(
                "SELECT id FROM book WHERE id = %s FOR UPDATE", (book_id,)
            ).fetchone()
            is None
        ):
            raise LookupError(f"book {book_id} does not exist")

        existing = _entry_for_command(conn, command_id)
        if existing is not None:
            return existing

        seq = conn.execute(
            "SELECT coalesce(max(seq), 0) + 1 FROM journal_entry WHERE book_id = %s",
            (book_id,),
        ).fetchone()[0]
        entry = build(seq)
        if entry.seq != seq:
            raise ValueError(f"built entry has seq {entry.seq}, expected {seq}")

        # The domain names the reversed entry by seq; the database links by id.
        # Looked up within this book only.
        reverses_entry_id = None
        if entry.reverses_seq is not None:
            reverses_entry_id = _entry_id(conn, book_id, entry.reverses_seq)

        # ON CONFLICT names command_id only: a repeated command is success, while a
        # (book_id, seq) collision or a second reversal of one entry still raises.
        row = conn.execute(
            """
            INSERT INTO journal_entry
                (book_id, seq, kind, occurred_on, author_id, command_id,
                 reverses_entry_id, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (command_id) DO NOTHING
            RETURNING id, seq, recorded_at
            """,
            (
                book_id,
                entry.seq,
                entry.kind.value,
                entry.occurred_on,
                entry.author_id,
                command_id,
                reverses_entry_id,
                Jsonb(_payload(entry)),
            ),
        ).fetchone()
        if row is None:
            existing = _entry_for_command(conn, command_id)
            if existing is None:
                raise RuntimeError(f"command {command_id} conflicted but has no entry")
            return existing

        entry_id, seq, recorded_at = row
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO posting (entry_id, participant_id, amount_cents, role)
                VALUES (%s, %s, %s, %s)
                """,
                [
                    (entry_id, p.participant_id, p.amount_cents, p.role.value)
                    for p in entry.postings
                ],
            )
        return RecordedEntry(entry_id, seq, recorded_at, created=True)


def append_reversal(
    conn: psycopg.Connection,
    *,
    book_id: UUID,
    command_id: UUID,
    target_seq: int,
    author_id: str,
) -> RecordedEntry:
    """Reverse entry L<target_seq> of this book, through append_entry.

    The book's entries are loaded inside append_entry's transaction, after the
    book is locked, so no one can reverse the same entry between the check and
    the write. A redelivered command returns its existing reversal before any
    check runs: a retry is silent, while a new request to reverse the same entry
    is refused by the domain (and, failing that, by the unique index).
    """

    def build(seq: int) -> Entry:
        entries = book_entries(conn, book_id)
        original = next((e for e in entries if e.seq == target_seq), None)
        if original is None:
            raise EntryNotFoundError(book_id, target_seq)
        return reverse(original, seq=seq, author_id=author_id, book_entries=entries)

    return append_entry(conn, book_id=book_id, command_id=command_id, build=build)


def book_entries(conn: psycopg.Connection, book_id: UUID) -> list[Entry]:
    """Every entry of the book as a domain Entry, ordered by seq."""
    postings_by_entry: dict[UUID, list[Posting]] = {}
    for entry_id, pid, cents, role in conn.execute(
        """
        SELECT p.entry_id, p.participant_id, p.amount_cents, p.role
        FROM posting p
        JOIN journal_entry e ON e.id = p.entry_id
        WHERE e.book_id = %s
        ORDER BY p.id
        """,
        (book_id,),
    ):
        postings_by_entry.setdefault(entry_id, []).append(
            Posting(pid, cents, Role(role))
        )

    rows = conn.execute(
        """
        SELECT e.id, e.seq, e.kind, e.occurred_on, e.author_id, e.payload, r.seq
        FROM journal_entry e
        LEFT JOIN journal_entry r ON r.id = e.reverses_entry_id
        WHERE e.book_id = %s
        ORDER BY e.seq
        """,
        (book_id,),
    ).fetchall()
    return [
        Entry(
            seq=seq,
            kind=EntryKind(kind),
            occurred_on=occurred_on,
            author_id=author_id,
            description=payload["description"],
            postings=tuple(postings_by_entry[entry_id]),
            remainder_offset=payload.get("remainder_offset"),
            reverses_seq=reverses_seq,
        )
        for entry_id, seq, kind, occurred_on, author_id, payload, reverses_seq in rows
    ]


def book_postings(conn: psycopg.Connection, book_id: UUID) -> list[Posting]:
    """Every posting of the book, in entry order. The input to positions()."""
    rows = conn.execute(
        """
        SELECT p.participant_id, p.amount_cents, p.role
        FROM posting p
        JOIN journal_entry e ON e.id = p.entry_id
        WHERE e.book_id = %s
        ORDER BY e.seq, p.id
        """,
        (book_id,),
    ).fetchall()
    return [Posting(pid, cents, Role(role)) for pid, cents, role in rows]


def _entry_for_command(
    conn: psycopg.Connection, command_id: UUID
) -> RecordedEntry | None:
    row = conn.execute(
        "SELECT id, seq, recorded_at FROM journal_entry WHERE command_id = %s",
        (command_id,),
    ).fetchone()
    if row is None:
        return None
    entry_id, seq, recorded_at = row
    return RecordedEntry(entry_id, seq, recorded_at, created=False)


def _entry_id(conn: psycopg.Connection, book_id: UUID, seq: int) -> UUID:
    row = conn.execute(
        "SELECT id FROM journal_entry WHERE book_id = %s AND seq = %s",
        (book_id, seq),
    ).fetchone()
    if row is None:
        raise EntryNotFoundError(book_id, seq)
    return row[0]


def _payload(entry: Entry) -> dict[str, object]:
    # total_cents is the sum of outlays, so a reversal's is negative, matching
    # its statement line.
    payload: dict[str, object] = {
        "total_cents": sum(
            p.amount_cents for p in entry.postings if p.role is Role.OUTLAY
        ),
        "description": entry.description,
        "remainder_offset": entry.remainder_offset,
    }
    if entry.kind is EntryKind.EXPENSE:
        payload["split_rule"] = "even"
    return payload
