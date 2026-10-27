"""Positions are a projection of the postings, never stored state."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from ledger.model import Posting, Role


def positions(postings: Iterable[Posting]) -> dict[str, int]:
    """Net cents per participant, sorted by participant id.

    Positive means the book owes that participant; negative means they owe the
    book. Over a whole book the values always sum to zero. Participants with no
    postings are absent; callers that display everyone fill those in with zero.
    """
    totals: defaultdict[str, int] = defaultdict(int)
    for posting in postings:
        totals[posting.participant_id] += posting.amount_cents
    return dict(sorted(totals.items()))


@dataclass(frozen=True)
class ParticipantSummary:
    """One participant's postings totalled by role, with the signs they carry.

    share and settlement_received are zero or negative, outlay and
    settlement_paid zero or positive, except where an overpayment flips one. The
    position is derived from the four, so the summary cannot contradict itself.
    """

    participant_id: str
    outlay_cents: int
    share_cents: int
    settlement_paid_cents: int
    settlement_received_cents: int

    @property
    def position_cents(self) -> int:
        return (
            self.outlay_cents
            + self.share_cents
            + self.settlement_paid_cents
            + self.settlement_received_cents
        )


@dataclass(frozen=True)
class PositionSummary:
    """Every participant's role totals, sorted by participant id."""

    participants: tuple[ParticipantSummary, ...]

    @property
    def total_spent_cents(self) -> int:
        """What the trip cost: sum(outlay), which always equals -sum(share)."""
        return sum(p.outlay_cents for p in self.participants)


def position_summary(postings: Iterable[Posting]) -> PositionSummary:
    """Totals by role per participant.

    Reversals need no special case: they mirror the original's roles, so every
    total is already net of them. Participants with no postings are absent, as
    in positions().
    """
    totals: defaultdict[str, defaultdict[Role, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for posting in postings:
        totals[posting.participant_id][posting.role] += posting.amount_cents
    return PositionSummary(
        tuple(
            ParticipantSummary(
                participant_id=pid,
                outlay_cents=by_role[Role.OUTLAY],
                share_cents=by_role[Role.SHARE],
                settlement_paid_cents=by_role[Role.SETTLEMENT_PAID],
                settlement_received_cents=by_role[Role.SETTLEMENT_RECEIVED],
            )
            for pid, by_role in sorted(totals.items())
        )
    )
