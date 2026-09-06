"""Temporal validation splits and a predeclared sequential z-test boundary."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import isfinite
from collections.abc import Sequence

import numpy as np
from scipy.stats import norm

from .inference import Applicability, MetricResult, SearchProvenance


@dataclass(frozen=True)
class PurgedFold:
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    embargo_indices: tuple[int, ...]


@dataclass(frozen=True)
class CPCVSplit:
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    embargo_indices: tuple[int, ...]


def purged_kfold(
    event_end_indices: Sequence[int], *, folds: int, embargo: int
) -> tuple[PurgedFold, ...]:
    """Exclude training events extending into each test window plus a future embargo."""
    n = len(event_end_indices)
    if folds < 2 or folds > n or embargo < 0:
        raise ValueError("invalid temporal fold configuration")
    if any(end < index or end >= n for index, end in enumerate(event_end_indices)):
        raise ValueError("event end indices must be in-range and not precede decision index")
    boundaries = np.linspace(0, n, folds + 1, dtype=int)
    splits: list[PurgedFold] = []
    for fold in range(folds):
        start, stop = int(boundaries[fold]), int(boundaries[fold + 1])
        test = set(range(start, stop))
        embargo_indices = set(range(stop, min(n, stop + embargo)))
        train = tuple(
            index
            for index, event_end in enumerate(event_end_indices)
            if index not in test | embargo_indices and not (index < stop and event_end >= start)
        )
        splits.append(PurgedFold(train, tuple(sorted(test)), tuple(sorted(embargo_indices))))
    return tuple(splits)


def cpcv_splits(
    event_end_indices: Sequence[int], *, groups: int, test_groups: int, embargo: int
) -> tuple[CPCVSplit, ...]:
    if groups < 2 or not 1 <= test_groups < groups:
        raise ValueError("invalid CPCV group configuration")
    n = len(event_end_indices)
    boundaries = np.linspace(0, n, groups + 1, dtype=int)
    output: list[CPCVSplit] = []
    for selected in combinations(range(groups), test_groups):
        test = set().union(
            *(set(range(int(boundaries[group]), int(boundaries[group + 1]))) for group in selected)
        )
        embargoed = set().union(
            *(
                set(range(int(boundaries[group + 1]), min(n, int(boundaries[group + 1]) + embargo)))
                for group in selected
            )
        )
        train = tuple(
            index
            for index, end in enumerate(event_end_indices)
            if index not in test | embargoed
            and not any(index < test_index + 1 and end >= test_index for test_index in test)
        )
        output.append(CPCVSplit(train, tuple(sorted(test)), tuple(sorted(embargoed))))
    return tuple(output)


def walk_forward_splits(
    n_observations: int, *, train_size: int, test_size: int, step: int | None = None
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    if n_observations <= 0 or train_size <= 0 or test_size <= 0:
        raise ValueError("sizes must be positive")
    step = step or test_size
    if step <= 0:
        raise ValueError("step must be positive")
    output = []
    for start in range(0, n_observations - train_size - test_size + 1, step):
        output.append(
            (
                tuple(range(start, start + train_size)),
                tuple(range(start + train_size, start + train_size + test_size)),
            )
        )
    return tuple(output)


def sequential_z_test(
    observations: Sequence[float],
    *,
    information_fractions: Sequence[float],
    look_number: int,
    alpha: float,
    provenance: SearchProvenance,
) -> MetricResult:
    """Conservative O'Brien-Fleming-shaped alpha spending for a predeclared z-test."""
    data = np.asarray(observations, dtype=float)
    if data.size < 2:
        return MetricResult.exceptional(
            Applicability.INSUFFICIENT_DATA,
            "OBF-spending-bonferroni.v2",
            provenance.provenance_ids,
            "requires two observations",
        )
    if not np.all(np.isfinite(data)):
        return MetricResult.exceptional(
            Applicability.NUMERIC_ERROR,
            "OBF-spending-bonferroni.v2",
            provenance.provenance_ids,
            "non-finite observations",
        )
    try:
        boundaries = obrien_fleming_spending_boundaries(alpha, information_fractions)
    except ValueError as error:
        return MetricResult.exceptional(
            Applicability.UNDEFINED,
            "OBF-spending-bonferroni.v2",
            provenance.provenance_ids,
            str(error),
        )
    if not 1 <= look_number <= len(boundaries):
        return MetricResult.exceptional(
            Applicability.UNDEFINED,
            "OBF-spending-bonferroni.v2",
            provenance.provenance_ids,
            "look number is outside the predeclared schedule",
        )
    std = float(np.std(data, ddof=1))
    if std == 0 or not isfinite(std):
        return MetricResult.exceptional(
            Applicability.UNDEFINED,
            "OBF-spending-bonferroni.v2",
            provenance.provenance_ids,
            "zero or invalid standard deviation",
        )
    z = float(np.mean(data) / (std / data.size**0.5))
    boundary = boundaries[look_number - 1]
    return MetricResult(
        Applicability.VALUE,
        float(z >= boundary),
        "OBF-spending-bonferroni.v2",
        provenance.provenance_ids,
        (
            "one-sided z-statistic has valid information increments",
            "entire information-fraction schedule was predeclared",
            "conservative Bonferroni allocation controls family alpha but is not exact O'Brien-Fleming calibration",
        ),
        uncertainty=(z, boundary),
    )


def obrien_fleming_spending_boundaries(
    alpha: float, information_fractions: Sequence[float]
) -> tuple[float, ...]:
    """One-sided OBF spending with a Bonferroni-valid boundary conversion.

    Exact O'Brien-Fleming calibration requires a validated joint-information
    model. This conservative conversion controls family alpha without claiming
    that a heuristic per-look formula has exact calibration.
    """
    fractions = tuple(float(fraction) for fraction in information_fractions)
    if not 0 < alpha < 1 or not fractions or fractions[-1] != 1.0:
        raise ValueError("schedule must end at information fraction 1 with alpha in (0, 1)")
    if any(not 0 < fraction <= 1 for fraction in fractions) or any(
        later <= earlier for earlier, later in zip(fractions, fractions[1:], strict=False)
    ):
        raise ValueError("information fractions must be strictly increasing in (0, 1]")
    fixed_boundary = norm.isf(alpha)
    cumulative_spending = tuple(
        float(norm.sf(fixed_boundary / fraction**0.5)) for fraction in fractions
    )
    allocations = (cumulative_spending[0],) + tuple(
        later - earlier
        for earlier, later in zip(cumulative_spending, cumulative_spending[1:], strict=False)
    )
    return tuple(float(norm.isf(allocation)) for allocation in allocations)
