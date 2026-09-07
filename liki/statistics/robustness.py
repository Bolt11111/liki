"""Uncertainty, fragility, and transportability diagnostics without implicit gates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .inference import Applicability, MetricResult, SearchProvenance
from .resampling import stationary_bootstrap


@dataclass(frozen=True)
class TransportabilityAssessment:
    source_regime: str
    target_regime: str
    source_effect: float
    target_effect: float
    effect_difference: float
    source_n: int
    target_n: int


def block_bootstrap_mean_interval(
    values: Sequence[float],
    *,
    block_length: float,
    replications: int,
    seed: int,
    confidence: float,
    provenance: SearchProvenance,
) -> MetricResult:
    """A dependence-aware mean interval; its assumptions remain visible to callers."""
    data = np.asarray(values, dtype=float)
    if data.ndim != 1 or data.size < 3:
        return MetricResult.exceptional(
            Applicability.INSUFFICIENT_DATA,
            "stationary-bootstrap-CI.v1",
            provenance.provenance_ids,
            "requires at least three observations",
        )
    if not np.all(np.isfinite(data)):
        return MetricResult.exceptional(
            Applicability.NUMERIC_ERROR,
            "stationary-bootstrap-CI.v1",
            provenance.provenance_ids,
            "non-finite observations",
        )
    if block_length <= 0 or replications < 100 or not 0 < confidence < 1:
        return MetricResult.exceptional(
            Applicability.NOT_APPLICABLE,
            "stationary-bootstrap-CI.v1",
            provenance.provenance_ids,
            "invalid predeclared resampling plan",
        )
    rng = np.random.default_rng(seed)
    samples = np.array(
        [
            np.mean(data[stationary_bootstrap(len(data), block_length=block_length, rng=rng)])
            for _ in range(replications)
        ]
    )
    alpha = (1 - confidence) / 2
    return MetricResult(
        Applicability.VALUE,
        float(np.mean(data)),
        "stationary-bootstrap-CI.v1",
        provenance.provenance_ids,
        ("stationary-bootstrap dependence approximation", "predeclared block length"),
        uncertainty=(float(np.quantile(samples, alpha)), float(np.quantile(samples, 1 - alpha))),
    )


def leave_block_out_fragility(
    values: Sequence[float], *, blocks: int, provenance: SearchProvenance
) -> MetricResult:
    """Report worst leave-contiguous-block-out mean without imposing a stability cutoff."""
    data = np.asarray(values, dtype=float)
    if data.ndim != 1 or data.size < blocks or blocks < 2:
        return MetricResult.exceptional(
            Applicability.INSUFFICIENT_DATA,
            "leave-block-out-fragility.v1",
            provenance.provenance_ids,
            "requires at least one observation per declared block",
        )
    if not np.all(np.isfinite(data)):
        return MetricResult.exceptional(
            Applicability.NUMERIC_ERROR,
            "leave-block-out-fragility.v1",
            provenance.provenance_ids,
            "non-finite observations",
        )
    partitions = np.array_split(np.arange(data.size), blocks)
    effects = [
        float(np.mean(np.delete(data, partition)))
        for partition in partitions
        if len(partition) < data.size
    ]
    return MetricResult(
        Applicability.VALUE,
        min(effects),
        "leave-block-out-fragility.v1",
        provenance.provenance_ids,
        ("contiguous blocks represent meaningful regimes or outages",),
        uncertainty=(min(effects), max(effects)),
    )


def transportability_assessment(
    values: Sequence[float],
    regimes: Sequence[str],
    *,
    source_regime: str,
    target_regime: str,
) -> TransportabilityAssessment:
    """Compare explicitly named regimes; a difference is evidence, not a pass/fail threshold."""
    data = np.asarray(values, dtype=float)
    regime_array = np.asarray(regimes)
    if data.ndim != 1 or data.shape != regime_array.shape or not np.all(np.isfinite(data)):
        raise ValueError("finite values and regimes must have matching one-dimensional shapes")
    source = data[regime_array == source_regime]
    target = data[regime_array == target_regime]
    if not len(source) or not len(target):
        raise ValueError("both declared regimes require observations")
    source_effect, target_effect = float(np.mean(source)), float(np.mean(target))
    return TransportabilityAssessment(
        source_regime,
        target_regime,
        source_effect,
        target_effect,
        target_effect - source_effect,
        len(source),
        len(target),
    )
