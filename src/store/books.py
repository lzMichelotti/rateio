"""The identity layer in SQL: books, their members, and how channels name people."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

import psycopg


def conversation_book(
    conn: psycopg.Connection, channel: str, external_id: str
) -> tuple[UUID, UUID] | None:
    """(conversation id, book id) for a channel's chat, or None if unknown."""
    row = conn.execute(
        """
        SELECT id, book_id FROM conversation
        WHERE channel = %s AND external_id = %s
        """,
        (channel, external_id),
    ).fetchone()
    return None if row is None else (row[0], row[1])


def participant_for(
    conn: psycopg.Connection, channel: str, external_id: str
) -> str | None:
    """The person a channel's identifier names, or None if nobody linked it."""
    row = conn.execute(
        """
        SELECT participant_id FROM channel_identity
        WHERE channel = %s AND external_id = %s
        """,
        (channel, external_id),
    ).fetchone()
    return None if row is None else str(row[0])


def member_names(conn: psycopg.Connection, book_id: UUID) -> list[tuple[str, str]]:
    """(participant id, display name) of every member, sorted by id."""
    return [
        (pid, name)
        for pid, name in conn.execute(
            """
            SELECT m.participant_id, p.display_name
            FROM book_member m
            JOIN participant p ON p.id = m.participant_id
            WHERE m.book_id = %s
            ORDER BY m.participant_id
            """,
            (book_id,),
        )
    ]


def book_members(conn: psycopg.Connection, book_id: UUID) -> list[str]:
    """The participant ids of every member of the book, sorted by id: the order
    the rounding remainder rotates over."""
    return [
        pid
        for (pid,) in conn.execute(
            """
            SELECT participant_id FROM book_member
            WHERE book_id = %s
            ORDER BY participant_id
            """,
            (book_id,),
        )
    ]


# -- administration --------------------------------------------------------------
# Each returns whether it changed anything, so running a setup script twice
# reports "already there" instead of duplicating or failing.


class BookNotFoundError(LookupError):
    pass


class AmbiguousBookError(LookupError):
    pass


def create_book(
    conn: psycopg.Connection, *, name: str, starts_on: date, ends_on: date
) -> UUID:
    row = conn.execute(
        "INSERT INTO book (name, starts_on, ends_on) VALUES (%s, %s, %s) RETURNING id",
        (name, starts_on, ends_on),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def find_book(conn: psycopg.Connection, name_or_id: str) -> UUID:
    """A book by its id, or by its name when exactly one book has it."""
    try:
        by_id = UUID(name_or_id)
    except ValueError:
        by_id = None
    if by_id is not None:
        row = conn.execute("SELECT id FROM book WHERE id = %s", (by_id,)).fetchone()
        if row is None:
            raise BookNotFoundError(name_or_id)
        return by_id
    ids = [
        UUID(str(bid))
        for (bid,) in conn.execute("SELECT id FROM book WHERE name = %s", (name_or_id,))
    ]
    if not ids:
        raise BookNotFoundError(name_or_id)
    if len(ids) > 1:
        raise AmbiguousBookError(f"{len(ids)} books are named {name_or_id!r}")
    return ids[0]


def add_participant(
    conn: psycopg.Connection, *, participant_id: str, display_name: str
) -> bool:
    return (
        conn.execute(
            """
            INSERT INTO participant (id, display_name) VALUES (%s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (participant_id, display_name),
        ).rowcount
        == 1
    )


def add_member(conn: psycopg.Connection, *, book_id: UUID, participant_id: str) -> bool:
    return (
        conn.execute(
            """
            INSERT INTO book_member (book_id, participant_id) VALUES (%s, %s)
            ON CONFLICT (book_id, participant_id) DO NOTHING
            """,
            (book_id, participant_id),
        ).rowcount
        == 1
    )


def link_identity(
    conn: psycopg.Connection, *, channel: str, external_id: str, participant_id: str
) -> bool:
    """Link a channel's identifier to a person. An identifier already linked to
    someone stays as it is: relinking it would silently change who said what."""
    return (
        conn.execute(
            """
            INSERT INTO channel_identity (channel, external_id, participant_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (channel, external_id) DO NOTHING
            """,
            (channel, external_id, participant_id),
        ).rowcount
        == 1
    )


def link_conversation(
    conn: psycopg.Connection,
    *,
    channel: str,
    external_id: str,
    book_id: UUID,
    kind: str = "group",
) -> bool:
    return (
        conn.execute(
            """
            INSERT INTO conversation (channel, external_id, kind, book_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (channel, external_id) DO NOTHING
            """,
            (channel, external_id, kind, book_id),
        ).rowcount
        == 1
    )


@dataclass(frozen=True)
class BookOverview:
    name: str
    starts_on: date
    ends_on: date
    members: list[tuple[str, str]]  # (participant id, display name)
    identities: list[tuple[str, str, str]]  # (channel, external id, participant id)
    conversations: list[tuple[str, str, str]]  # (channel, external id, kind)


def book_overview(conn: psycopg.Connection, book_id: UUID) -> BookOverview:
    name, starts_on, ends_on = conn.execute(
        "SELECT name, starts_on, ends_on FROM book WHERE id = %s", (book_id,)
    ).fetchone()
    identities = conn.execute(
        """
        SELECT i.channel, i.external_id, i.participant_id
        FROM channel_identity i
        JOIN book_member m ON m.participant_id = i.participant_id
        WHERE m.book_id = %s
        ORDER BY i.participant_id, i.channel, i.external_id
        """,
        (book_id,),
    ).fetchall()
    conversations = conn.execute(
        """
        SELECT channel, external_id, kind FROM conversation
        WHERE book_id = %s ORDER BY channel, external_id
        """,
        (book_id,),
    ).fetchall()
    return BookOverview(
        name,
        starts_on,
        ends_on,
        member_names(conn, book_id),
        [tuple(r) for r in identities],
        [tuple(r) for r in conversations],
    )
