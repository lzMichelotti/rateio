"""State machines for the conversation around a fact: confirmations and settlements.

Pure functions from (current state, action, who acts) to the next state or an
explained refusal. They decide; the store only carries out what they decided,
and its `UPDATE ... WHERE status = 'open'` covers the race these functions
cannot see.

A settlement is not a separate mechanism: it is a confirmation whose confirmer
(the payee) differs from its creator (the payer). When a settlement is rejected
or cancelled its confirmation is `discarded`; the settlement row records which.
"""

from dataclasses import dataclass
from enum import StrEnum

from ledger.refusal import Refusal, RefusalReason


class ConfirmationKind(StrEnum):
    EXPENSE_PROPOSAL = "expense_proposal"
    SETTLEMENT_DECLARATION = "settlement_declaration"
    REVERSAL_PROPOSAL = "reversal_proposal"


class ConfirmationStatus(StrEnum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"
    EXPIRED = "expired"


class SettlementStatus(StrEnum):
    DECLARED = "declared"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class Action(StrEnum):
    CONFIRM = "confirm"  # !ok
    DECLINE = "decline"  # !nao
    EXPIRE = "expire"  # the nightly job, never a person


class WorkflowRefused(Refusal):
    """A transition the workflow will not make. Subclasses carry the data the
    channel layer needs to explain it to the group."""


class NotTheConfirmerError(WorkflowRefused):
    reason = RefusalReason.NOT_THE_CONFIRMER

    def __init__(self, actor: str, confirmer: str) -> None:
        self.actor = actor
        self.confirmer = confirmer
        super().__init__(f"{actor} tried to confirm; the confirmer is {confirmer}")


class NotAPartyError(WorkflowRefused):
    reason = RefusalReason.NOT_A_PARTY

    def __init__(self, actor: str, allowed: tuple[str, ...]) -> None:
        self.actor = actor
        self.allowed = allowed
        super().__init__(f"{actor} tried to decline; allowed: {', '.join(allowed)}")


class AlreadyResolvedError(WorkflowRefused):
    reason = RefusalReason.ALREADY_RESOLVED

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"already {status}")


class SettlementNeverExpiresError(WorkflowRefused):
    reason = RefusalReason.SETTLEMENT_NEVER_EXPIRES

    def __init__(self) -> None:
        super().__init__("settlement declarations never expire")


@dataclass(frozen=True)
class Transition:
    status: ConfirmationStatus
    changed: bool  # False: the same action repeated on an already resolved state


@dataclass(frozen=True)
class SettlementTransition:
    status: SettlementStatus
    changed: bool


def transition_confirmation(
    kind: ConfirmationKind,
    status: ConfirmationStatus,
    action: Action,
    *,
    actor: str | None,
    created_by: str,
    confirmer: str,
) -> Transition:
    """The confirmation's next status, or a refusal.

    Who may act is checked first, so a stranger's !ok is refused as such even on
    a resolved confirmation. Repeating the action that resolved it changes
    nothing and is not an error (!ok is idempotent); a contradicting action is
    refused.
    """
    target = _confirmation_target(kind, action, actor, created_by, confirmer)
    if status is ConfirmationStatus.OPEN:
        return Transition(target, changed=True)
    if status is target:
        return Transition(target, changed=False)
    raise AlreadyResolvedError(status.value)


def transition_settlement(
    status: SettlementStatus,
    action: Action,
    *,
    actor: str | None,
    payer_id: str,
    payee_id: str,
) -> SettlementTransition:
    """The settlement's next status, or a refusal.

    Only the payee confirms. !nao from the payee rejects ("it never arrived"),
    from the payer cancels ("I didn't send it after all"), from anyone else is
    refused. A settlement never expires.
    """
    target = _settlement_target(action, actor, payer_id, payee_id)
    if status is SettlementStatus.DECLARED:
        return SettlementTransition(target, changed=True)
    if status is target:
        return SettlementTransition(target, changed=False)
    raise AlreadyResolvedError(status.value)


def _confirmation_target(
    kind: ConfirmationKind,
    action: Action,
    actor: str | None,
    created_by: str,
    confirmer: str,
) -> ConfirmationStatus:
    if action is Action.EXPIRE:
        if actor is not None:
            raise ValueError("expiry is a system action, not a participant's")
        if kind is ConfirmationKind.SETTLEMENT_DECLARATION:
            raise SettlementNeverExpiresError()
        return ConfirmationStatus.EXPIRED

    if actor is None:
        raise ValueError(f"{action.value} needs a participant")
    if action is Action.CONFIRM:
        if actor != confirmer:
            raise NotTheConfirmerError(actor, confirmer)
        return ConfirmationStatus.CONFIRMED

    allowed: tuple[str, ...] = (confirmer,)
    if kind is ConfirmationKind.SETTLEMENT_DECLARATION:
        allowed = (confirmer, created_by)  # payee rejects, payer cancels
    if actor not in allowed:
        raise NotAPartyError(actor, allowed)
    return ConfirmationStatus.DISCARDED


def _settlement_target(
    action: Action, actor: str | None, payer_id: str, payee_id: str
) -> SettlementStatus:
    if action is Action.EXPIRE:
        raise SettlementNeverExpiresError()
    if actor is None:
        raise ValueError(f"{action.value} needs a participant")
    if action is Action.CONFIRM:
        if actor != payee_id:
            raise NotTheConfirmerError(actor, payee_id)
        return SettlementStatus.CONFIRMED
    if actor == payee_id:
        return SettlementStatus.REJECTED
    if actor == payer_id:
        return SettlementStatus.CANCELLED
    raise NotAPartyError(actor, (payee_id, payer_id))
