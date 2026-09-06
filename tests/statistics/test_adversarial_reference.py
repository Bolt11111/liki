"""Independent numerical checks and finite-sample null studies for statistical contracts."""

from itertools import combinations
from math import log

import numpy as np
import pytest
from scipy.stats import norm

from liki.statistics import (
    Applicability,
    SearchProvenance,
    deflated_sharpe_ratio,
    obrien_fleming_spending_boundaries,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    purged_kfold,
    sequential_z_test,
    stationary_bootstrap_matrix,
)


def provenance(n: int = 4, effective: float | None = None) -> SearchProvenance:
    identifiers = tuple(f"trial-{index}" for index in range(n))
    return SearchProvenance(
        identifiers,
        "family-full-history",
        n,
        {"correlation-clustering.v1": effective or float(n)},
        ("exposure-1",),
        {"correlation-clustering": "v1"},
    )


def test_psr_matches_independent_scipy_reference_formula():
    returns = np.array([-0.02, 0.01, 0.03, -0.01, 0.015, 0.025])
    result = probabilistic_sharpe_ratio(
        returns, benchmark_sharpe=0.2, annualization=4, provenance=provenance()
    )
    mean, std = np.mean(returns), np.std(returns, ddof=1)
    sharpe = mean / std * 2
    standardized = (returns - mean) / std
    denominator = np.sqrt(
        1 - np.mean(standardized**3) * sharpe + ((np.mean(standardized**4) - 1) / 4) * sharpe**2
    )
    expected = norm.cdf((sharpe - 0.2) * np.sqrt(len(returns) - 1) / denominator)
    assert result.state == Applicability.VALUE
    assert result.value == pytest.approx(expected, abs=1e-14)


def test_dsr_rejects_partial_history_and_uses_conservative_largest_effective_count():
    returns = [0.01, -0.005, 0.02, 0.01, -0.01]
    full = {f"trial-{index}": value for index, value in enumerate([0.1, 0.2, -0.1, 0.35])}
    result = deflated_sharpe_ratio(
        returns, observed_trial_sharpes=full, provenance=provenance(4, effective=4)
    )
    partial = deflated_sharpe_ratio(
        returns, observed_trial_sharpes={"trial-0": 0.1}, provenance=provenance(4, effective=4)
    )
    assert result.state == Applicability.VALUE
    assert partial.state == Applicability.NOT_APPLICABLE
    with pytest.raises(ValueError, match="cannot exceed raw history"):
        provenance(4, effective=5)


def test_pbo_matches_independent_contiguous_cscv_rank_calculation():
    matrix = np.array(
        [
            [0.04, 0.00, 0.01],
            [0.03, 0.00, 0.01],
            [0.00, 0.04, 0.01],
            [0.00, 0.03, 0.01],
            [0.01, 0.00, 0.04],
            [0.01, 0.00, 0.03],
            [0.02, 0.01, 0.00],
            [0.02, 0.01, 0.00],
        ]
    )
    result = probability_of_backtest_overfitting(matrix, partitions=4, provenance=provenance())
    blocks = np.array_split(matrix, 4)
    independently_computed = []
    for selected_blocks in combinations(range(4), 2):
        train = np.concatenate([blocks[index] for index in selected_blocks])
        test = np.concatenate([blocks[index] for index in range(4) if index not in selected_blocks])
        winner = int(np.argmax(np.mean(train, axis=0)))
        scores = np.mean(test, axis=0)
        rank = int(np.count_nonzero(scores <= scores[winner]))
        independently_computed.append(log(rank / (matrix.shape[1] + 1 - rank)) < 0)
    assert result.value == pytest.approx(np.mean(independently_computed))


def test_obf_spending_has_measured_null_family_error_below_alpha():
    alpha = 0.05
    fractions = np.array([0.25, 0.5, 0.75, 1.0])
    boundaries = np.array(obrien_fleming_spending_boundaries(alpha, fractions))
    rng = np.random.default_rng(311)
    increments = rng.normal(size=(100_000, 400))
    looks = np.cumsum(increments, axis=1)[:, (fractions * 400).astype(int) - 1] / np.sqrt(
        fractions * 400
    )
    estimated_family_error = np.mean(np.any(looks >= boundaries, axis=1))
    # The schedule spends no more than alpha by construction; sampling uncertainty is ~0.0007 here.
    assert estimated_family_error < alpha + 0.003
    assert estimated_family_error > 0.0


def test_sequential_interface_rejects_unscheduled_or_nonterminal_claims():
    invalid = sequential_z_test(
        [0.01, 0.02, 0.03],
        information_fractions=(0.5, 0.9),
        look_number=1,
        alpha=0.05,
        provenance=provenance(),
    )
    assert invalid.state == Applicability.UNDEFINED


def test_purge_removes_overlapping_labels_and_embargo_exactly_after_test_window():
    event_end_indices = [index + 3 if index < 9 else 11 for index in range(12)]
    folds = purged_kfold(event_end_indices, folds=3, embargo=2)
    middle = folds[1]
    assert middle.test_indices == (4, 5, 6, 7)
    assert middle.embargo_indices == (8, 9)
    for train_index in middle.train_indices:
        assert not any(
            train_index <= test_index <= event_end_indices[train_index]
            for test_index in middle.test_indices
        )


def test_dependence_bootstrap_uses_one_shared_index_path_for_every_strategy():
    matrix = np.column_stack((np.arange(20), np.arange(20) * 3, -np.arange(20)))
    resampled, indices = stationary_bootstrap_matrix(
        matrix, block_length=3, rng=np.random.default_rng(7)
    )
    assert np.array_equal(resampled, matrix[indices, :])
    assert np.array_equal(resampled[:, 1], resampled[:, 0] * 3)
