"""Correcting an entry without touching it: a reversing entry that cancels it."""

from collections.abc import Iterable

from ledger.model import Entry, EntryKind, Posting
from ledger.refusal import Refusal, RefusalReason


class ReversalRefused(Refusal):
    """A reversal the ledger will not record. Subclasses carry the entry numbers
    so the channel layer can phrase the refusal for the group."""


class AlreadyReversedError(ReversalRefused):
    reason = RefusalReason.ALREADY_REVERSED

    def __init__(self, original_seq: int, reversal_seq: int) -> None:
        self.original_seq = original_seq
        self.reversal_seq = reversal_seq
        super().__init__(f"L{original_seq} was already reversed by L{reversal_seq}")


class ReversalOfReversalError(ReversalRefused):
    reason = RefusalReason.REVERSAL_OF_REVERSAL

    def __init__(self, seq: int, reverses_seq: int) -> None:
        self.seq = seq
        self.reverses_seq = reverses_seq
        super().__init__(f"L{seq} is the reversal of L{reverses_seq}")


def reverse(
    original: Entry,
    *,
    seq: int,
    author_id: str,
    book_entries: Iterable[Entry],
) -> Entry:
    """The entry that cancels `original`: every posting mirrored, sign flipped.

    Refuses to reverse a reversal, and to reverse an entry that book_entries show
    was already reversed (the database's partial unique index enforces the same
    rule against races and direct SQL; this check is what explains it).

    Roles are kept, so per-role aggregates (sum of outlays, sum of shares) net out
    on their own, and positions() needs no knowledge of reversals: original plus
    reversal is zero for every participant.

    The reversal inherits the original's occurred_on, so the business day of the
    mistake is the one that gets corrected; when the correction happened is the
    reversal's recorded_at, assigned by the store.
    """
    # Entry guarantees reverses_seq is set exactly when the kind is REVERSAL.
    if original.reverses_seq is not None:
        raise ReversalOfReversalError(original.seq, original.reverses_seq)
    for entry in book_entries:
        if entry.reverses_seq == original.seq:
            raise AlreadyReversedError(original.seq, entry.seq)

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
