"""The canonical commands: what the core accepts, whoever produced them.

The grammar produces them today and the interpreter will in stage 08. Each is a
proof that parsing happened: a RecordExpense exists only with a positive amount
in integer cents, a Confirm only with a well-formed code, a DeclareSettlement
only with a resolved participant id, never the text someone typed.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import ClassVar


class CommandKind(StrEnum):
    """The values of command.kind."""

    RECORD_EXPENSE = "record_expense"
    DECLARE_SETTLEMENT = "declare_settlement"
    CONFIRM = "confirm"
    REJECT = "reject"
    REVERSE = "reverse"
    SHOW_POSITION = "show_position"
    SHOW_STATEMENT = "show_statement"
    SHOW_SETTLEMENT_PLAN = "show_settlement_plan"
    HELP = "help"


@dataclass(frozen=True)
class RecordExpense:
    kind: ClassVar[CommandKind] = CommandKind.RECORD_EXPENSE
    amount_cents: int
    description: str
    occurred_on: date

    def payload(self) -> dict[str, object]:
        return {
            "amount_cents": self.amount_cents,
            "description": self.description,
            "occurred_on": self.occurred_on.isoformat(),
        }


@dataclass(frozen=True)
class DeclareSettlement:
    kind: ClassVar[CommandKind] = CommandKind.DECLARE_SETTLEMENT
    payee_id: str
    amount_cents: int

    def payload(self) -> dict[str, object]:
        return {"counterparty": self.payee_id, "amount_cents": self.amount_cents}


@dataclass(frozen=True)
class Confirm:
    kind: ClassVar[CommandKind] = CommandKind.CONFIRM
    code: str

    def payload(self) -> dict[str, object]:
        return {"code": self.code}


@dataclass(frozen=True)
class Reject:
    kind: ClassVar[CommandKind] = CommandKind.REJECT
    code: str

    def payload(self) -> dict[str, object]:
        return {"code": self.code}


@dataclass(frozen=True)
class Reverse:
    kind: ClassVar[CommandKind] = CommandKind.REVERSE
    seq: int

    def payload(self) -> dict[str, object]:
        return {"seq": self.seq}


@dataclass(frozen=True)
class ShowPosition:
    kind: ClassVar[CommandKind] = CommandKind.SHOW_POSITION

    def payload(self) -> dict[str, object]:
        return {}


@dataclass(frozen=True)
class ShowStatement:
    kind: ClassVar[CommandKind] = CommandKind.SHOW_STATEMENT
    limit: int

    def payload(self) -> dict[str, object]:
        return {"limit": self.limit}


@dataclass(frozen=True)
class ShowSettlementPlan:
    kind: ClassVar[CommandKind] = CommandKind.SHOW_SETTLEMENT_PLAN

    def payload(self) -> dict[str, object]:
        return {}


@dataclass(frozen=True)
class Help:
    kind: ClassVar[CommandKind] = CommandKind.HELP

    def payload(self) -> dict[str, object]:
        return {}


Command = (
    RecordExpense
    | DeclareSettlement
    | Confirm
    | Reject
    | Reverse
    | ShowPosition
    | ShowStatement
    | ShowSettlementPlan
    | Help
)
