from datetime import UTC, date, datetime, timedelta

import pytest

from ledger.breaks import (
    OVERPAYMENT,
    Break,
    ExpenseIntent,
    IntentDuplicate,
    OutsideBookDates,
    overpayment_breaks,
    proposal_warnings,
)


def test_an_exact_payment_raises_no_break():
    after = {"luis": 0, "seph": 0}

    assert overpayment_breaks(after, payer_id="luis", payee_id="seph") == []


def test_a_partial_payment_raises_no_break():
    after = {"luis": -4000, "seph": 4000}

    assert overpayment_breaks(after, payer_id="luis", payee_id="seph") == []


def test_paying_100_after_the_debt_dropped_to_40_reports_both_sides():
    # luis owed 100 and declared 100; a reversal cut his debt to 40, and seph's
    # credit to 40, before seph confirmed. The 100 still arrived.
    after = {"luis": -4000 + 10000, "seph": 4000 - 10000}

    assert overpayment_breaks(after, payer_id="luis", payee_id="seph") == [
        Break(OVERPAYMENT, "luis", 6000),
        Break(OVERPAYMENT, "seph", -6000),
    ]


def test_only_the_side_that_went_wrong_is_reported():
    # seph was owed by others too, so receiving more than luis owed leaves seph
    # still a creditor: only luis is reported.
    after = {"luis": 6000, "seph": 2000}

    assert overpayment_breaks(after, payer_id="luis", payee_id="seph") == [
        Break(OVERPAYMENT, "luis", 6000),
    ]


# -- breaks 1 and 4: warnings on an expense proposal -----------------------------

SENT = datetime(2027, 2, 20, 21, 0, tzinfo=UTC)
TRIP = {"starts_on": date(2027, 2, 15), "ends_on": date(2027, 2, 25)}


def dinner(at=SENT, author="seph", cents=41200, description="jantar", code=""):
    return ExpenseIntent(author, cents, description, at, code)


def warnings_for(new, recent=(), occurred_on=date(2027, 2, 20)):
    return proposal_warnings(new, recent, occurred_on=occurred_on, **TRIP)


def test_the_same_dinner_two_minutes_later_is_break_1():
    earlier = dinner(code="K4")

    assert warnings_for(dinner(at=SENT + timedelta(minutes=2)), [earlier]) == (
        IntentDuplicate("K4", SENT),
    )


def test_exactly_ten_minutes_later_is_a_new_expense():
    assert warnings_for(dinner(at=SENT + timedelta(minutes=10)), [dinner()]) == ()


@pytest.mark.parametrize(
    "earlier",
    [dinner(cents=41300), dinner(author="vini"), dinner(description="almoco")],
)
def test_another_amount_author_or_description_is_no_duplicate(earlier):
    assert warnings_for(dinner(at=SENT + timedelta(minutes=2)), [earlier]) == ()


def test_descriptions_compare_without_case_accents_or_extra_spaces():
    earlier = ExpenseIntent("seph", 4680, "Pedagio", SENT, "B2")
    again = ExpenseIntent("seph", 4680, "  pedágio ", SENT + timedelta(minutes=1))

    assert warnings_for(again, [earlier]) == (IntentDuplicate("B2", SENT),)


def test_the_latest_earlier_proposal_is_the_one_named():
    first = dinner(code="K4")
    second = dinner(at=SENT + timedelta(minutes=3), code="M5")

    (warning,) = warnings_for(dinner(at=SENT + timedelta(minutes=5)), [first, second])
    assert warning.previous_code == "M5"


@pytest.mark.parametrize(
    "occurred_on", [date(2027, 2, 14), date(2027, 2, 26), date(2026, 2, 20)]
)
def test_a_date_outside_the_trip_is_break_4(occurred_on):
    assert warnings_for(dinner(), occurred_on=occurred_on) == (
        OutsideBookDates(occurred_on, date(2027, 2, 15), date(2027, 2, 25)),
    )


@pytest.mark.parametrize("occurred_on", [date(2027, 2, 15), date(2027, 2, 25)])
def test_the_first_and_last_days_are_inside_the_trip(occurred_on):
    assert warnings_for(dinner(), occurred_on=occurred_on) == ()
