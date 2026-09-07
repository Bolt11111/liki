"""Closed-interval reference checks independent of the production purge predicate."""

from itertools import combinations, product

import numpy as np
import pytest

from liki.statistics import cpcv_splits, purged_kfold, walk_forward_splits
from liki.statistics import validation


@pytest.mark.parametrize("method", [purged_kfold, cpcv_splits])
def test_extended_test_label_purges_future_training_and_moves_embargo(method):
    ends = [0, 4, 2, 3, 4, 5, 6, 7]
    configuration = {"folds": 4} if method is purged_kfold else {"groups": 4, "test_groups": 1}
    first = method(ends, embargo=1, **configuration)[0]
    assert first.test_indices == (0, 1)
    assert first.embargo_indices == (5,)
    assert first.train_indices == (6, 7)


def test_closed_endpoints_purge_past_and_future_training():
    middle = purged_kfold([2, 1, 4, 3, 4, 5], folds=3, embargo=0)[1]
    assert middle.test_indices == (2, 3)
    assert middle.train_indices == (1, 5)
    assert middle.embargo_indices == ()


def test_cpcv_disjoint_test_groups_preserve_the_uncontaminated_gap():
    split = cpcv_splits(list(range(12)), groups=4, test_groups=2, embargo=1)[1]
    assert split.test_indices == (0, 1, 2, 6, 7, 8)
    assert split.embargo_indices == (3, 9)
    assert split.train_indices == (4, 5, 10, 11)


def test_cpcv_embargo_uses_each_groups_maximum_label_end_and_excludes_test_indices():
    ends = list(range(12))
    ends[0] = 7
    split = cpcv_splits(ends, groups=4, test_groups=2, embargo=2)[1]
    assert split.test_indices == (0, 1, 2, 6, 7, 8)
    assert split.embargo_indices == (9, 10)
    assert split.train_indices == (11,)


def test_cpcv_adjacent_test_groups_never_appear_in_embargo():
    split = cpcv_splits(list(range(8)), groups=4, test_groups=2, embargo=1)[0]
    assert split.test_indices == (0, 1, 2, 3)
    assert split.embargo_indices == (4,)
    assert split.train_indices == (5, 6, 7)


@pytest.mark.parametrize("method", [purged_kfold, cpcv_splits])
def test_dataset_end_clips_embargo_and_can_leave_no_training_data(method):
    configuration = {"folds": 2} if method is purged_kfold else {"groups": 2, "test_groups": 1}
    first = method([3, 1, 2, 3], embargo=100, **configuration)[0]
    assert first.test_indices == (0, 1)
    assert first.embargo_indices == ()
    assert first.train_indices == ()


def _occupied_time_oracle(ends, test_blocks, embargo):
    test = set().union(*test_blocks)
    occupied_test_time = set().union(*(set(range(index, ends[index] + 1)) for index in test))
    embargoed = set()
    for block in test_blocks:
        occupied_block_time = set().union(*(set(range(index, ends[index] + 1)) for index in block))
        horizon = max(occupied_block_time)
        embargoed.update(index for index in range(len(ends)) if 0 < index - horizon <= embargo)
    embargoed -= test
    train = {
        index
        for index in range(len(ends))
        if index not in test | embargoed
        and set(range(index, ends[index] + 1)).isdisjoint(occupied_test_time)
    }
    return tuple(sorted(train)), tuple(sorted(test)), tuple(sorted(embargoed))


def _assert_matches_oracle(split, expected):
    actual = split.train_indices, split.test_indices, split.embargo_indices
    assert actual == expected
    for indices in actual:
        assert indices == tuple(sorted(set(indices)))
    for left, right in combinations(actual, 2):
        assert set(left).isdisjoint(right)


