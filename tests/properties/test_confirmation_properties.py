"""Invariants of the confirmation workflow, checked against generated trips."""

import random
from datetime import date

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ledger.positions import positions
from ledger.workflow import Action
from store.confirmations import declare_settlement, propose_expense, resolve
from store.ledger import book_postings

FIVE = ["lotti", "luis", "seph", "vini", "vitor"]  # seeded in the test database
DAY = date(2026, 12, 26)

expenses = st.lists(
    st.tuples(st.sampled_from(FIVE), st.integers(min_value=1, max_value=1_000_000)),
    min_size=1,
    max_size=8,
)
# (which debtor pays, which other participant receives, percent of the debt)
payments = st.tuples(
    st.integers(min_value=0, max_value=1_000),
    st.integers(min_value=0, max_value=1_000),
    st.integers(min_value=1, max_value=100),
)

isolated = settings(
    deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


def declare_some_payment(conn, make_command, book_id, payment):
    """Declare a valid payment from a current debtor, or None if nobody owes."""
    net = positions(book_postings(conn, book_id))
    debtors = sorted(p for p, cents in net.items() if cents < 0)
    if not debtors:
        return None
    pick_payer, pick_payee, percent = payment
    payer_id = debtors[pick_payer % len(debtors)]
    others = [p for p in FIVE if p != payer_id]
    payee_id = others[pick_payee % len(others)]
    amount_cents = max(1, -net[payer_id] * percent // 100)
    return (
        declare_settlement(
            conn,
            book_id=book_id,
            command_id=make_command(
                payer_id, book_id=book_id, kind="declare_settlement"
            ),
            payer_id=payer_id,
            payee_id=payee_id,
            amount_cents=amount_cents,
            declared_on=DAY,
            rng=random.Random(0),
        ),
        payee_id,
        payer_id,
    )


# Each trip runs in its own forced-rollback transaction on a fresh book, so the
# function-scoped fixtures are safely reset between cases.


@isolated
@given(trip=expenses, declared=st.lists(payments, max_size=5))
def test_a_declared_unconfirmed_settlement_changes_no_position(
    conn, make_book, make_command, spend, trip, declared
):
    with conn.transaction(force_rollback=True):
        book_id = make_book()
        for payer_id, total_cents in trip:
            spend(payer_id, total_cents, book_id=book_id)
        before = positions(book_postings(conn, book_id))

        for payment in declared:
            declare_some_payment(conn, make_command, book_id, payment)

        assert positions(book_postings(conn, book_id)) == before
        assert conn.execute(
            """
            SELECT count(*) FROM settlement
            WHERE book_id = %s AND (status <> 'declared' OR entry_id IS NOT NULL)
            """,
            (book_id,),
        ).fetchone() == (0,)


@isolated
@given(
    trip=expenses,
    payment=payments,
    as_settlement=st.booleans(),
    times=st.integers(min_value=2, max_value=5),
)
def test_confirming_the_same_confirmation_n_times_creates_one_entry(
    conn, make_book, make_command, spend, trip, payment, as_settlement, times
):
    with conn.transaction(force_rollback=True):
        book_id = make_book()
        for payer_id, total_cents in trip:
            spend(payer_id, total_cents, book_id=book_id)

        declared = as_settlement and declare_some_payment(
            conn, make_command, book_id, payment
        )
        if declared:
            proposal, confirmer, _ = declared
        else:
            proposal = propose_expense(
                conn,
                book_id=book_id,
                command_id=make_command("vini", book_id=book_id),
                payer_id="vini",
                total_cents=12345,
                description="expense",
                occurred_on=DAY,
                participant_ids=FIVE,
                rng=random.Random(0),
            )
            confirmer = "vini"

        results = [
            resolve(
                conn,
                book_id=book_id,
                code=proposal.code,
                action=Action.CONFIRM,
                actor=confirmer,
            )
            for _ in range(times)
        ]

        assert [r.changed for r in results] == [True] + [False] * (times - 1)
        assert conn.execute(
            "SELECT count(*) FROM journal_entry WHERE confirmation_id = %s",
            (proposal.confirmation_id,),
        ).fetchone() == (1,)


steps = st.lists(
    st.one_of(
        st.tuples(
            st.just("expense"),
            st.sampled_from(FIVE),
            st.integers(min_value=1, max_value=1_000_000),
            st.sampled_from(["confirm", "decline", "leave"]),
        ),
        st.tuples(
            st.just("payment"),
            payments,
            st.sampled_from(["confirm", "reject", "cancel", "leave"]),
        ),
        st.tuples(st.just("reverse"), st.integers(min_value=0, max_value=1_000)),
    ),
    max_size=12,
)


@isolated
@given(opening=expenses, trip=steps)
def test_every_entry_has_one_confirmation_and_every_confirmed_one_one_entry(
    conn, make_book, make_command, spend, undo, opening, trip
):
    with conn.transaction(force_rollback=True):
        book_id = make_book()
        # Confirmed expenses first, so there are debts for payments to settle.
        reversible = [
            spend(payer_id, total_cents, book_id=book_id).seq
            for payer_id, total_cents in opening
        ]
        for step in trip:
            if step[0] == "expense":
                _, payer_id, total_cents, outcome = step
                proposal = propose_expense(
                    conn,
                    book_id=book_id,
                    command_id=make_command(payer_id, book_id=book_id),
                    payer_id=payer_id,
                    total_cents=total_cents,
                    description="expense",
                    occurred_on=DAY,
                    participant_ids=FIVE,
                    rng=random.Random(0),
                )
                if outcome != "leave":
                    action = Action.CONFIRM if outcome == "confirm" else Action.DECLINE
                    resolution = resolve(
                        conn,
                        book_id=book_id,
                        code=proposal.code,
                        action=action,
                        actor=payer_id,
                    )
                    if resolution.entry is not None:
                        reversible.append(resolution.entry.seq)
            elif step[0] == "payment":
                _, payment, outcome = step
                declared = declare_some_payment(conn, make_command, book_id, payment)
                if declared and outcome != "leave":
                    proposal, payee_id, payer_id = declared
                    actor = payer_id if outcome == "cancel" else payee_id
                    action = Action.CONFIRM if outcome == "confirm" else Action.DECLINE
                    resolve(
                        conn,
                        book_id=book_id,
                        code=proposal.code,
                        action=action,
                        actor=actor,
                    )
            elif reversible:
                undo(reversible.pop(step[1] % len(reversible)), book_id=book_id)

        # Every entry carries a confirmation, and no two entries share one.
        entries, with_confirmation, distinct = conn.execute(
            """
            SELECT count(*), count(confirmation_id), count(DISTINCT confirmation_id)
            FROM journal_entry WHERE book_id = %s
            """,
            (book_id,),
        ).fetchone()
        assert entries == with_confirmation == distinct

        # Confirmed <=> has an entry, and the two pointers agree both ways.
        assert conn.execute(
            """
            SELECT count(*)
            FROM confirmation c
            LEFT JOIN journal_entry e ON e.id = c.entry_id
            WHERE c.book_id = %s
              AND NOT (
                    (c.status = 'confirmed' AND e.confirmation_id = c.id)
                 OR (c.status <> 'confirmed' AND c.entry_id IS NULL)
              )
            """,
            (book_id,),
        ).fetchone() == (0,)
        assert conn.execute(
            """
            SELECT count(*)
            FROM journal_entry e
            JOIN confirmation c ON c.id = e.confirmation_id
            WHERE e.book_id = %s AND (c.status <> 'confirmed' OR c.entry_id <> e.id)
            """,
            (book_id,),
        ).fetchone() == (0,)
