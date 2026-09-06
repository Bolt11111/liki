from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from liki.portfolio import (
    AllocationConstraints, AllocationMethod, Attribution, CapitalState, PathSimulationConfig, PortfolioModel,
    PortfolioObservation, ReverseStressConfig, Scenario, StrategyDefinition, analyze_portfolio, simulate_ruin,
)


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _strategies():
    return (
        StrategyDefinition(strategy_version_id="alpha", asset_id="BTC", venue_id="x", capacity_fraction="0.8", liquidity_stress_loss_fraction="0.1", net_directional_fraction="1", common_dependencies=("feed-a",), factor_loadings={"market": "1"}),
        StrategyDefinition(strategy_version_id="beta", asset_id="ETH", venue_id="y", capacity_fraction="0.8", liquidity_stress_loss_fraction="0.2", net_directional_fraction="-1", common_dependencies=("feed-b",), factor_loadings={"market": "-0.5"}),
    )


def _observations():
    values = (("0.02", "0.01", "normal"), ("-0.01", "-0.015", "normal"), ("0.01", "-0.002", "stress"), ("-0.03", "-0.04", "stress"), ("0.012", "0.004", "stress"), ("0.005", "0.002", "normal"))
    return tuple(PortfolioObservation(observed_at=NOW + timedelta(hours=index), simple_returns={"alpha": left, "beta": right}, regime=regime) for index, (left, right, regime) in enumerate(values))


def _constraints():
    return AllocationConstraints(gross_target="0.8", max_strategy_weight="0.6", max_asset_fraction="0.6", max_venue_fraction="0.6", max_turnover_fraction="1", max_liquidity_fraction="0.8")


def _model(method=AllocationMethod.MINIMUM_VARIANCE):
    return PortfolioModel(model_id="minimum-variance", version="1", allocation_method=method, covariance_shrinkage="0.2", return_shrinkage="0.5", tail_confidence="0.8", assumptions=("synchronized returns",), limitations=("historical covariance can break",))


def test_analysis_is_synchronized_constrained_and_reconciles_attribution():
    analysis = analyze_portfolio(
        _strategies(), _observations(), _constraints(), _model(), Decimal("1000"),
        scenarios=(Scenario(scenario_id="venue-and-liquidity", strategy_return_shocks={"alpha": "-0.2", "beta": "-0.2"}, slippage_and_impact_loss="10", funding_and_borrow_loss="5", collateral_and_fx_loss="15", venue_default_loss="20", liquidity_feedback_multiplier="1.5", recovery_assumption="0.5"),),
        attributions=(Attribution(strategy_version_id="alpha", instrument_id="BTC-USD", venue_id="x", gross_market_pnl="30", execution_cost="2", fees="1", funding_and_borrow="1", collateral_and_fx="0", net_pnl="26"),),
        prior_weights={"alpha": Decimal("0.4"), "beta": Decimal("0.4")},
        capital_state=CapitalState(reporting_currency="USD", immediately_withdrawable="100", margin_encumbered="500", trapped_by_positions_or_orders="200", withdrawal_delayed="100", valuation_artifact_id="valuation-artifact"),
        reverse_stress=ReverseStressConfig(target_loss_fraction="0.2", strategy_return_shocks={"alpha": "-0.4", "beta": "-0.4"}, slippage_and_impact_loss="10", funding_and_borrow_loss="5", collateral_and_fx_loss="15", venue_default_loss="20", liquidity_feedback_multiplier="1.5", recovery_assumption="0.5", uncertain_assumptions=("exit depth",)),
    )
    assert sum(analysis.allocation.weights.values()) == Decimal("0.8")
    assert all(weight <= Decimal("0.6") for weight in analysis.allocation.weights.values())
    assert analysis.challenger.method == AllocationMethod.EQUAL_WEIGHT
    assert analysis.risk.net_directional_exposure != analysis.risk.gross_exposure
    assert analysis.risk.expected_shortfall.state.value == "VALUE"
    assert analysis.risk.turnover.state.value == "VALUE"
    assert analysis.risk.common_driver_exposure["dependency:feed-a"] > Decimal("0")
    assert analysis.risk.capital_state is not None
    assert analysis.scenarios["venue-and-liquidity"]["loss"] > Decimal("0")
    assert analysis.reverse_stress is not None
    assert analysis.reverse_stress["survival_breach_reachable"] is True
    assert analysis.authoritative_performance is True
    assert analysis.attribution_residual == Decimal("0")


def test_analysis_rejects_missing_common_clock_and_reports_unreconciled_pnl():
    bad = list(_observations())
    bad[2] = bad[2].model_copy(update={"simple_returns": {"alpha": Decimal("0.01")}})
    with pytest.raises(ValueError, match="exactly"):
        analyze_portfolio(_strategies(), bad, _constraints(), _model(), Decimal("1000"))
    analysis = analyze_portfolio(_strategies(), _observations(), _constraints(), _model(), Decimal("1000"), attributions=(Attribution(strategy_version_id="alpha", instrument_id="BTC-USD", venue_id="x", gross_market_pnl="30", execution_cost="2", fees="1", funding_and_borrow="1", collateral_and_fx="0", net_pnl="27"),), attribution_tolerance=Decimal("0"))
    assert analysis.attribution_residual == Decimal("1")
    assert analysis.authoritative_performance is False


def test_optimizer_preserves_declared_method_and_compounds_returns_for_drawdown():
    inverse = analyze_portfolio(_strategies(), _observations(), _constraints(), _model(AllocationMethod.INVERSE_VOLATILITY), Decimal("1000"))
    minimum_variance = analyze_portfolio(_strategies(), _observations(), _constraints(), _model(), Decimal("1000"))
    assert inverse.allocation.method is AllocationMethod.INVERSE_VOLATILITY
    assert inverse.risk.maximum_drawdown.metric_id == "maximum_drawdown"
    assert inverse.risk.maximum_drawdown.version == "1"
    assert inverse.risk.turnover.state.value == "NOT_APPLICABLE"
    assert inverse.allocation.weights != minimum_variance.allocation.weights


def test_reverse_stress_reports_when_declared_maximum_cannot_breach_target():
    analysis = analyze_portfolio(
        _strategies(), _observations(), _constraints(), _model(), Decimal("1000"),
        reverse_stress=ReverseStressConfig(target_loss_fraction="0.95", strategy_return_shocks={"alpha": "-0.01", "beta": "-0.01"}, slippage_and_impact_loss="0", funding_and_borrow_loss="0", collateral_and_fx_loss="0", venue_default_loss="0", liquidity_feedback_multiplier="1", recovery_assumption="0", uncertain_assumptions=("declared shock ceiling",)),
    )
    assert analysis.reverse_stress is not None
    assert analysis.reverse_stress["survival_breach_reachable"] is False


def test_seeded_path_simulation_is_reproducible_and_explicit_about_uncertainty():
    config = PathSimulationConfig(seed=7, paths=500, horizon_periods=12, starting_equity="1000", ruin_drawdown_fraction="0.25", edge_decay_fraction="0.5", correlation_stress_multiplier="1.4", per_period_cost_fraction="0.001", shock_probability_per_period="0.2", shock_loss_fraction="0.05", block_length=2)
    weights = {"alpha": Decimal("0.5"), "beta": Decimal("0.5")}
    first = simulate_ruin(_observations(), ("alpha", "beta"), weights, config)
    second = simulate_ruin(_observations(), ("alpha", "beta"), weights, config)
    assert first == second
    assert first.evidence_kind.value == "MODEL_ESTIMATE"
    assert "Monte Carlo" in first.uncertainty_reason