@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_exhaustive_small_intervals_against_independent_occupied_time_oracle(n):
    for ends in product(*(range(index, n) for index in range(n))):
        for group_count in range(2, n + 1):
            blocks = [
                set(range(n * group // group_count, n * (group + 1) // group_count))
                for group in range(group_count)
            ]
            for embargo in range(n + 2):
                folds = purged_kfold(ends, folds=group_count, embargo=embargo)
                assert len(folds) == group_count
                assert sorted(index for fold in folds for index in fold.test_indices) == list(
                    range(n)
                )
                for split, block in zip(folds, blocks, strict=True):
                    _assert_matches_oracle(split, _occupied_time_oracle(ends, [block], embargo))
                for test_count in range(1, group_count):
                    splits = cpcv_splits(
                        ends, groups=group_count, test_groups=test_count, embargo=embargo
                    )
                    selections = tuple(combinations(blocks, test_count))
                    assert len(splits) == len(selections)
                    for split, selected in zip(splits, selections, strict=True):
                        _assert_matches_oracle(
                            split, _occupied_time_oracle(ends, selected, embargo)
                        )


@pytest.mark.parametrize("method", [purged_kfold, cpcv_splits])
@pytest.mark.parametrize(
    "bad_end", [-1, 4, 0.5, 0.0, float("nan"), float("inf"), "0", None, True, np.bool_(False)]
)
def test_invalid_event_ends_fail_closed(method, bad_end):
    configuration = {"folds": 2} if method is purged_kfold else {"groups": 2, "test_groups": 1}
    with pytest.raises(ValueError, match="event end indices"):
        method([bad_end, 1, 2, 3], embargo=0, **configuration)


@pytest.mark.parametrize("method", [purged_kfold, cpcv_splits])
def test_event_end_cannot_precede_its_own_decision_index(method):
    configuration = {"folds": 2} if method is purged_kfold else {"groups": 2, "test_groups": 1}
    with pytest.raises(ValueError, match="event end indices"):
        method([0, 0, 2, 3], embargo=0, **configuration)


@pytest.mark.parametrize("method", [purged_kfold, cpcv_splits])
@pytest.mark.parametrize("ends", [[], [0]])
def test_insufficient_events_cannot_form_empty_test_groups(method, ends):
    configuration = {"folds": 2} if method is purged_kfold else {"groups": 2, "test_groups": 1}
    with pytest.raises(ValueError):
        method(ends, embargo=0, **configuration)


@pytest.mark.parametrize("method", [purged_kfold, cpcv_splits])
@pytest.mark.parametrize("bad_value", [-1, 1.0, 0.5, float("nan"), float("inf"), "1", None, True])
def test_invalid_temporal_configuration_types_and_embargo_fail_closed(method, bad_value):
    configuration = {"folds": 2, "embargo": 0}
    if method is cpcv_splits:
        configuration = {"groups": 2, "test_groups": 1, "embargo": 0}
    for field in configuration:
        with pytest.raises(ValueError):
            method(list(range(4)), **(configuration | {field: bad_value}))


@pytest.mark.parametrize("groups", [0, 1, 5])
def test_group_counts_must_produce_at_least_two_nonempty_groups(groups):
    with pytest.raises(ValueError):
        purged_kfold(list(range(4)), folds=groups, embargo=0)
    with pytest.raises(ValueError):
        cpcv_splits(list(range(4)), groups=groups, test_groups=1, embargo=0)


@pytest.mark.parametrize("test_groups", [0, 3, 4])
def test_cpcv_requires_nonempty_test_and_held_out_group_sets(test_groups):
    with pytest.raises(ValueError):
        cpcv_splits(list(range(6)), groups=3, test_groups=test_groups, embargo=0)


def test_cpcv_rejects_pathological_combination_count_before_enumeration(monkeypatch):
    def unexpected_enumeration(*args):
        raise AssertionError("CPCV combinations must be bounded before enumeration")

    monkeypatch.setattr(validation, "combinations", unexpected_enumeration)
    with pytest.raises(ValueError, match="10000 splits"):
        cpcv_splits(list(range(20)), groups=20, test_groups=10, embargo=0)


def test_numpy_integral_indices_and_configurations_are_supported():
    ends = np.arange(6, dtype=np.int64)
    assert purged_kfold(ends, folds=np.int64(3), embargo=np.int64(1)) == purged_kfold(
        list(range(6)), folds=3, embargo=1
    )
    assert cpcv_splits(ends, groups=np.int64(3), test_groups=np.int64(1), embargo=np.int64(1)) == (
        cpcv_splits(list(range(6)), groups=3, test_groups=1, embargo=1)
    )


@pytest.mark.parametrize("bad_value", [0, -1, 1.0, 0.5, float("nan"), float("inf"), "1", True])
def test_walk_forward_requires_positive_integral_sizes_and_step(bad_value):
    configuration = {"n_observations": 8, "train_size": 2, "test_size": 2, "step": 1}
    for field in configuration:
        with pytest.raises(ValueError):
            walk_forward_splits(**(configuration | {field: bad_value}))


def test_walk_forward_defaults_only_an_omitted_step_and_preserves_chronology():
    expected = (((0, 1), (2, 3)), ((2, 3), (4, 5)))
    assert walk_forward_splits(6, train_size=2, test_size=2) == expected
    assert walk_forward_splits(6, train_size=2, test_size=2, step=None) == expected
    assert walk_forward_splits(6, train_size=2, test_size=2, step=3) == (expected[0],)
    assert walk_forward_splits(3, train_size=2, test_size=2) == ()
