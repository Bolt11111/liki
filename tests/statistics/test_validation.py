from liki.statistics import (
    Applicability,
    SearchProvenance,
    cpcv_splits,
    obrien_fleming_spending_boundaries,
    purged_kfold,
    sequential_z_test,
    walk_forward_splits,
)


def provenance() -> SearchProvenance:
    return SearchProvenance(
        ("trial-1",), "family", 1, {"correlation.v1": 1}, ("exposure-1",), {"correlation": "v1"}
    )


def test_temporal_splits_purge_overlapping_events_and_walk_forward():
    ends = [min(index + 2, 11) for index in range(12)]
    folds = purged_kfold(ends, folds=3, embargo=1)
    for fold in folds:
        for train in fold.train_indices:
            assert all(not (train < test + 1 and ends[train] >= test) for test in fold.test_indices)
    assert len(cpcv_splits(ends, groups=3, test_groups=1, embargo=1)) == 3
    assert len(walk_forward_splits(10, train_size=4, test_size=2)) == 3


def test_sequential_z_test_requires_predeclared_design():
    result = sequential_z_test(
        [0.01, 0.02, 0.03],
        information_fractions=(0.5, 1.0),
        look_number=1,
        alpha=0.05,
        provenance=provenance(),
    )
    assert result.state == Applicability.VALUE
    invalid = sequential_z_test(
        [0.01, 0.02],
        information_fractions=(0.5, 1.0),
        look_number=3,
        alpha=0.05,
        provenance=provenance(),
    )
    assert invalid.state == Applicability.UNDEFINED


def test_obf_spending_schedule_is_strict_and_finishes_with_alpha_budget():
    boundaries = obrien_fleming_spending_boundaries(0.05, (0.25, 0.5, 0.75, 1.0))
    assert boundaries[0] > boundaries[-1] > 1.64
