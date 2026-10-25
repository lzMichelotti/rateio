"""Replaying the log reproduces the positions, whichever way it is replayed."""

from collections import Counter
from datetime import date

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ledger.expense import record_expense
from ledger.positions import positions
from store.ledger import append_entry, book_postings

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]  # seeded in the test database

trips = st.lists(
    st.tuples(st.sampled_from(FIVE), st.integers(min_value=1, max_value=1_000_000)),
    max_size=15,
)


def expense(payer_id: str, total_cents: int):
    return lambda seq: record_expense(
        seq=seq,
        occurred_on=date(2026, 12, 26),
        payer_id=payer_id,
        total_cents=total_cents,
        description="expense",
        participant_ids=FIVE,
    )


# Each generated trip runs in its own forced-rollback transaction on a fresh
# book, so the function-scoped fixtures are safely reset between cases.
@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(trip=trips)
def test_replay_reproduces_positions(conn, make_book, make_command, trip):
    with conn.transaction(force_rollback=True):
        book_id = make_book()
        entries = []
        for payer_id, total_cents in trip:
            build = expense(payer_id, total_cents)
            recorded = append_entry(
                conn,
                book_id=book_id,
                command_id=make_command(payer_id, book_id=book_id),
                build=build,
            )
            entries.append(build(recorded.seq))

        all_postings = [p for entry in entries for p in entry.postings]
        from_scratch = positions(all_postings)

        # Entry by entry: the running total must match, and sum to zero at every step.
        running: Counter[str] = Counter()
        for entry in entries:
            running.update(positions(entry.postings))
            assert sum(running.values()) == 0
        assert {k: v for k, v in running.items() if v} == {
            k: v for k, v in from_scratch.items() if v
        }

        # What went into the database comes back out unchanged.
        assert positions(book_postings(conn, book_id)) == from_scratch
