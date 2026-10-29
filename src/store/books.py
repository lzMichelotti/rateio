"""The identity layer in SQL: books, their members, and how channels name people."""

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
