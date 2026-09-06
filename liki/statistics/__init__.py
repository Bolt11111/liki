"""Auditable financial-statistics methods with explicit applicability states."""

from .inference import (
    Applicability,
    InferencePlan,
    MetricResult,
    SearchProvenance,
    deflated_sharpe_ratio,
    false_discovery_rate_bh,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    white_reality_check,
)
from .metrics import MetricDefinition, maximum_drawdown, simple_returns
from .resampling import stationary_bootstrap, stationary_bootstrap_matrix
from .robustness import (
    TransportabilityAssessment,
    block_bootstrap_mean_interval,
    leave_block_out_fragility,
    transportability_assessment,
)
from .validation import (
    CPCVSplit,
    PurgedFold,
    cpcv_splits,
    obrien_fleming_spending_boundaries,
    purged_kfold,
    sequential_z_test,
    walk_forward_splits,
)

__all__ = [
    "Applicability",
    "CPCVSplit",
    "InferencePlan",
    "MetricResult",
    "MetricDefinition",
    "PurgedFold",
    "SearchProvenance",
    "TransportabilityAssessment",
    "block_bootstrap_mean_interval",
    "cpcv_splits",
    "deflated_sharpe_ratio",
    "false_discovery_rate_bh",
    "leave_block_out_fragility",
    "obrien_fleming_spending_boundaries",
    "maximum_drawdown",
    "probabilistic_sharpe_ratio",
    "probability_of_backtest_overfitting",
    "purged_kfold",
    "sequential_z_test",
    "simple_returns",
    "stationary_bootstrap",
    "stationary_bootstrap_matrix",
    "transportability_assessment",
    "walk_forward_splits",
    "white_reality_check",
]
