import pytest
from psycopg import errors


@pytest.fixture
def conversation(conn, book):
    return conn.execute(
        """
        INSERT INTO conversation (channel, external_id, kind, book_id)
        VALUES ('cli', 'trip', 'group', %s)
        RETURNING id
        """,
        (book,),
    ).fetchone()[0]


def enqueue(conn, conversation, key):
    return conn.execute(
        """
        INSERT INTO outbound_message (conversation_id, body, dedupe_key)
        VALUES (%s, 'ok', %s)
        ON CONFLICT (dedupe_key) DO NOTHING
        RETURNING id, status
        """,
        (conversation, key),
    ).fetchone()


def test_a_reply_starts_pending(conn, conversation):
    assert enqueue(conn, conversation, "reply:1")[1] == "pending"


def test_one_row_per_dedupe_key(conn, conversation):
    enqueue(conn, conversation, "reply:1")

    assert enqueue(conn, conversation, "reply:1") is None


def test_status_is_one_of_three(conn, conversation):
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            """
            INSERT INTO outbound_message (conversation_id, body, dedupe_key, status)
            VALUES (%s, 'ok', 'reply:2', 'lost')
            """,
            (conversation,),
        )
