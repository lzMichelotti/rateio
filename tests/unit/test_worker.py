"""The worker loop, with its connection, pause and stop condition passed in."""

import random
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from core import processor, worker
from store import inbox
from store.books import link_conversation, link_identity

START = datetime(2026, 12, 26, 15, 0, tzinfo=UTC)


@pytest.fixture
def queue(conn, book):
    link_conversation(conn, channel="cli", external_id="trip", book_id=book)
    link_identity(conn, channel="cli", external_id="lotti", participant_id="lotti")

    def put(*texts):
        return [
            inbox.receive(
                conn,
                channel="cli",
                conversation_external_id="trip",
                sender_external_id="lotti",
                dedupe_key=f"test:{i}",
                raw_payload={"text": text},
                received_at=START + timedelta(minutes=i),
            )
            for i, text in enumerate(texts)
        ]

    return put


def processed(conn, ids):
    return [
        conn.execute(
            "SELECT processed_at IS NOT NULL FROM inbound_message WHERE id = %s", (i,)
        ).fetchone()[0]
        for i in ids
    ]


def test_it_processes_what_waits_then_pauses(conn, queue):
    ids = queue("!saldo", "!ajuda")
    naps = []

    worker.run(
        lambda: conn,
        rng=random.Random(0),
        should_stop=lambda: bool(naps),
        sleep=naps.append,
    )

    assert processed(conn, ids) == [True, True]
    assert naps == [worker.POLL_SECONDS]


def test_a_lost_database_is_waited_for_not_a_reason_to_stop(conn, queue):
    ids = queue("!saldo")
    attempts, naps, logs = [], [], []

    def connect():
        attempts.append(1)
        if len(attempts) == 1:
            raise psycopg.OperationalError("connection refused")
        return conn

    worker.run(
        connect,
        rng=random.Random(0),
        should_stop=lambda: len(naps) >= 2,
        sleep=naps.append,
        report=logs.append,
    )

    assert processed(conn, ids) == [True]
    assert naps == [1.0, worker.POLL_SECONDS]
    assert logs == ["worker.db_unavailable error=OperationalError retry_in=1s"]


def test_a_bug_stops_the_worker(conn, queue, monkeypatch):
    queue("!saldo")

    def broken(*args, **kwargs):
        raise RuntimeError("a bug in the core")

    monkeypatch.setattr(processor, "_process", broken)

    with pytest.raises(RuntimeError):
        worker.run(
            lambda: conn,
            rng=random.Random(0),
            should_stop=lambda: False,
            sleep=lambda s: None,
        )


def test_a_stop_request_lets_the_message_in_hand_finish(conn, queue):
    ids = queue("!saldo", "!ajuda")

    worker.run(
        lambda: conn,
        rng=random.Random(0),
        should_stop=lambda: processed(conn, ids[:1]) == [True],
        sleep=lambda s: None,
    )

    assert processed(conn, ids) == [True, False]
