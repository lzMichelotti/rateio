from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from ledger.model import Entry, EntryKind, Posting, Role, UnbalancedEntryError


def expense(*postings: Posting) -> Entry:
    return Entry(
        seq=1,
        kind=EntryKind.EXPENSE,
        occurred_on=date(2026, 12, 26),
        author_id="lotti",
        description="fuel",
        postings=postings,
    )


def test_a_balanced_entry_is_accepted():
    entry = expense(
        Posting("lotti", 1000, Role.OUTLAY),
        Posting("lotti", -500, Role.SHARE),
        Posting("luis", -500, Role.SHARE),
    )

    assert sum(p.amount_cents for p in entry.postings) == 0


def test_an_unbalanced_entry_cannot_exist():
    with pytest.raises(UnbalancedEntryError):
        expense(
            Posting("lotti", 1000, Role.OUTLAY),
            Posting("luis", -999, Role.SHARE),
        )


def test_an_entry_without_postings_cannot_exist():
    with pytest.raises(UnbalancedEntryError):
        expense()


def test_a_zero_posting_cannot_exist():
    with pytest.raises(ValueError):
        Posting("lotti", 0, Role.SHARE)


def test_an_entry_cannot_be_changed_after_creation():
    entry = expense(
        Posting("lotti", 1000, Role.OUTLAY),
        Posting("luis", -1000, Role.SHARE),
    )

    with pytest.raises(FrozenInstanceError):
        entry.description = "something else"
