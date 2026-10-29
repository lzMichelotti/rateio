"""Every refusal reason has exactly one kind of refusal behind it."""

from datetime import date

import pytest

from ledger.expense import PayerNotMemberError, record_expense
from ledger.refusal import NotPositiveAmountError, Refusal, RefusalReason
from store.confirmations import ConfirmationNotFoundError, NoFreeCodeError
from store.ledger import EntryNotFoundError

# The store's refusals are subclasses only once their modules are imported.
STORE_REFUSALS = {ConfirmationNotFoundError, EntryNotFoundError, NoFreeCodeError}


def concrete_refusals() -> list[type[Refusal]]:
    found, pending = [], list(Refusal.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if "reason" in vars(cls):
            found.append(cls)
    return found


def test_each_reason_is_declared_by_exactly_one_refusal():
    refusals = concrete_refusals()

    assert STORE_REFUSALS <= set(refusals)
    assert sorted(cls.reason for cls in refusals) == sorted(RefusalReason)


def expense(total_cents: int, payer_id: str = "lotti"):
    return record_expense(
        seq=1,
        occurred_on=date(2026, 12, 26),
        payer_id=payer_id,
        total_cents=total_cents,
        description="fuel",
        participant_ids=["lotti", "luis"],
    )


@pytest.mark.parametrize("total_cents", [0, -100])
def test_an_expense_that_is_not_positive_is_refused(total_cents):
    with pytest.raises(NotPositiveAmountError) as refused:
        expense(total_cents)

    assert refused.value.reason is RefusalReason.NOT_POSITIVE_AMOUNT
    assert refused.value.amount_cents == total_cents


def test_a_payer_outside_the_participants_is_refused():
    with pytest.raises(PayerNotMemberError) as refused:
        expense(10000, payer_id="vini")

    assert refused.value.reason is RefusalReason.PAYER_NOT_MEMBER
    assert refused.value.payer_id == "vini"
