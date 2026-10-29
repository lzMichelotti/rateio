"""The inbox and the outbox in SQL: messages in, commands recorded, replies out.

Locally this table is the queue: the processor takes the oldest unprocessed
message, one at a time. Stage 06 replaces the polling with SQS and Lambda; the
statements a message's transaction runs stay the same.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class Inbound:
    id: UUID
    channel: str
    conversation_external_id: str
    sender_external_id: str
    raw_payload: Mapping[str, Any]
    received_at: datetime


def receive(
    conn: psycopg.Connection,
    *,
    channel: str,
    conversation_external_id: str,
    sender_external_id: str,
    dedupe_key: str,
    raw_payload: Mapping[str, Any],
    received_at: datetime | None = None,
) -> UUID | None:
    """Land a message addressed to the bot. None means the dedupe key was seen
    before: a redelivery, dropped in silence (gate 1 of the idempotency chain).
    received_at defaults to the database clock; a channel may pass its own."""
    row = conn.execute(
        """
        INSERT INTO inbound_message
            (channel, conversation_external_id, sender_external_id, dedupe_key,
             raw_payload, received_at)
        VALUES (%s, %s, %s, %s, %s, coalesce(%s, now()))
        ON CONFLICT (dedupe_key) DO NOTHING
        RETURNING id
        """,
        (
            channel,
            conversation_external_id,
            sender_external_id,
            dedupe_key,
            Jsonb(dict(raw_payload)),
            received_at,
        ),
    ).fetchone()
    return None if row is None else row[0]


def next_pending(conn: psycopg.Connection) -> UUID | None:
    """The oldest unprocessed message, locked until this transaction ends.

    Plain FOR UPDATE, not SKIP LOCKED: a second processor waits rather than
    skipping ahead, so messages are acted on in the order they arrived.
    """
    row = conn.execute(
        """
        SELECT id FROM inbound_message
        WHERE processed_at IS NULL
        ORDER BY received_at, id
        LIMIT 1
        FOR UPDATE
        """
    ).fetchone()
    return None if row is None else row[0]


def lock_unprocessed(conn: psycopg.Connection, inbound_id: UUID) -> Inbound | None:
    """The message, locked, if it still needs processing; None if it was
    processed already, which makes processing the same message twice a no-op."""
    row = conn.execute(
        """
        SELECT id, channel, conversation_external_id, sender_external_id,
               raw_payload, received_at
        FROM inbound_message
        WHERE id = %s AND processed_at IS NULL
        FOR UPDATE
        """,
        (inbound_id,),
    ).fetchone()
    return None if row is None else Inbound(*row)


def record_command(
    conn: psycopg.Connection,
    *,
    inbound_id: UUID,
    book_id: UUID,
    participant_id: str,
    kind: str,
    payload: Mapping[str, Any],
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO command
            (inbound_message_id, book_id, participant_id, kind, payload, source)
        VALUES (%s, %s, %s, %s, %s, 'syntax')
        RETURNING id
        """,
        (inbound_id, book_id, participant_id, kind, Jsonb(dict(payload))),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def enqueue_reply(
    conn: psycopg.Connection, *, conversation_id: UUID, inbound_id: UUID, body: str
) -> None:
    """One reply per message, ever: the key is reply:<inbound_message_id>."""
    conn.execute(
        """
        INSERT INTO outbound_message (conversation_id, body, dedupe_key)
        VALUES (%s, %s, %s)
        ON CONFLICT (dedupe_key) DO NOTHING
        """,
        (conversation_id, body, f"reply:{inbound_id}"),
    )


def mark_processed(conn: psycopg.Connection, inbound_id: UUID) -> None:
    conn.execute(
        "UPDATE inbound_message SET processed_at = now() WHERE id = %s", (inbound_id,)
    )


def pending_replies(
    conn: psycopg.Connection, conversation_id: UUID
) -> list[tuple[UUID, str]]:
    """(id, body) of this chat's unsent messages, oldest first, locked so two
    senders never deliver the same one."""
    return [
        (row[0], row[1])
        for row in conn.execute(
            """
            SELECT id, body FROM outbound_message
            WHERE conversation_id = %s AND status = 'pending'
            ORDER BY created_at, id
            FOR UPDATE
            """,
            (conversation_id,),
        )
    ]


def mark_sent(
    conn: psycopg.Connection, outbound_id: UUID, channel_message_id: str | None = None
) -> None:
    conn.execute(
        """
        UPDATE outbound_message
        SET status = 'sent', sent_at = now(), attempts = attempts + 1,
            channel_message_id = %s
        WHERE id = %s AND status = 'pending'
        """,
        (channel_message_id, outbound_id),
    )
