"""Shared fixtures: a throwaway test database, migrated and seeded once per run."""

import os
import random
import subprocess
import sys
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from ledger.workflow import Action
from store.confirmations import propose_expense, propose_reversal, resolve

TEST_DBNAME = "rateio_test"
SEED_FILE = Path(__file__).parent / "fixtures" / "participants.sql"
FIVE = ["lotti", "luis", "seph", "vini", "vitor"]  # the seeded participants


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
    """Factory: each call creates a fresh book with no entries and returns its id.
    Its members are the five seeded participants unless others are given."""

    def make(members: list[str] = FIVE) -> UUID:
        book_id = conn.execute(
            """
            INSERT INTO book (name, starts_on, ends_on)
            VALUES ('Example trip', '2026-12-25', '2027-01-05')
            RETURNING id
            """
        ).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO book_member (book_id, participant_id) VALUES (%s, %s)",
                [(book_id, pid) for pid in members],
            )
        return book_id

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


@pytest.fixture
def spend(conn, book, make_command):
    """Factory: record an expense the way production does, !gasto then the
    author's !ok. Returns the RecordedEntry."""

    def record(
        payer_id: str = "lotti",
        total_cents: int = 30000,
        *,
        description: str = "fuel",
        occurred_on: date = date(2026, 12, 26),
        book_id: UUID | None = None,
    ):
        book_id = book_id or book
        proposal = propose_expense(
            conn,
            book_id=book_id,
            command_id=make_command(payer_id, book_id=book_id),
            payer_id=payer_id,
            total_cents=total_cents,
            description=description,
            occurred_on=occurred_on,
            rng=random.Random(0),
        )
        return resolve(
            conn,
            book_id=book_id,
            code=proposal.code,
            action=Action.CONFIRM,
            actor=payer_id,
        ).entry

    return record


@pytest.fixture
def undo(conn, book, make_command):
    """Factory: reverse L<target_seq> the way production does, !estorna then the
    author's !ok. Returns the RecordedEntry."""

    def record(
        target_seq: int, author_id: str = "luis", *, book_id: UUID | None = None
    ):
        book_id = book_id or book
        proposal = propose_reversal(
            conn,
            book_id=book_id,
            command_id=make_command(author_id, book_id=book_id, kind="reverse"),
            target_seq=target_seq,
            author_id=author_id,
            rng=random.Random(0),
        )
        return resolve(
            conn,
            book_id=book_id,
            code=proposal.code,
            action=Action.CONFIRM,
            actor=author_id,
        ).entry

    return record
