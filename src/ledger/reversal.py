"""Correcting an entry without touching it: a reversing entry that cancels it."""

from ledger.model import Entry, EntryKind, Posting


def reverse(original: Entry, *, seq: int, author_id: str) -> Entry:
    """The entry that cancels `original`: every posting mirrored, sign flipped.

    Roles are kept, so per-role aggregates (sum of outlays, sum of shares) net out
    on their own, and positions() needs no knowledge of reversals: original plus
    reversal is zero for every participant.

    The reversal inherits the original's occurred_on, so the business day of the
    mistake is the one that gets corrected; when the correction happened is the
    reversal's recorded_at, assigned by the store.
    """
    return Entry(
        seq=seq,
        kind=EntryKind.REVERSAL,
        occurred_on=original.occurred_on,
        author_id=author_id,
        description=original.description,
        postings=tuple(
            Posting(p.participant_id, -p.amount_cents, p.role)
            for p in original.postings
        ),
        reverses_seq=original.seq,
    )
