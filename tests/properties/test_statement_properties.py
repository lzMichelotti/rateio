"""The statement hides nothing, across trips that mix expenses and reversals."""

from datetime import date

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ledger.expense import record_expense
from ledger.model import EntryKind
from ledger.positions import positions
from ledger.statement import statement
from store.ledger import append_entry, append_reversal, book_entries, book_postings

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]  # seeded in the test database

spend = st.tuples(
    st.just("spend"),
    st.sampled_from(FIVE),
    st.integers(min_value=1, max_value=1_000_000),
)
# Which still-reversible entry to reverse, as an index into the candidates.
undo = st.tuples(st.just("reverse"), st.integers(min_value=0, max_value=1_000))
trips = st.lists(st.one_of(spend, undo), max_size=15)


def expense(payer_id: str, total_cents: int):
    return lambda seq: record_expense(
        seq=seq,
        occurred_on=date(2026, 12, 26),
        payer_id=payer_id,
        total_cents=total_cents,
        description="expense",
        participant_ids=FIVE,
    )


# Each trip runs in its own forced-rollback transaction on a fresh book, so the
# function-scoped fixtures are safely reset between cases.
@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(trip=trips)
def test_statement_contains_every_entry_ever_written(
    conn, make_book, make_command, trip
):
    with conn.transaction(force_rollback=True):
        book_id = make_book()
        reversible: list[int] = []  # expenses not yet reversed, by seq
        for step in trip:
            if step[0] == "spend":
                _, payer_id, total_cents = step
                recorded = append_entry(
                    conn,
                    book_id=book_id,
                    command_id=make_command(payer_id, book_id=book_id),
                    build=expense(payer_id, total_cents),
                )
                reversible.append(recorded.seq)
            elif reversible:
                target = reversible.pop(step[1] % len(reversible))
                append_reversal(
                    conn,
                    book_id=book_id,
                    command_id=make_command(book_id=book_id, kind="reverse"),
                    target_seq=target,
                    author_id="luis",
                )

        entries = book_entries(conn, book_id)
        lines = statement(entries)
        (written,) = conn.execute(
            "SELECT count(*) FROM journal_entry WHERE book_id = %s", (book_id,)
        ).fetchone()

        # Nothing hidden: one line per entry ever written, reversed ones included.
        assert len(lines) == written

        # Both sides of every reversal are marked, and point at each other.
        by_seq = {line.seq: line for line in lines}
        for line in lines:
            if line.kind is EntryKind.REVERSAL:
                assert by_seq[line.reverses].reversed_by == line.seq

        # Reversals undo exactly their originals: the book's positions equal the
        # positions of the expenses that were never reversed.
        surviving = [p for e in entries if e.seq in reversible for p in e.postings]
        net = positions(book_postings(conn, book_id))
        assert {k: v for k, v in net.items() if v} == {
            k: v for k, v in positions(surviving).items() if v
        }
        assert sum(net.values()) == 0
