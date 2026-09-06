"""Registered financial inference methods; every result carries a declared state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations
from math import isfinite, log
from collections.abc import Mapping, Sequence

import numpy as np
from scipy.stats import norm


class Applicability(StrEnum):
    VALUE = "VALUE"
    UNDEFINED = "UNDEFINED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NUMERIC_ERROR = "NUMERIC_ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class MetricResult:
    state: Applicability
    value: float | None
    method_id: str
    provenance_ids: tuple[str, ...]
    assumptions: tuple[str, ...]
    reason: str | None = None
    uncertainty: tuple[float, float] | None = None
    diagnostics: Mapping[str, float] | None = None

    @classmethod
    def exceptional(
        cls, state: Applicability, method_id: str, provenance_ids: Sequence[str], reason: str
    ) -> MetricResult:
        return cls(state, None, method_id, tuple(provenance_ids), (), reason)


@dataclass(frozen=True)
class SearchProvenance:
    """Persisted Trial Ledger view. A raw number without ledger identifiers is invalid."""

    trial_ledger_record_ids: tuple[str, ...]
    search_family_id: str
    raw_adaptive_trials: int
    effective_trial_estimates: Mapping[str, float]
    dataset_exposure_record_ids: tuple[str, ...]
    method_versions: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.trial_ledger_record_ids or not self.search_family_id:
            raise ValueError("statistics require persisted trial-ledger provenance")
        if self.raw_adaptive_trials != len(self.trial_ledger_record_ids):
            raise ValueError("every raw adaptive trial requires a persisted trial-ledger record ID")
        if not self.effective_trial_estimates or any(
            value < 1 or value > self.raw_adaptive_trials
            for value in self.effective_trial_estimates.values()
        ):
            raise ValueError(
                "effective-trial estimates must be positive and cannot exceed raw history"
            )
        if not self.dataset_exposure_record_ids:
            raise ValueError("statistics require persisted data exposure provenance")

    @property
    def conservative_effective_trials(self) -> float:
        """Largest credible count is conservative for multiplicity; never exceeds raw history."""
        return min(float(self.raw_adaptive_trials), max(self.effective_trial_estimates.values()))

    @property
    def provenance_ids(self) -> tuple[str, ...]:
        return self.trial_ledger_record_ids + self.dataset_exposure_record_ids


@dataclass(frozen=True)
class InferencePlan:
    """Predeclared intent; post-hoc metrics must use a separate exploratory plan."""

    plan_id: str
    primary_metrics: tuple[str, ...]
    benchmark_or_null: str
    alternative: str
    compared_variant_ids: tuple[str, ...]
    split_method: str
    resampling_method: str | None
    decision_interpretation: str
    predeclared_at_record_id: str

    def __post_init__(self) -> None:
        if not self.plan_id or not self.primary_metrics or not self.compared_variant_ids:
            raise ValueError(
                "inference plan requires metrics, compared variants, and immutable identity"
            )
        if self.alternative not in {"one-sided-greater", "one-sided-less", "two-sided"}:
            raise ValueError("inferential alternative must be explicit")
        if not self.predeclared_at_record_id:
            raise ValueError("inference plan must reference its persisted declaration")


def _returns(values: Sequence[float]) -> tuple[np.ndarray | None, MetricResult | None]:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or array.size == 0:
        return None, MetricResult.exceptional(
            Applicability.INSUFFICIENT_DATA, "input", (), "empty series"
        )
    if not np.all(np.isfinite(array)):
        return None, MetricResult.exceptional(
            Applicability.NUMERIC_ERROR, "input", (), "non-finite input"
        )
    return array, None


def _sample_moments(
    returns: np.ndarray,
) -> tuple[tuple[float, float, float, float] | None, Applicability | None]:
    if returns.size < 3:
        return None, Applicability.INSUFFICIENT_DATA
    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))
    if std == 0:
        return None, Applicability.UNDEFINED
    centred = (returns - mean) / std
    return (mean, std, float(np.mean(centred**3)), float(np.mean(centred**4))), None


def probabilistic_sharpe_ratio(
    returns: Sequence[float],
    *,
    benchmark_sharpe: float,
    annualization: float = 1.0,
    provenance: SearchProvenance,
) -> MetricResult:
    """Bailey/de Prado PSR using observed skew and non-excess kurtosis."""
    data, problem = _returns(returns)
    if problem:
        return MetricResult.exceptional(
            problem.state, "PSR.v1", provenance.provenance_ids, problem.reason or "input"
        )
    assert data is not None
    if annualization <= 0 or not isfinite(benchmark_sharpe):
        return MetricResult.exceptional(
            Applicability.UNDEFINED,
            "PSR.v1",
            provenance.provenance_ids,
            "invalid benchmark or annualization",
        )
    moments, state = _sample_moments(data)
    if moments is None:
        return MetricResult.exceptional(
            state or Applicability.NUMERIC_ERROR,
            "PSR.v1",
            provenance.provenance_ids,
            "requires three nonconstant observations",
        )
    mean, std, skewness, kurtosis = moments
    observed = mean / std * annualization**0.5
    denominator_sq = 1 - skewness * observed + ((kurtosis - 1) / 4) * observed**2
    if denominator_sq <= 0 or not isfinite(denominator_sq):
        return MetricResult.exceptional(
            Applicability.NOT_APPLICABLE,
            "PSR.v1",
            provenance.provenance_ids,
            "invalid Sharpe sampling variance",
        )
    z_score = (observed - benchmark_sharpe) * (data.size - 1) ** 0.5 / denominator_sq**0.5
    tail_dominance = float(np.max((data - mean) ** 2) / np.sum((data - mean) ** 2))
    return MetricResult(
        Applicability.VALUE,
        float(norm.cdf(z_score)),
        "PSR.v1",
        provenance.provenance_ids,
        (
            "finite return moments",
            "sampling convention declared",
            "benchmark Sharpe declared",
            "tail dominance requires review",
        ),
        diagnostics={
            "skewness": skewness,
            "kurtosis": kurtosis,
            "tail_dominance_fraction": tail_dominance,
        },
    )


def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    observed_trial_sharpes: Mapping[str, float],
    annualization: float = 1.0,
    provenance: SearchProvenance,
) -> MetricResult:
    """DSR: PSR versus expected maximum Sharpe implied by the recorded search family."""
    if set(observed_trial_sharpes) != set(provenance.trial_ledger_record_ids):
        return MetricResult.exceptional(
            Applicability.NOT_APPLICABLE,
            "DSR.v1",
            provenance.provenance_ids,
            "trial Sharpe distribution must be keyed to every persisted trial-ledger record",
        )
    trials, problem = _returns(tuple(observed_trial_sharpes.values()))
    if problem:
        return MetricResult.exceptional(
            problem.state, "DSR.v1", provenance.provenance_ids, problem.reason or "input"
        )
    assert trials is not None
    if trials.size < 2:
        return MetricResult.exceptional(
            Applicability.INSUFFICIENT_DATA,
            "DSR.v1",
            provenance.provenance_ids,
            "requires trial Sharpe distribution",
        )
    trial_std = float(np.std(trials, ddof=1))
    if trial_std == 0:
        return MetricResult.exceptional(
            Applicability.NOT_APPLICABLE,
            "DSR.v1",
            provenance.provenance_ids,
            "trial Sharpe variance is zero",
        )
    n_eff = provenance.conservative_effective_trials
    euler_gamma = 0.5772156649015329
    threshold = float(
        np.mean(trials)
        + trial_std
        * (
            (1 - euler_gamma) * norm.ppf(1 - 1 / n_eff)
            + euler_gamma * norm.ppf(1 - 1 / (n_eff * np.e))
        )
    )
    result = probabilistic_sharpe_ratio(
        returns, benchmark_sharpe=threshold, annualization=annualization, provenance=provenance
    )
    return MetricResult(
        result.state,
        result.value,
        "DSR.v1",
        result.provenance_ids,
        result.assumptions + ("recorded search trial Sharpes represent selection distribution",),
        result.reason,
    )


def probability_of_backtest_overfitting(
    return_matrix: Sequence[Sequence[float]], *, partitions: int, provenance: SearchProvenance
) -> MetricResult:
    """CSCV PBO: fraction of IS winners with below-median OOS rank, via logit < 0."""
    matrix = np.asarray(return_matrix, dtype=float)
    if (
        matrix.ndim != 2
        or matrix.shape[1] < 2
        or matrix.shape[0] < partitions
        or not np.all(np.isfinite(matrix))
    ):
        return MetricResult.exceptional(
            Applicability.INSUFFICIENT_DATA,
            "PBO-CSCV.v1",
            provenance.provenance_ids,
            "requires finite observations x variants matrix",
        )
    if partitions < 2 or partitions % 2 or matrix.shape[0] % partitions:
        return MetricResult.exceptional(
            Applicability.NOT_APPLICABLE,
            "PBO-CSCV.v1",
            provenance.provenance_ids,
            "partitions must be even and divide observations",
        )
    blocks = np.array_split(matrix, partitions)
    logits: list[float] = []
    half = partitions // 2
    for in_sample_indices in combinations(range(partitions), half):
        in_sample = np.concatenate([blocks[index] for index in in_sample_indices])
        out_sample = np.concatenate(
            [blocks[index] for index in range(partitions) if index not in in_sample_indices]
        )
        selected = int(np.argmax(np.mean(in_sample, axis=0)))
        oos_scores = np.mean(out_sample, axis=0)
        rank = int(np.sum(oos_scores <= oos_scores[selected]))
        logits.append(log(rank / (matrix.shape[1] + 1 - rank)))
    return MetricResult(
        Applicability.VALUE,
        float(np.mean(np.asarray(logits) < 0)),
        "PBO-CSCV.v1",
        provenance.provenance_ids,
        (
            "contiguous partitions preserve time ordering within blocks",
            "selection metric predeclared",
        ),
    )


def false_discovery_rate_bh(
    p_values: Mapping[str, float], *, q: float, provenance: SearchProvenance
) -> tuple[MetricResult, tuple[str, ...]]:
    """Benjamini-Hochberg FDR over the full passed family, not a local winner subset."""
    if not 0 < q < 1 or not p_values:
        return MetricResult.exceptional(
            Applicability.UNDEFINED,
            "BH-FDR.v1",
            provenance.provenance_ids,
            "invalid q or empty family",
        ), ()
    if len(p_values) > provenance.raw_adaptive_trials:
        return MetricResult.exceptional(
            Applicability.NOT_APPLICABLE,
            "BH-FDR.v1",
            provenance.provenance_ids,
            "family exceeds recorded raw trials",
        ), ()
    if any(not isfinite(value) or value < 0 or value > 1 for value in p_values.values()):
        return MetricResult.exceptional(
            Applicability.NUMERIC_ERROR, "BH-FDR.v1", provenance.provenance_ids, "invalid p-value"
        ), ()
    ordered = sorted(p_values.items(), key=lambda pair: pair[1])
    cutoff = 0
    for index, (_, p_value) in enumerate(ordered, start=1):
        if p_value <= q * index / len(ordered):
            cutoff = index
    discoveries = tuple(identifier for identifier, _ in ordered[:cutoff])
    return MetricResult(
        Applicability.VALUE,
        float(cutoff / len(ordered)),
        "BH-FDR.v1",
        provenance.provenance_ids,
        ("all tested family members supplied", "valid null p-values", "FDR target predeclared"),
    ), discoveries


def white_reality_check(
    excess_return_matrix: Sequence[Sequence[float]],
    *,
    block_length: float,
    replications: int,
    seed: int,
    provenance: SearchProvenance,
) -> MetricResult:
    """White's data-snooping test using stationary-bootstrap centred excess returns."""
    from .resampling import stationary_bootstrap_matrix

    matrix = np.asarray(excess_return_matrix, dtype=float)
    if (
        matrix.ndim != 2
        or matrix.shape[0] < 3
        or matrix.shape[1] < 1
        or not np.all(np.isfinite(matrix))
    ):
        return MetricResult.exceptional(
            Applicability.INSUFFICIENT_DATA,
            "White-RC.v1",
            provenance.provenance_ids,
            "requires finite time x model excess returns",
        )
    if block_length <= 0 or replications < 100:
        return MetricResult.exceptional(
            Applicability.NOT_APPLICABLE,
            "White-RC.v1",
            provenance.provenance_ids,
            "declared dependence bootstrap requires block length and >=100 replications",
        )
    observed = float(np.sqrt(matrix.shape[0]) * np.max(np.mean(matrix, axis=0)))
    centred = matrix - np.mean(matrix, axis=0)
    rng = np.random.default_rng(seed)
    bootstrap_maxima = np.empty(replications)
    for replication in range(replications):
        resampled, _ = stationary_bootstrap_matrix(centred, block_length=block_length, rng=rng)
        bootstrap_maxima[replication] = np.sqrt(matrix.shape[0]) * np.max(
            np.mean(resampled, axis=0)
        )
    p_value = float((1 + np.count_nonzero(bootstrap_maxima >= observed)) / (replications + 1))
    return MetricResult(
        Applicability.VALUE,
        p_value,
        "White-RC.v1",
        provenance.provenance_ids,
        (
            "benchmark excess returns supplied",
            "stationary bootstrap dependence approximation",
            "entire searched model set supplied",
        ),
    )
