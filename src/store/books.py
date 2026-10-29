"""The identity layer in SQL: books, their members, and how channels name people."""

from uuid import UUID

import psycopg


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
