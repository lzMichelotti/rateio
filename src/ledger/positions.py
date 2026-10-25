"""Positions are a projection of the postings, never stored state."""

from collections import defaultdict
from collections.abc import Iterable

from ledger.model import Posting


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
