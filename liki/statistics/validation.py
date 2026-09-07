"""Temporal validation splits and a predeclared sequential z-test boundary."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations
from math import comb, isfinite
from numbers import Integral

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


def _integer(value: int, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _validated_event_ends(event_end_indices: Sequence[int]) -> tuple[int, ...]:
    ends = tuple(event_end_indices)
    if any(
        isinstance(end, bool) or not isinstance(end, Integral) or not index <= end < len(ends)
        for index, end in enumerate(ends)
    ):
        raise ValueError(
            "event end indices must be integers, in-range, and not precede decision index"
        )
    return tuple(int(end) for end in ends)


def _purged_indices(
    ends: tuple[int, ...], windows: Sequence[tuple[int, int]], embargo: int
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    test = {index for start, stop in windows for index in range(start, stop)}
    # Contiguous decision indices make each group's event union one closed interval.
    horizons = tuple((start, max(ends[start:stop])) for start, stop in windows)
    embargoed = {
        index
        for _, horizon in horizons
        for index in range(horizon + 1, min(len(ends), horizon + embargo + 1))
    } - test
    excluded = test | embargoed
    train = tuple(
        index
        for index, end in enumerate(ends)
        if index not in excluded
        and not any(index <= horizon and end >= start for start, horizon in horizons)
    )
    return train, tuple(sorted(test)), tuple(sorted(embargoed))


def purged_kfold(
    event_end_indices: Sequence[int], *, folds: int, embargo: int
) -> tuple[PurgedFold, ...]:
    """Purge intersections between closed training and test events [i, end_i].

    Contiguous folds use boundaries floor(n * fold / folds). For each test fold,
    h = max(end_i) over its events; embargo excludes decision indices h+1 through
    h+embargo, clipped to the dataset. Empty training sets are returned unchanged.
    """
    ends = _validated_event_ends(event_end_indices)
    folds = _integer(folds, "folds", minimum=2)
    embargo = _integer(embargo, "embargo", minimum=0)
    n = len(ends)
    if folds > n:
        raise ValueError("invalid temporal fold configuration")
    return tuple(
        PurgedFold(*_purged_indices(ends, ((n * fold // folds, n * (fold + 1) // folds),), embargo))
        for fold in range(folds)
    )


def cpcv_splits(
    event_end_indices: Sequence[int], *, groups: int, test_groups: int, embargo: int
) -> tuple[CPCVSplit, ...]:
    """Enumerate at most 10000 purged test-group combinations in lexical order.

    Groups use the same boundaries and closed-event purging as purged_kfold.
    Each selected group's maximum event end independently starts its embargo;
    these embargo indices are unioned, clipped, and stripped of test indices.
    Gaps between disjoint test-event intervals remain eligible for training.
    """
    ends = _validated_event_ends(event_end_indices)
    groups = _integer(groups, "groups", minimum=2)
    test_groups = _integer(test_groups, "test_groups", minimum=1)
    embargo = _integer(embargo, "embargo", minimum=0)
    n = len(ends)
    if groups > n or test_groups >= groups:
        raise ValueError("invalid CPCV group configuration")
    if comb(groups, test_groups) > 10_000:
        raise ValueError("CPCV configuration exceeds the limit of 10000 splits")
    windows = tuple((n * group // groups, n * (group + 1) // groups) for group in range(groups))
    return tuple(
        CPCVSplit(*_purged_indices(ends, tuple(windows[group] for group in selected), embargo))
        for selected in combinations(range(groups), test_groups)
    )


def walk_forward_splits(
    n_observations: int, *, train_size: int, test_size: int, step: int | None = None
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    n_observations = _integer(n_observations, "n_observations", minimum=1)
    train_size = _integer(train_size, "train_size", minimum=1)
    test_size = _integer(test_size, "test_size", minimum=1)
    step = test_size if step is None else _integer(step, "step", minimum=1)
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
