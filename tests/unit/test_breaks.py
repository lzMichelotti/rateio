from ledger.breaks import OVERPAYMENT, Break, overpayment_breaks


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
