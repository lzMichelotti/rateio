from itertools import product

import pytest

from ledger.workflow import (
    Action,
    AlreadyResolvedError,
    ConfirmationKind,
    ConfirmationStatus,
    NotAPartyError,
    NotTheConfirmerError,
    SettlementNeverExpiresError,
    SettlementStatus,
    Transition,
    WorkflowRefused,
    transition_confirmation,
    transition_settlement,
)

OPEN, CONFIRMED, DISCARDED, EXPIRED = (
    ConfirmationStatus.OPEN,
    ConfirmationStatus.CONFIRMED,
    ConfirmationStatus.DISCARDED,
    ConfirmationStatus.EXPIRED,
)
EXPENSE = ConfirmationKind.EXPENSE_PROPOSAL
SETTLEMENT = ConfirmationKind.SETTLEMENT_DECLARATION


def expense(status, action, actor):
    """An expense proposal: lotti proposed it and lotti confirms it."""
    return transition_confirmation(
        EXPENSE, status, action, actor=actor, created_by="lotti", confirmer="lotti"
    )


def settlement_confirmation(status, action, actor):
    """luis declares he paid seph: seph is the confirmer."""
    return transition_confirmation(
        SETTLEMENT, status, action, actor=actor, created_by="luis", confirmer="seph"
    )


def settlement(status, action, actor):
    return transition_settlement(
        status, action, actor=actor, payer_id="luis", payee_id="seph"
    )


# -- confirmation ----------------------------------------------------------------


def test_the_author_confirms_an_expense_proposal():
    assert expense(OPEN, Action.CONFIRM, "lotti") == Transition(CONFIRMED, True)


def test_only_the_payee_confirms_a_settlement():
    assert settlement_confirmation(OPEN, Action.CONFIRM, "seph").status is CONFIRMED
    with pytest.raises(NotTheConfirmerError):
        settlement_confirmation(OPEN, Action.CONFIRM, "luis")
    with pytest.raises(NotTheConfirmerError):
        settlement_confirmation(OPEN, Action.CONFIRM, "vini")


def test_decline_on_a_settlement_from_either_party_discards_it():
    assert settlement_confirmation(OPEN, Action.DECLINE, "seph").status is DISCARDED
    assert settlement_confirmation(OPEN, Action.DECLINE, "luis").status is DISCARDED


def test_decline_from_a_third_person_is_refused():
    with pytest.raises(NotAPartyError):
        settlement_confirmation(OPEN, Action.DECLINE, "vini")
    with pytest.raises(NotAPartyError):
        expense(OPEN, Action.DECLINE, "vini")


def test_proposals_expire_but_settlements_never_do():
    assert expense(OPEN, Action.EXPIRE, None).status is EXPIRED
    with pytest.raises(SettlementNeverExpiresError):
        settlement_confirmation(OPEN, Action.EXPIRE, None)


def test_repeating_the_resolving_action_changes_nothing():
    assert expense(CONFIRMED, Action.CONFIRM, "lotti") == Transition(CONFIRMED, False)


def test_contradicting_a_resolved_confirmation_is_refused():
    with pytest.raises(AlreadyResolvedError):
        expense(DISCARDED, Action.CONFIRM, "lotti")
    with pytest.raises(AlreadyResolvedError):
        expense(CONFIRMED, Action.DECLINE, "lotti")


@pytest.mark.parametrize(
    ("kind", "status", "action", "actor"),
    list(
        product(
            ConfirmationKind,
            ConfirmationStatus,
            Action,
            [None, "luis", "seph", "vini"],
        )
    ),
)
def test_no_combination_passes_silently(kind, status, action, actor):
    """Every (kind, status, action, actor) is either a legal transition or an
    explained refusal, and a resolved confirmation never moves."""
    created_by, confirmer = ("luis", "seph") if kind is SETTLEMENT else ("luis", "luis")
    try:
        result = transition_confirmation(
            kind,
            status,
            action,
            actor=actor,
            created_by=created_by,
            confirmer=confirmer,
        )
    except (WorkflowRefused, ValueError):
        return
    if status is OPEN:
        assert result.changed and result.status is not OPEN
    else:
        assert not result.changed and result.status is status


# -- settlement ------------------------------------------------------------------


def test_settlement_three_senders_of_decline():
    assert settlement(SettlementStatus.DECLARED, Action.DECLINE, "seph").status is (
        SettlementStatus.REJECTED
    )
    assert settlement(SettlementStatus.DECLARED, Action.DECLINE, "luis").status is (
        SettlementStatus.CANCELLED
    )
    with pytest.raises(NotAPartyError):
        settlement(SettlementStatus.DECLARED, Action.DECLINE, "vini")


def test_settlement_is_confirmed_only_by_the_payee():
    assert settlement(SettlementStatus.DECLARED, Action.CONFIRM, "seph").status is (
        SettlementStatus.CONFIRMED
    )
    with pytest.raises(NotTheConfirmerError):
        settlement(SettlementStatus.DECLARED, Action.CONFIRM, "luis")


def test_a_rejected_settlement_cannot_be_cancelled_afterwards():
    with pytest.raises(AlreadyResolvedError):
        settlement(SettlementStatus.REJECTED, Action.DECLINE, "luis")


def test_a_settlement_never_expires():
    with pytest.raises(SettlementNeverExpiresError):
        settlement(SettlementStatus.DECLARED, Action.EXPIRE, None)
