"""Canonical registered metrics for statistical evidence, never accounting ledgers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .inference import Applicability, MetricResult, SearchProvenance


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    version: str
    formula_reference: str
    input_series_semantics: str
    units: str
    annualization_rule: str
    missing_data_rule: str
    undefined_conditions: tuple[str, ...]
    numerical_tolerance: float
    golden_fixture_ids: tuple[str, ...]


def simple_returns(equity: Sequence[float], *, provenance: SearchProvenance) -> MetricResult:
    """r_t = V_t / V_(t-1) - 1 for a reconciled, cash-flow-consistent equity series."""
    values = np.asarray(equity, dtype=float)
    if values.ndim != 1 or values.size < 2:
        return MetricResult.exceptional(
            Applicability.INSUFFICIENT_DATA,
            "simple-return.v1",
            provenance.provenance_ids,
            "requires two equity observations",
        )
    if not np.all(np.isfinite(values)) or np.any(values <= 0):
        return MetricResult.exceptional(
            Applicability.NUMERIC_ERROR,
            "simple-return.v1",
            provenance.provenance_ids,
            "equity must be finite and positive",
        )
    return MetricResult(
        Applicability.VALUE,
        float(values[-1] / values[-2] - 1),
        "simple-return.v1",
        provenance.provenance_ids,
        ("equity is reconciled marked-to-market", "cash-flow convention is declared"),
    )


def maximum_drawdown(equity: Sequence[float], *, provenance: SearchProvenance) -> MetricResult:
    values = np.asarray(equity, dtype=float)
    if values.ndim != 1 or values.size < 1:
        return MetricResult.exceptional(
            Applicability.INSUFFICIENT_DATA,
            "maximum-drawdown.v1",
            provenance.provenance_ids,
            "empty equity series",
        )
    if not np.all(np.isfinite(values)) or np.any(values <= 0):
        return MetricResult.exceptional(
            Applicability.NUMERIC_ERROR,
            "maximum-drawdown.v1",
            provenance.provenance_ids,
            "equity must be finite and positive",
        )
    drawdowns = values / np.maximum.accumulate(values) - 1
    return MetricResult(
        Applicability.VALUE,
        float(np.min(drawdowns)),
        "maximum-drawdown.v1",
        provenance.provenance_ids,
        ("negative sign denotes a loss",),
    )
