import numpy as np

from liki.statistics import (
    Applicability,
    SearchProvenance,
    deflated_sharpe_ratio,
    false_discovery_rate_bh,
    maximum_drawdown,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    white_reality_check,
)


def provenance() -> SearchProvenance:
    return SearchProvenance(
        trial_ledger_record_ids=("trial-1", "trial-2", "trial-3"),
        search_family_id="family-1",
        raw_adaptive_trials=3,
        effective_trial_estimates={"correlation.v1": 3.0},
        dataset_exposure_record_ids=("exposure-1",),
        method_versions={"correlation": "v1"},
    )


def test_psr_signal_exceeds_null_and_nonfinite_is_explicit():
    rng = np.random.default_rng(5)
    signal = rng.normal(0.003, 0.01, 500)
    null = rng.normal(0, 0.01, 500)
    assert (
        probabilistic_sharpe_ratio(signal, benchmark_sharpe=0, provenance=provenance()).value
        > probabilistic_sharpe_ratio(null, benchmark_sharpe=0, provenance=provenance()).value
    )
    assert (
        probabilistic_sharpe_ratio(
            [float("nan")], benchmark_sharpe=0, provenance=provenance()
        ).state
        == Applicability.NUMERIC_ERROR
    )


def test_dsr_requires_ledger_provenance_and_uses_full_trial_distribution():
    result = deflated_sharpe_ratio(
        [0.01] * 5,
        observed_trial_sharpes={"trial-1": 0.1, "trial-2": 0.2, "trial-3": 0.3},
        provenance=provenance(),
    )
    assert result.state == Applicability.UNDEFINED
    assert "trial-1" in result.provenance_ids


def test_pbo_and_fdr_return_auditable_values():
    matrix = np.tile(np.array([[0.01, 0.0], [0.0, 0.01]]), (4, 1))
    pbo = probability_of_backtest_overfitting(matrix, partitions=4, provenance=provenance())
    result, discovered = false_discovery_rate_bh(
        {"a": 0.001, "b": 0.03, "c": 0.9}, q=0.05, provenance=provenance()
    )
    assert pbo.state == Applicability.VALUE and 0 <= pbo.value <= 1
    assert result.state == Applicability.VALUE and discovered == ("a", "b")


def test_white_reality_check_null_is_not_significant():
    result = white_reality_check(
        np.zeros((50, 3)), block_length=5, replications=100, seed=8, provenance=provenance()
    )
    assert result.state == Applicability.VALUE and result.value == 1.0


def test_registered_metric_golden_fixture_and_heavy_tail_diagnostic():
    drawdown = maximum_drawdown([100, 120, 90, 110], provenance=provenance())
    assert drawdown.value == -0.25
    result = probabilistic_sharpe_ratio(
        [0.001] * 30 + [-0.2], benchmark_sharpe=0, provenance=provenance()
    )
    assert result.diagnostics is not None and result.diagnostics["tail_dominance_fraction"] > 0.9
