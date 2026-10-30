"""The worker: the processor running continuously (make worker).

Locally, the inbox table is the queue: every second the worker processes what is
waiting, one transaction per message, oldest first. Stage 06 replaces this loop
with SQS and Lambda; the processor it calls stays the same.

Two kinds of trouble, handled apart:

- The database is unreachable (psycopg.OperationalError): environment, not a
  bug. The message being processed was rolled back and is still waiting, so the
  worker reconnects after a growing wait and carries on.
- Anything else is a bug: the worker stops and says so. Carrying on could act on
  a later message (an !ok) before the one that failed (its proposal). Nothing is
  lost: the bridge keeps landing messages, and they wait for the fix.

Ctrl+C or SIGTERM asks it to stop after the message in hand; even a harder stop
in mid-transaction leaves nothing of that message behind.

Usage: python -m core.worker   (reads DATABASE_URL)
"""

import os
import random
import signal
import sys
import time
import traceback
from collections.abc import Callable

import psycopg

from core import processor

POLL_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0


def run(
    connect: Callable[[], psycopg.Connection],
    *,
    rng: random.Random,
    should_stop: Callable[[], bool],
    sleep: Callable[[float], None],
    log: Callable[[str], None] = print,
) -> None:
    """Process the inbox until should_stop. Raises on a bug."""
    backoff = 1.0
    conn: psycopg.Connection | None = None
    while not should_stop():
        try:
            if conn is None or conn.closed:
                conn = connect()
            processor.process_pending(conn, rng=rng, should_stop=should_stop)
            backoff = 1.0
        except psycopg.OperationalError as error:
            log(
                f"database unavailable ({type(error).__name__}); retrying in {backoff:.0f}s"
            )
            if conn is not None:
                conn.close()
            conn = None
            sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue
        sleep(POLL_SECONDS)


def main() -> int:
    stopping = False

    def request_stop(signum: int, frame: object) -> None:
        nonlocal stopping
        stopping = True

    # A flag, not KeyboardInterrupt: the message in hand finishes its transaction.
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    def nap(seconds: float) -> None:
        # Short steps, so a stop request is honoured within a tenth of a second.
        deadline = time.monotonic() + seconds
        while not stopping and time.monotonic() < deadline:
            time.sleep(0.1)

    url = os.environ["DATABASE_URL"]
    print("worker running (Ctrl+C stops)")
    try:
        # Autocommit: each message's transaction commits on its own.
        run(
            lambda: psycopg.connect(url, autocommit=True),
            rng=random.Random(),
            should_stop=lambda: stopping,
            sleep=nap,
        )
    except Exception:  # noqa: BLE001 - the top: any bug ends the worker, said once
        traceback.print_exc()
        print(
            "worker stopped on a bug; the message stays in the inbox until it is fixed",
            file=sys.stderr,
        )
        return 1
    print("worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
