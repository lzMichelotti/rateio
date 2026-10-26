"""Shared fixtures: a throwaway test database, migrated and seeded once per run."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

TEST_DBNAME = "rateio_test"
SEED_FILE = Path(__file__).parent / "fixtures" / "participants.sql"


@pytest.fixture(scope="session")
def database_url() -> str:
    """Recreate the test database from scratch, run the real migrations, seed it.

    The dev database named in DATABASE_URL is only used to issue CREATE/DROP;
    tests never touch its data.
    """
    dev_url = os.environ.get("DATABASE_URL")
    if not dev_url:
        pytest.fail("DATABASE_URL is not set (copy .env.example to .env)")
    test_url = make_conninfo(dev_url, dbname=TEST_DBNAME)

    # CREATE/DROP DATABASE cannot run inside a transaction, hence autocommit.
    with psycopg.connect(dev_url, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DBNAME}")
        admin.execute(f"CREATE DATABASE {TEST_DBNAME}")

    # Run the runner exactly as `make migrate` does, so tests exercise the real path.
    subprocess.run(
        [sys.executable, "-m", "store.migrate"],
        env={**os.environ, "DATABASE_URL": test_url},
        check=True,
    )

    with psycopg.connect(test_url) as conn:
        conn.execute(SEED_FILE.read_text(encoding="utf-8"))

    return test_url


@pytest.fixture
def conn(database_url: str):
    """A connection whose changes are rolled back after each test."""
    with psycopg.connect(database_url) as conn:
        yield conn
        conn.rollback()


@pytest.fixture
def make_book(conn):
    """Factory: each call creates a fresh, empty book and returns its id."""

    def make() -> UUID:
        return conn.execute(
            """
            INSERT INTO book (name, starts_on, ends_on)
            VALUES ('Example trip', '2026-12-25', '2027-01-05')
            RETURNING id
            """
        ).fetchone()[0]

    return make


@pytest.fixture
def book(make_book) -> UUID:
    """A fresh, empty book. Gone after the test, like everything on `conn`."""
    return make_book()


@pytest.fixture
def make_command(conn, book):
    """Factory: each call lands a fake inbound message and its command.

    Returns the command id. Reusing one id simulates a redelivered command.
    The command belongs to the `book` fixture unless another book_id is given.
    """

    def make(
        participant_id: str = "lotti",
        payload: dict | None = None,
        book_id: UUID | None = None,
        kind: str = "record_expense",
    ) -> UUID:
        message_id = conn.execute(
            """
            INSERT INTO inbound_message
                (channel, conversation_external_id, sender_external_id,
                 dedupe_key, raw_payload)
            VALUES ('test', '120000000000000001@g.us', '5500000000001@s.whatsapp.net',
                    %s, %s)
            RETURNING id
            """,
            (uuid4().hex, Jsonb({})),
        ).fetchone()[0]
        return conn.execute(
            """
            INSERT INTO command
                (inbound_message_id, book_id, participant_id, kind, payload, source)
            VALUES (%s, %s, %s, %s, %s, 'syntax')
            RETURNING id
            """,
            (message_id, book_id or book, participant_id, kind, Jsonb(payload or {})),
        ).fetchone()[0]

    return make
