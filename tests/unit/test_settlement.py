import pytest

from ledger.settlement import DeclarationRefused, ExceedsDebtError, validate_declaration

# luis owes 100 to the group; seph is owed 100.
POSITIONS = {"lotti": 0, "luis": -10000, "seph": 10000}


def declare(amount_cents, payer_id="luis", payee_id="seph"):
    validate_declaration(
        POSITIONS, payer_id=payer_id, payee_id=payee_id, amount_cents=amount_cents
    )


def test_paying_exactly_the_debt_is_accepted():
    declare(10000)


def test_paying_part_of_the_debt_is_accepted():
    declare(4000)


def test_one_cent_above_the_debt_is_refused():
    with pytest.raises(ExceedsDebtError) as refused:
        declare(10001)

    assert (refused.value.amount_cents, refused.value.debt_cents) == (10001, 10000)


def test_someone_who_owes_nothing_cannot_declare_a_payment():
    with pytest.raises(ExceedsDebtError) as refused:
        declare(100, payer_id="seph", payee_id="luis")

    assert refused.value.debt_cents == 0


@pytest.mark.parametrize(
    ("amount_cents", "payer_id", "payee_id"),
    [(0, "luis", "seph"), (-100, "luis", "seph"), (100, "luis", "luis")],
)
def test_nonsense_declarations_are_refused(amount_cents, payer_id, payee_id):
    with pytest.raises(DeclarationRefused):
        declare(amount_cents, payer_id, payee_id)
