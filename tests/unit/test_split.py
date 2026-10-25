import pytest

from ledger.split import split_evenly

FIVE = ["vitor", "lotti", "vini", "luis", "seph"]  # deliberately unsorted


def test_remainder_starts_at_the_offset():
    # 18743 / 5 = 3748 remainder 3; seq 2 -> offset 2 -> seph, vini, vitor.
    split = split_evenly(18743, FIVE, seq=2)

    assert split.remainder_offset == 2
    assert split.shares == (
        ("lotti", 3748),
        ("luis", 3748),
        ("seph", 3749),
        ("vini", 3749),
        ("vitor", 3749),
    )


def test_remainder_wraps_past_the_end():
    # seq 4 -> offset 4 -> vitor, then wraps to lotti and luis.
    split = split_evenly(18743, FIVE, seq=4)

    assert dict(split.shares) == {
        "lotti": 3749,
        "luis": 3749,
        "seph": 3748,
        "vini": 3748,
        "vitor": 3749,
    }


def test_exact_division_has_no_extra_cents():
    split = split_evenly(30000, FIVE, seq=7)

    assert {cents for _, cents in split.shares} == {6000}


def test_shares_sum_to_the_total():
    split = split_evenly(18743, FIVE, seq=2)

    assert sum(cents for _, cents in split.shares) == 18743


@pytest.mark.parametrize(
    ("total_cents", "participant_ids"),
    [
        (0, FIVE),
        (-100, FIVE),
        (100, []),
        (100, ["lotti", "lotti"]),
    ],
)
def test_nonsense_input_is_refused(total_cents, participant_ids):
    with pytest.raises(ValueError):
        split_evenly(total_cents, participant_ids, seq=1)
