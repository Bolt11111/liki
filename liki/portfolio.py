"""Deterministic, research-only portfolio allocation and risk analysis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from math import sqrt

import numpy as np
from pydantic import Field, field_validator, model_validator
from scipy.optimize import minimize

from liki.core import Contract
from liki.finance import BoundedValue, EvidenceKind, MetricResult, expected_shortfall, max_drawdown
from liki.finance.portfolio import component_risk, shrunk_covariance
from liki.finance.types import MetricState, ZERO, decimal

__all__ = [
    "AllocationConstraints", "AllocationMethod", "AllocationResult", "Attribution", "CapitalState",
    "PathSimulationConfig", "PortfolioAnalysis", "PortfolioModel", "PortfolioObservation",
    "PortfolioRiskView", "ReverseStressConfig", "Scenario", "StrategyDefinition", "StrategyHealth",
    "StrategyStatusTransition", "analyze_portfolio", "simulate_ruin",
]


class AllocationMethod(StrEnum):
    EQUAL_WEIGHT = "EQUAL_WEIGHT"
    INVERSE_VOLATILITY = "INVERSE_VOLATILITY"
    MINIMUM_VARIANCE = "MINIMUM_VARIANCE"


class StrategyHealth(StrEnum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    DEGRADED = "DEGRADED"
    SUSPENDED = "SUSPENDED"
    DORMANT = "DORMANT"
    RETIRED = "RETIRED"


def _finite_decimal(value: object) -> Decimal:
    return decimal(value)  # type: ignore[arg-type]


class StrategyDefinition(Contract):
    strategy_version_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    venue_id: str = Field(min_length=1)
    capacity_fraction: Decimal = Field(gt=0, le=1)
    liquidity_stress_loss_fraction: Decimal = Field(ge=0, le=1)
    net_directional_fraction: Decimal = Field(ge=-1, le=1)
    common_dependencies: tuple[str, ...] = ()
    factor_loadings: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("capacity_fraction", "liquidity_stress_loss_fraction", "net_directional_fraction", mode="before")
    @classmethod
    def parse_fraction(cls, value: object) -> Decimal:
        return _finite_decimal(value)

    @field_validator("factor_loadings", mode="before")
    @classmethod
    def parse_factor_loadings(cls, value: object) -> dict[str, Decimal]:
        if not isinstance(value, Mapping):
            raise TypeError("factor_loadings must be keyed by explicit factor name")
        return {str(key): _finite_decimal(item) for key, item in value.items()}


class PortfolioObservation(Contract):
    """One common-clock, simple-return observation for every included strategy."""

    observed_at: datetime
    simple_returns: dict[str, Decimal]
    regime: str = Field(min_length=1)

    @field_validator("simple_returns", mode="before")
    @classmethod
    def parse_returns(cls, value: object) -> dict[str, Decimal]:
        if not isinstance(value, Mapping):
            raise TypeError("simple_returns must be keyed by strategy version id")
        return {str(key): _finite_decimal(item) for key, item in value.items()}

    @model_validator(mode="after")
    def complete_clock_and_timestamp(self) -> PortfolioObservation:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be a timezone-aware datetime")
        if not self.simple_returns:
            raise ValueError("at least one synchronized return is required")
        return self


class AllocationConstraints(Contract):
    gross_target: Decimal = Field(gt=0, le=1)
    max_strategy_weight: Decimal = Field(gt=0, le=1)
    max_asset_fraction: Decimal = Field(gt=0, le=1)
    max_venue_fraction: Decimal = Field(gt=0, le=1)
    max_turnover_fraction: Decimal = Field(ge=0, le=1)
    max_liquidity_fraction: Decimal = Field(gt=0, le=1)

    @field_validator(
        "gross_target", "max_strategy_weight", "max_asset_fraction", "max_venue_fraction",
        "max_turnover_fraction", "max_liquidity_fraction", mode="before",
    )
    @classmethod
    def parse_fraction(cls, value: object) -> Decimal:
        return _finite_decimal(value)


class PortfolioModel(Contract):
    model_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    allocation_method: AllocationMethod
    covariance_shrinkage: Decimal = Field(ge=0, le=1)
    return_shrinkage: Decimal = Field(ge=0, le=1)
    tail_confidence: Decimal = Field(gt=0, lt=1)
    assumptions: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)

    @field_validator("covariance_shrinkage", "return_shrinkage", "tail_confidence", mode="before")
    @classmethod
    def parse_fraction(cls, value: object) -> Decimal:
        return _finite_decimal(value)


class Scenario(Contract):
    scenario_id: str = Field(min_length=1)
    strategy_return_shocks: dict[str, Decimal]
    slippage_and_impact_loss: Decimal = Field(ge=0)
    funding_and_borrow_loss: Decimal = Field(ge=0)
    collateral_and_fx_loss: Decimal = Field(ge=0)
    venue_default_loss: Decimal = Field(ge=0)
    liquidity_feedback_multiplier: Decimal = Field(ge=1)
    recovery_assumption: Decimal = Field(ge=0, le=1)

    @field_validator(
        "strategy_return_shocks", "slippage_and_impact_loss", "funding_and_borrow_loss",
        "collateral_and_fx_loss", "venue_default_loss", "liquidity_feedback_multiplier",
        "recovery_assumption", mode="before",
    )
    @classmethod
    def parse_numbers(cls, value: object) -> object:
        if isinstance(value, Mapping):
            return {str(key): _finite_decimal(item) for key, item in value.items()}
        return _finite_decimal(value)


class ReverseStressConfig(Contract):
    """Declared maximum plausible shock combination searched for a stated survival breach."""

    target_loss_fraction: Decimal = Field(gt=0, le=1)
    strategy_return_shocks: dict[str, Decimal]
    slippage_and_impact_loss: Decimal = Field(ge=0)
    funding_and_borrow_loss: Decimal = Field(ge=0)
    collateral_and_fx_loss: Decimal = Field(ge=0)
    venue_default_loss: Decimal = Field(ge=0)
    liquidity_feedback_multiplier: Decimal = Field(ge=1)
    recovery_assumption: Decimal = Field(ge=0, le=1)
    uncertain_assumptions: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "target_loss_fraction", "slippage_and_impact_loss", "funding_and_borrow_loss",
        "collateral_and_fx_loss", "venue_default_loss", "liquidity_feedback_multiplier",
        "recovery_assumption", mode="before",
    )
    @classmethod
    def parse_numbers(cls, value: object) -> Decimal:
        return _finite_decimal(value)

    @field_validator("strategy_return_shocks", mode="before")
    @classmethod
    def parse_shocks(cls, value: object) -> dict[str, Decimal]:
        if not isinstance(value, Mapping):
            raise TypeError("strategy_return_shocks must be keyed by strategy version id")
        return {str(key): _finite_decimal(item) for key, item in value.items()}


class CapitalState(Contract):
    """Reporting-currency capital buckets; no cross-venue transfer is assumed during stress."""

    reporting_currency: str = Field(min_length=1, max_length=16)
    immediately_withdrawable: Decimal = Field(ge=0)
    margin_encumbered: Decimal = Field(ge=0)
    trapped_by_positions_or_orders: Decimal = Field(ge=0)
    withdrawal_delayed: Decimal = Field(ge=0)
    valuation_artifact_id: str = Field(min_length=1)

    @field_validator(
        "immediately_withdrawable", "margin_encumbered", "trapped_by_positions_or_orders",
        "withdrawal_delayed", mode="before",
    )
    @classmethod
    def parse_money(cls, value: object) -> Decimal:
        return _finite_decimal(value)


class Attribution(Contract):
    strategy_version_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    venue_id: str = Field(min_length=1)
    gross_market_pnl: Decimal
    execution_cost: Decimal = Field(ge=0)
    fees: Decimal = Field(ge=0)
    funding_and_borrow: Decimal = Field(ge=0)
    collateral_and_fx: Decimal = Field(ge=0)
    net_pnl: Decimal

    @field_validator(
        "gross_market_pnl", "execution_cost", "fees", "funding_and_borrow", "collateral_and_fx", "net_pnl",
        mode="before",
    )
    @classmethod
    def parse_money(cls, value: object) -> Decimal:
        return _finite_decimal(value)


class PathSimulationConfig(Contract):
    seed: int
    paths: int = Field(ge=100, le=100_000)
    horizon_periods: int = Field(ge=1, le=10_000)
    starting_equity: Decimal = Field(gt=0)
    ruin_drawdown_fraction: Decimal = Field(gt=0, lt=1)
    edge_decay_fraction: Decimal = Field(ge=0, le=1)
    correlation_stress_multiplier: Decimal = Field(ge=1, le=10)
    per_period_cost_fraction: Decimal = Field(ge=0, lt=1)
    shock_probability_per_period: Decimal = Field(ge=0, le=1)
    shock_loss_fraction: Decimal = Field(ge=0, lt=1)
    block_length: int = Field(ge=1, le=365)

    @field_validator(
        "starting_equity", "ruin_drawdown_fraction", "edge_decay_fraction", "correlation_stress_multiplier",
        "per_period_cost_fraction", "shock_probability_per_period", "shock_loss_fraction", mode="before",
    )
    @classmethod
    def parse_numbers(cls, value: object) -> Decimal:
        return _finite_decimal(value)


class StrategyStatusTransition(Contract):
    portfolio_id: str = Field(min_length=1)
    strategy_version_id: str = Field(min_length=1)
    state: StrategyHealth
    reason: str = Field(min_length=1)
    predeclared_regime_rule_artifact_id: str | None = None
    refreshed_evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AllocationResult:
    method: AllocationMethod
    weights: dict[str, Decimal]
    variance: Decimal


@dataclass(frozen=True)
class PortfolioRiskView:
    gross_exposure: Decimal
    net_directional_exposure: Decimal
    leverage: Decimal
    strategy_concentration: Decimal
    asset_concentration: dict[str, Decimal]
    venue_concentration: dict[str, Decimal]
    component_risk: dict[str, Decimal]
    expected_shortfall: MetricResult
    maximum_drawdown: MetricResult
    tail_co_movement: dict[str, MetricResult]
    correlation_instability: dict[str, MetricResult]
    liquidity_at_risk: Decimal
    capacity_shortfall: Decimal
    turnover: MetricResult
    common_driver_exposure: dict[str, Decimal]
    capital_state: CapitalState | None


@dataclass(frozen=True)
class PortfolioAnalysis:
    allocation: AllocationResult
    challenger: AllocationResult
    risk: PortfolioRiskView
    regularized_expected_returns: dict[str, Decimal]
    scenarios: dict[str, dict[str, Decimal | bool | tuple[str, ...]]]
    reverse_stress: dict[str, Decimal | bool | tuple[str, ...]] | None
    attribution_residual: Decimal | None
    authoritative_performance: bool


def _matrix(observations: Sequence[PortfolioObservation], strategies: Sequence[str]) -> np.ndarray:
    if len(observations) < 2:
        raise ValueError("at least two synchronized observations are required")
    required = set(strategies)
    previous = None
    rows: list[list[float]] = []
    for observation in observations:
        if set(observation.simple_returns) != required:
            raise ValueError("all observations must contain exactly the portfolio strategy universe")
        when = observation.observed_at
        if previous is not None and when <= previous:
            raise ValueError("observations must be strictly increasing")
        previous = when
        rows.append([float(observation.simple_returns[strategy]) for strategy in strategies])
    matrix = np.asarray(rows, dtype=np.float64)
    if not np.isfinite(matrix).all():
        raise ValueError("returns must be finite")
    return matrix


def _bounded_metric(metric_id: str, value: float | None, reason: str) -> MetricResult:
    if value is None or not np.isfinite(value):
        return MetricResult(metric_id=metric_id, version="portfolio-v1", state=MetricState.INSUFFICIENT_DATA, reason=reason)
    return MetricResult(metric_id=metric_id, version="portfolio-v1", state=MetricState.VALUE, value=Decimal(str(value)))


def _max_weights(strategies: Sequence[StrategyDefinition], constraints: AllocationConstraints) -> np.ndarray:
    return np.asarray(
        [float(min(constraints.max_strategy_weight, constraints.max_liquidity_fraction, item.capacity_fraction)) for item in strategies],
        dtype=np.float64,
    )


def _validate_constraints(
    weights: np.ndarray,
    strategies: Sequence[StrategyDefinition],
    constraints: AllocationConstraints,
    prior_weights: np.ndarray | None = None,
) -> None:
    tolerance = 1e-10
    if abs(float(weights.sum()) - float(constraints.gross_target)) > tolerance:
        raise ValueError("allocation does not satisfy gross target")
    if np.any(weights < -tolerance) or np.any(weights - _max_weights(strategies, constraints) > tolerance):
        raise ValueError("allocation violates strategy or liquidity capacity")
    for group, limit in (("asset_id", constraints.max_asset_fraction), ("venue_id", constraints.max_venue_fraction)):
        for identifier in {getattr(item, group) for item in strategies}:
            total = sum(weights[index] for index, item in enumerate(strategies) if getattr(item, group) == identifier)
            if total - float(limit) > tolerance:
                raise ValueError(f"allocation violates {group} concentration")
    if prior_weights is not None and np.abs(weights - prior_weights).sum() - float(constraints.max_turnover_fraction) > tolerance:
        raise ValueError("allocation violates declared one-way turnover limit")


def _constraint_functions(
    strategies: Sequence[StrategyDefinition], constraints: AllocationConstraints, prior_weights: np.ndarray | None,
) -> list[dict]:
    functions: list[dict] = [{"type": "eq", "fun": lambda weight: weight.sum() - float(constraints.gross_target)}]
    for group, limit in (("asset_id", constraints.max_asset_fraction), ("venue_id", constraints.max_venue_fraction)):
        for identifier in {getattr(item, group) for item in strategies}:
            indices = [index for index, item in enumerate(strategies) if getattr(item, group) == identifier]
            functions.append({"type": "ineq", "fun": lambda weight, indices=indices, limit=limit: float(limit) - weight[indices].sum()})
    if prior_weights is not None:
        functions.append({"type": "ineq", "fun": lambda weight: float(constraints.max_turnover_fraction) - np.abs(weight - prior_weights).sum()})
    return functions


def _equal_weight(
    strategies: Sequence[StrategyDefinition], constraints: AllocationConstraints, prior_weights: np.ndarray | None,
) -> np.ndarray:
    caps = _max_weights(strategies, constraints)
    if float(caps.sum()) + 1e-12 < float(constraints.gross_target):
        raise ValueError("gross target exceeds strategy and liquidity capacity")
    target = np.full(len(strategies), float(constraints.gross_target) / len(strategies))
    initial = np.minimum(target, caps)
    if initial.sum() > 0:
        initial *= float(constraints.gross_target) / initial.sum()
    result = minimize(
        lambda weight: float(np.sum((weight - target) ** 2)), initial, method="SLSQP",
        bounds=[(0.0, cap) for cap in caps], constraints=_constraint_functions(strategies, constraints, prior_weights),
        options={"ftol": 1e-12, "maxiter": 500},
    )
    if not result.success:
        raise ValueError(f"constrained equal-weight challenger did not converge: {result.message}")
    weights = np.asarray(result.x, dtype=np.float64)
    _validate_constraints(weights, strategies, constraints, prior_weights)
    return weights


def _allocate(
    method: AllocationMethod, covariance: np.ndarray, strategies: Sequence[StrategyDefinition], constraints: AllocationConstraints,
    prior_weights: np.ndarray | None,
) -> np.ndarray:
    baseline = _equal_weight(strategies, constraints, prior_weights)
    if method == AllocationMethod.EQUAL_WEIGHT:
        return baseline
    if method == AllocationMethod.INVERSE_VOLATILITY:
        volatility = np.sqrt(np.maximum(np.diag(covariance), 0))
        if np.any(volatility <= 0) or not np.isfinite(volatility).all():
            raise ValueError("inverse-volatility allocation is undefined with nonpositive variance")
        raw = 1 / volatility
        raw *= float(constraints.gross_target) / raw.sum()

        def objective(weight: np.ndarray) -> float:
            return float(np.sum((weight - raw) ** 2))

        initial = baseline
    else:
        def objective(weight: np.ndarray) -> float:
            return float(weight @ covariance @ weight)

        initial = baseline
    result = minimize(
        objective, initial, method="SLSQP", bounds=[(0.0, cap) for cap in _max_weights(strategies, constraints)],
        constraints=_constraint_functions(strategies, constraints, prior_weights), options={"ftol": 1e-12, "maxiter": 500},
    )
    if not result.success:
        raise ValueError(f"constrained allocation did not converge: {result.message}")
    weights = np.asarray(result.x, dtype=np.float64)
    _validate_constraints(weights, strategies, constraints, prior_weights)
    return weights


def _correlation_metrics(
    matrix: np.ndarray, observations: Sequence[PortfolioObservation], names: Sequence[str], tail_confidence: Decimal,
) -> tuple[dict[str, MetricResult], dict[str, MetricResult]]:
    tail: dict[str, MetricResult] = {}
    instability: dict[str, MetricResult] = {}
    regimes = sorted({item.regime for item in observations})
    for left in range(len(names)):
        for right in range(left + 1, len(names)):
            key = f"{names[left]}::{names[right]}"
            if len(matrix) < 5:
                tail[key] = _bounded_metric("tail_co_movement", None, "at least five observations required")
            else:
                left_threshold, right_threshold = np.quantile(matrix[:, left], float(Decimal("1") - tail_confidence)), np.quantile(matrix[:, right], float(Decimal("1") - tail_confidence))
                tail[key] = _bounded_metric("tail_co_movement", float(np.mean((matrix[:, left] <= left_threshold) & (matrix[:, right] <= right_threshold))), "")
            correlations: list[float] = []
            for regime in regimes:
                indices = [index for index, item in enumerate(observations) if item.regime == regime]
                if len(indices) >= 2:
                    value = float(np.corrcoef(matrix[indices, left], matrix[indices, right])[0, 1])
                    if np.isfinite(value):
                        correlations.append(value)
            instability[key] = _bounded_metric("correlation_instability", max(correlations) - min(correlations) if len(correlations) >= 2 else None, "two regimes with variable pair returns required")
    return tail, instability


def _loss_components(
    shocks: Mapping[str, Decimal], names: Sequence[str], weights: np.ndarray, equity: Decimal,
    slippage_and_impact_loss: Decimal, funding_and_borrow_loss: Decimal, collateral_and_fx_loss: Decimal,
    venue_default_loss: Decimal, liquidity_feedback_multiplier: Decimal, recovery_assumption: Decimal, severity: Decimal,
) -> tuple[dict[str, Decimal], Decimal, Decimal]:
    strategy_losses = {
        name: max(ZERO, -equity * Decimal(str(weights[index])) * shocks[name]) * severity
        for index, name in enumerate(names)
    }
    market_loss = sum(strategy_losses.values(), ZERO)
    feedback = Decimal("1") + (liquidity_feedback_multiplier - Decimal("1")) * severity
    market_loss *= feedback
    fixed_loss = severity * (
        slippage_and_impact_loss + funding_and_borrow_loss + collateral_and_fx_loss
        + venue_default_loss * (Decimal("1") - recovery_assumption)
    )
    return strategy_losses, market_loss, fixed_loss


def _scenario_results(scenarios: Sequence[Scenario], names: Sequence[str], weights: np.ndarray, equity: Decimal) -> dict[str, dict[str, Decimal | bool | tuple[str, ...]]]:
    results: dict[str, dict[str, Decimal | bool | tuple[str, ...]]] = {}
    for scenario in scenarios:
        if set(scenario.strategy_return_shocks) != set(names):
            raise ValueError("scenario shocks must cover exactly the portfolio strategy universe")
        strategy_losses, market_loss, fixed_loss = _loss_components(
            scenario.strategy_return_shocks, names, weights, equity, scenario.slippage_and_impact_loss,
            scenario.funding_and_borrow_loss, scenario.collateral_and_fx_loss, scenario.venue_default_loss,
            scenario.liquidity_feedback_multiplier, scenario.recovery_assumption, Decimal("1"),
        )
        total_loss = market_loss + fixed_loss
        dominant = tuple(name for name, _ in sorted(strategy_losses.items(), key=lambda item: item[1], reverse=True) if _ > ZERO)
        results[scenario.scenario_id] = {
            "loss": total_loss,
            "loss_fraction": total_loss / equity,
            "survival_breach": total_loss >= equity,
            "dominant_failure_paths": dominant,
            "recovery_assumption": scenario.recovery_assumption,
        }
    return results


def _reverse_stress(
    config: ReverseStressConfig, names: Sequence[str], weights: np.ndarray, equity: Decimal,
) -> dict[str, Decimal | bool | tuple[str, ...]]:
    if set(config.strategy_return_shocks) != set(names):
        raise ValueError("reverse-stress shocks must cover exactly the portfolio strategy universe")
    target = config.target_loss_fraction * equity

    def loss(severity: Decimal) -> tuple[dict[str, Decimal], Decimal]:
        strategy_losses, market_loss, fixed_loss = _loss_components(
            config.strategy_return_shocks, names, weights, equity, config.slippage_and_impact_loss,
            config.funding_and_borrow_loss, config.collateral_and_fx_loss, config.venue_default_loss,
            config.liquidity_feedback_multiplier, config.recovery_assumption, severity,
        )
        return strategy_losses, market_loss + fixed_loss

    strategy_losses, maximum_loss = loss(Decimal("1"))
    if maximum_loss < target:
        severity = Decimal("1")
        reached = False
    else:
        lower, upper = Decimal("0"), Decimal("1")
        for _ in range(80):
            midpoint = (lower + upper) / Decimal("2")
            if loss(midpoint)[1] >= target:
                upper = midpoint
            else:
                lower = midpoint
        severity, reached = upper, True
        strategy_losses, _ = loss(severity)
    dominant = tuple(name for name, value in sorted(strategy_losses.items(), key=lambda item: item[1], reverse=True) if value > ZERO)
    return {
        "target_loss_fraction": config.target_loss_fraction,
        "severity": severity,
        "loss_at_severity": loss(severity)[1],
        "maximum_loss": maximum_loss,
        "survival_breach_reachable": reached,
        "dominant_failure_paths": dominant,
        "uncertain_assumptions": config.uncertain_assumptions,
    }


def analyze_portfolio(
    strategies: Sequence[StrategyDefinition], observations: Sequence[PortfolioObservation], constraints: AllocationConstraints,
    model: PortfolioModel, equity: Decimal, scenarios: Sequence[Scenario] = (), attributions: Sequence[Attribution] = (),
    attribution_tolerance: Decimal = Decimal("0"), prior_weights: Mapping[str, Decimal] | None = None,
    capital_state: CapitalState | None = None, reverse_stress: ReverseStressConfig | None = None,
) -> PortfolioAnalysis:
    """Build a constrained allocation from synchronized simple returns only; it never submits orders."""
    equity = _finite_decimal(equity)
    attribution_tolerance = _finite_decimal(attribution_tolerance)
    if equity <= ZERO or attribution_tolerance < ZERO:
        raise ValueError("equity must be positive and attribution tolerance nonnegative")
    names = tuple(item.strategy_version_id for item in strategies)
    if len(names) < 2 or len(set(names)) != len(names):
        raise ValueError("at least two distinct strategies are required")
    matrix = _matrix(observations, names)
    return_map = {name: matrix[:, index].tolist() for index, name in enumerate(names)}
    covariance_names, covariance = shrunk_covariance(return_map, float(model.covariance_shrinkage))
    covariance_order = [covariance_names.index(name) for name in names]
    covariance = covariance[np.ix_(covariance_order, covariance_order)]
    sample_means = matrix.mean(axis=0)
    regularized_means = sample_means * (1 - float(model.return_shrinkage))
    prior_vector: np.ndarray | None = None
    if prior_weights is not None:
        if set(prior_weights) != set(names):
            raise ValueError("prior weights must cover exactly the portfolio strategy universe")
        prior_vector = np.asarray([float(_finite_decimal(prior_weights[name])) for name in names], dtype=np.float64)
        if np.any(prior_vector < 0) or prior_vector.sum() - 1 > 1e-10:
            raise ValueError("prior weights must be nonnegative and have gross exposure at most one")
    weights = _allocate(model.allocation_method, covariance, strategies, constraints, prior_vector)
    challenger_weights = _allocate(AllocationMethod.EQUAL_WEIGHT, covariance, strategies, constraints, prior_vector)
    variance = float(weights @ covariance @ weights)
    challenger_variance = float(challenger_weights @ covariance @ challenger_weights)
    portfolio_returns = [Decimal(str(item @ weights)) for item in matrix]
    exposure = {name: Decimal(str(weights[index])) * equity for index, name in enumerate(names)}
    components = component_risk({name: Decimal(str(weights[index])) for index, name in enumerate(names)}, covariance, names)
    asset_concentration = {asset: sum((Decimal(str(weights[index])) for index, item in enumerate(strategies) if item.asset_id == asset), ZERO) for asset in {item.asset_id for item in strategies}}
    venue_concentration = {venue: sum((Decimal(str(weights[index])) for index, item in enumerate(strategies) if item.venue_id == venue), ZERO) for venue in {item.venue_id for item in strategies}}
    tail, instability = _correlation_metrics(matrix, observations, names, model.tail_confidence)
    capacity_shortfall = max(ZERO, constraints.gross_target - sum((item.capacity_fraction for item in strategies), ZERO))
    capital_total = None if capital_state is None else sum((
        capital_state.immediately_withdrawable, capital_state.margin_encumbered,
        capital_state.trapped_by_positions_or_orders, capital_state.withdrawal_delayed,
    ), ZERO)
    if capital_total is not None and capital_total > equity:
        raise ValueError("capital-state buckets cannot exceed reporting equity")
    turnover = (
        MetricResult(metric_id="portfolio_turnover", version="1", state=MetricState.NOT_APPLICABLE,
                     reason="no prior weights were supplied; turnover is not inferred")
        if prior_vector is None else MetricResult(metric_id="portfolio_turnover", version="1", state=MetricState.VALUE,
                                                   value=Decimal(str(np.abs(weights - prior_vector).sum())))
    )
    drivers: dict[str, Decimal] = {}
    for index, strategy in enumerate(strategies):
        for driver, loading in strategy.factor_loadings.items():
            drivers[driver] = drivers.get(driver, ZERO) + Decimal(str(weights[index])) * loading
        for dependency in strategy.common_dependencies:
            key = f"dependency:{dependency}"
            drivers[key] = drivers.get(key, ZERO) + Decimal(str(weights[index]))
    risk = PortfolioRiskView(
        gross_exposure=sum((abs(item) for item in exposure.values()), ZERO),
        net_directional_exposure=sum((exposure[name] * strategies[index].net_directional_fraction for index, name in enumerate(names)), ZERO),
        leverage=sum((abs(item) for item in exposure.values()), ZERO) / equity,
        strategy_concentration=max((Decimal(str(weight)) for weight in weights), default=ZERO),
        asset_concentration=asset_concentration, venue_concentration=venue_concentration, component_risk=components,
        expected_shortfall=expected_shortfall(portfolio_returns, model.tail_confidence, "1"),
        maximum_drawdown=max_drawdown(
            [equity, *(equity * Decimal(str(item)) for item in np.cumprod([1 + float(item) for item in portfolio_returns]))], "1",
        ),
        tail_co_movement=tail, correlation_instability=instability,
        liquidity_at_risk=sum((abs(exposure[name]) * strategies[index].liquidity_stress_loss_fraction for index, name in enumerate(names)), ZERO),
        capacity_shortfall=capacity_shortfall,
        turnover=turnover, common_driver_exposure=drivers, capital_state=capital_state,
    )
    residual: Decimal | None = None
    authoritative = True
    if attributions:
        if {item.strategy_version_id for item in attributions} - set(names):
            raise ValueError("attribution contains a strategy outside the portfolio")
        residual = sum((item.net_pnl - (item.gross_market_pnl - item.execution_cost - item.fees - item.funding_and_borrow - item.collateral_and_fx) for item in attributions), ZERO)
        authoritative = abs(residual) <= attribution_tolerance
    return PortfolioAnalysis(
        allocation=AllocationResult(model.allocation_method, {name: Decimal(str(weights[index])) for index, name in enumerate(names)}, Decimal(str(variance))),
        challenger=AllocationResult(AllocationMethod.EQUAL_WEIGHT, {name: Decimal(str(challenger_weights[index])) for index, name in enumerate(names)}, Decimal(str(challenger_variance))),
        risk=risk, regularized_expected_returns={name: Decimal(str(regularized_means[index])) for index, name in enumerate(names)},
        scenarios=_scenario_results(scenarios, names, weights, equity),
        reverse_stress=None if reverse_stress is None else _reverse_stress(reverse_stress, names, weights, equity),
        attribution_residual=residual,
        authoritative_performance=authoritative,
    )


def simulate_ruin(
    observations: Sequence[PortfolioObservation], strategy_ids: Sequence[str], weights: Mapping[str, Decimal], config: PathSimulationConfig,
) -> BoundedValue:
    """Seeded synchronous block bootstrap with explicit decay, dependence, cost, and shock assumptions."""
    names = tuple(strategy_ids)
    matrix = _matrix(observations, names)
    vector = np.asarray([float(_finite_decimal(weights[name])) for name in names], dtype=np.float64)
    if vector.sum() <= 0 or vector.sum() > 1 + 1e-9 or np.any(vector < 0):
        raise ValueError("risk-of-ruin weights must be nonnegative with gross exposure in (0, 1]")
    rng = np.random.default_rng(config.seed)
    means = matrix.mean(axis=0)
    ruin_count = 0
    terminal_losses: list[float] = []
    for _ in range(config.paths):
        equity = float(config.starting_equity)
        peak = equity
        path_low = equity
        remaining_block = 0
        row = 0
        for _period in range(config.horizon_periods):
            if remaining_block == 0:
                row = int(rng.integers(0, len(matrix)))
                remaining_block = config.block_length
            sampled = matrix[row % len(matrix)]
            row += 1
            remaining_block -= 1
            centered = sampled - means
            common = float(centered.mean())
            stressed = means * float(config.edge_decay_fraction) + centered + (float(config.correlation_stress_multiplier) - 1) * common
            result = float(vector @ stressed) - float(config.per_period_cost_fraction)
            if rng.random() < float(config.shock_probability_per_period):
                result -= float(config.shock_loss_fraction)
            equity *= max(0.0, 1 + result)
            peak = max(peak, equity)
            path_low = min(path_low, equity)
        drawdown = 1 - path_low / float(config.starting_equity)
        terminal_losses.append(1 - equity / float(config.starting_equity))
        if drawdown >= float(config.ruin_drawdown_fraction) or equity <= 0:
            ruin_count += 1
    probability = ruin_count / config.paths
    error = sqrt(probability * (1 - probability) / config.paths)
    return BoundedValue(
        lower=Decimal(str(max(0.0, probability - 1.96 * error))), central=Decimal(str(probability)),
        upper=Decimal(str(min(1.0, probability + 1.96 * error))), evidence_kind=EvidenceKind.MODEL_ESTIMATE,
        uncertainty_reason=("seeded synchronous block bootstrap; 95% binomial Monte Carlo interval; "
                            f"mean terminal loss={np.mean(terminal_losses):.12g}"),
    )
