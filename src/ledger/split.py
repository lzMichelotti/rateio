"""Even split of a total in integer cents, with a deterministic rotating remainder."""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Split:
    """Each participant's share, sorted by participant id, and the offset used."""

    shares: tuple[tuple[str, int], ...]
    remainder_offset: int


def split_evenly(total_cents: int, participant_ids: Iterable[str], seq: int) -> Split:
    """Divide total_cents among the participants. Never rounds, never loses a cent.

    Every participant gets total // n. The total % n leftover cents go one each
    to the participants at positions offset, offset + 1, ... (wrapping), where
    offset = seq % n over the participants sorted by id. The offset rotates with
    the entry sequence, so no one always absorbs the remainder, and it depends
    only on stored data, so a replay reproduces the same numbers.
    """
    ids = sorted(participant_ids)
    if total_cents <= 0:
        raise ValueError(f"total must be positive, got {total_cents}")
    if not ids:
        raise ValueError("cannot split among zero participants")
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate participant ids: {ids}")

    n = len(ids)
    base, remainder = divmod(total_cents, n)
    offset = seq % n
    gets_extra_cent = {(offset + i) % n for i in range(remainder)}

    shares = tuple(
        (participant_id, base + 1 if position in gets_extra_cent else base)
        for position, participant_id in enumerate(ids)
    )
    return Split(shares=shares, remainder_offset=offset)
