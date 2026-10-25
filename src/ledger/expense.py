"""Turning "someone paid for the group" into a balanced entry."""

from collections.abc import Iterable
from datetime import date

from ledger.model import Entry, EntryKind, Posting, Role
from ledger.split import split_evenly


def record_expense(
    *,
    seq: int,
    occurred_on: date,
    payer_id: str,
    total_cents: int,
    description: str,
    participant_ids: Iterable[str],
) -> Entry:
    """An expense entry: one positive outlay for the payer, one negative share each.

    The payer keeps two postings (outlay and share) rather than one net leg, so
    "how much did each person pay" and "how much did each person consume" stay
    answerable. A participant whose share rounds to zero gets no posting: a zero
    leg moves no money and is refused by the schema.
    """
    ids = list(participant_ids)
    if payer_id not in ids:
        raise ValueError(f"payer {payer_id!r} is not among the participants")

    split = split_evenly(total_cents, ids, seq)
    shares = tuple(
        Posting(participant_id, -cents, Role.SHARE)
        for participant_id, cents in split.shares
        if cents > 0
    )
    return Entry(
        seq=seq,
        kind=EntryKind.EXPENSE,
        occurred_on=occurred_on,
        author_id=payer_id,
        description=description,
        postings=(Posting(payer_id, total_cents, Role.OUTLAY), *shares),
        remainder_offset=split.remainder_offset,
    )
