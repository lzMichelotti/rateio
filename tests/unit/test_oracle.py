"""The oracle judges the plan, so the oracle is tested too."""

from oracle import minimum_transfers, partitions


def test_every_partition_is_generated_once():
    bell = [1, 1, 2, 5, 15, 52]

    for n, expected in enumerate(bell):
        generated = [
            sorted(sorted(group) for group in partition)
            for partition in partitions(list(range(n)))
        ]
        assert len(generated) == expected
        assert len({repr(p) for p in generated}) == expected


def test_nobody_owing_needs_no_transfer():
    assert minimum_transfers({}) == 0
    assert minimum_transfers({"lotti": 0, "luis": 0}) == 0


def test_a_pair_that_closes_on_its_own_saves_a_transfer():
    assert (
        minimum_transfers({"lotti": 4, "luis": 3, "seph": 2, "vini": -5, "vitor": -4})
        == 3
    )


def test_two_independent_pairs_need_two_transfers():
    assert minimum_transfers({"lotti": 1, "luis": -1, "seph": 2, "vini": -2}) == 2


def test_with_no_zero_sum_subgroup_everyone_but_one_pays():
    assert (
        minimum_transfers(
            {
                "lotti": 67208,
                "luis": 31545,
                "seph": -19912,
                "vini": -31792,
                "vitor": -47049,
            }
        )
        == 4
    )
