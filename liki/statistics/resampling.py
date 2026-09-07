"""Dependence-preserving resampling primitives."""

from __future__ import annotations

import numpy as np


def stationary_bootstrap(
    length: int, *, block_length: float, rng: np.random.Generator
) -> np.ndarray:
    """Politis-Romano stationary-bootstrap indices with geometrically distributed blocks."""
    if length < 1 or block_length <= 0:
        raise ValueError("length and block_length must be positive")
    restart_probability = min(1.0, 1.0 / block_length)
    output = np.empty(length, dtype=int)
    output[0] = int(rng.integers(length))
    for index in range(1, length):
        output[index] = (
            int(rng.integers(length))
            if rng.random() < restart_probability
            else (output[index - 1] + 1) % length
        )
    return output


def stationary_bootstrap_matrix(
    values: np.ndarray, *, block_length: float, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """Resample every model with one common time-index path to retain cross-model dependence."""
    array = np.asarray(values)
    if array.ndim != 2 or array.shape[0] < 1:
        raise ValueError("values must be a nonempty time-by-model matrix")
    indices = stationary_bootstrap(array.shape[0], block_length=block_length, rng=rng)
    return array[indices, :], indices
