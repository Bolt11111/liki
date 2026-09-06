"""Versioned canonical metrics with explicit exceptional numerical states."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from math import sqrt
from pathlib import Path
import json
from collections.abc import Callable, Sequence

from pydantic import field_validator

from .types import FinanceModel, MetricState, decimal


class MetricResult(FinanceModel):
    metric_id: str
    version: str
    state: MetricState
    value: Decimal | None = None
    reason: str | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _decimal(cls, value: object) -> Decimal | None:
        return None if value is None else decimal(value)  # type: ignore[arg-type]


class MetricDefinition(FinanceModel):
    metric_id: str
    version: str
    formula_reference: str
    input_series_semantics: str
    units: str
    annualization_rule: str
    missing_data_rule: str
    undefined_conditions: tuple[str, ...]
    numerical_tolerance: Decimal
    golden_fixture_ids: tuple[str, ...]

    @field_validator("numerical_tolerance", mode="before")
    @classmethod
    def _decimal(cls, value: object) -> Decimal:
        return decimal(value)  # type: ignore[arg-type]


def load_registry(path: Path | None = None) -> dict[str, MetricDefinition]:
    source = path or Path(__file__).resolve().parents[2] / "config" / "metrics.json"
    return {entry["metric_id"]: MetricDefinition.model_validate(entry) for entry in json.loads(source.read_text())["metrics"]}


def simple_returns(equity: Sequence[Decimal]) -> list[Decimal]:
    if len(equity) < 2:
        return []
    result: list[Decimal] = []
    for previous, current in zip(equity[:-1], equity[1:], strict=True):
        previous, current = decimal(previous), decimal(current)
        if previous == 0:
            raise ZeroDivisionError("return is undefined at zero prior equity")
        result.append(current / previous - Decimal("1"))
    return result


def _result(metric_id: str, version: str, fn: Callable[[], Decimal]) -> MetricResult:
    try:
        value = decimal(fn())
        return MetricResult(metric_id=metric_id, version=version, state=MetricState.VALUE, value=value)
    except ZeroDivisionError as error:
        return MetricResult(metric_id=metric_id, version=version, state=MetricState.UNDEFINED, reason=str(error))
    except (InvalidOperation, OverflowError, ValueError) as error:
        return MetricResult(metric_id=metric_id, version=version, state=MetricState.NUMERIC_ERROR, reason=str(error))


def max_drawdown(equity: Sequence[Decimal], version: str = "1") -> MetricResult:
    if not equity:
        return MetricResult(metric_id="maximum_drawdown", version=version, state=MetricState.INSUFFICIENT_DATA, reason="empty equity series")
    def calculate() -> Decimal:
        peak = decimal(equity[0])
        drawdown = Decimal("0")
        for value in equity:
            value = decimal(value)
            peak = max(peak, value)
            if peak <= 0:
                raise ZeroDivisionError("drawdown undefined with nonpositive peak")
            drawdown = min(drawdown, value / peak - Decimal("1"))
        return drawdown
    return _result("maximum_drawdown", version, calculate)


def sharpe(returns: Sequence[Decimal], periods_per_year: int, version: str = "1") -> MetricResult:
    if len(returns) < 2:
        return MetricResult(metric_id="naive_sharpe", version=version, state=MetricState.INSUFFICIENT_DATA, reason="at least two non-overlapping returns required")
    if periods_per_year <= 0:
        return MetricResult(metric_id="naive_sharpe", version=version, state=MetricState.NOT_APPLICABLE, reason="annualization policy missing")
    def calculate() -> Decimal:
        values = [decimal(item) for item in returns]
        mean = sum(values, ZERO) / Decimal(len(values))
        variance = sum(((item - mean) ** 2 for item in values), ZERO) / Decimal(len(values) - 1)
        if variance == 0:
            raise ZeroDivisionError("standard deviation is zero")
        return mean / variance.sqrt() * Decimal(str(sqrt(periods_per_year)))
    return _result("naive_sharpe", version, calculate)


def expected_shortfall(returns: Sequence[Decimal], confidence: Decimal, version: str = "1") -> MetricResult:
    if not ZERO < decimal(confidence) < Decimal("1"):
        return MetricResult(metric_id="expected_shortfall", version=version, state=MetricState.NOT_APPLICABLE, reason="confidence outside (0, 1)")
    if not returns:
        return MetricResult(metric_id="expected_shortfall", version=version, state=MetricState.INSUFFICIENT_DATA, reason="empty return series")
    def calculate() -> Decimal:
        ordered = sorted(decimal(item) for item in returns)
        count = max(1, int((Decimal("1") - decimal(confidence)) * len(ordered)))
        return sum(ordered[:count], ZERO) / Decimal(count)
    return _result("expected_shortfall", version, calculate)


ZERO = Decimal("0")
