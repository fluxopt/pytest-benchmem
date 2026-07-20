"""Squared pairwise distances — a worked memory example for the docs.

Computing the matrix of squared Euclidean distances between every pair of ``n``
points in ``d`` dimensions is a staple of clustering, nearest-neighbour search
and kernel methods. The obvious vectorised implementation hides an expensive
memory pitfall; the optimised one gives the identical result for a fraction of
the peak. Both are exercised by ``tests/test_examples.py``.
"""

from __future__ import annotations

import numpy as np


def pairwise_sq_dists_naive(x: np.ndarray) -> np.ndarray:
    """Squared distances via broadcasting — allocates an ``(n, n, d)`` temporary.

    The subtraction ``x[:, None, :] - x[None, :, :]`` materialises a full
    ``(n, n, d)`` array before it is reduced back to ``(n, n)``. That
    intermediate is ``d``× larger than the result and dominates peak memory —
    the allocation a flamegraph points straight at.

    Args:
        x: Points as an ``(n, d)`` array.

    Returns:
        The ``(n, n)`` matrix of squared Euclidean distances.
    """
    diff = x[:, None, :] - x[None, :, :]  # (n, n, d) — the memory hog
    dists: np.ndarray = np.einsum("ijk,ijk->ij", diff, diff)
    return dists


def pairwise_sq_dists(x: np.ndarray) -> np.ndarray:
    """Squared distances via the Gram-matrix identity — only ``O(n²)`` memory.

    Uses ``‖xᵢ − xⱼ‖² = ‖xᵢ‖² + ‖xⱼ‖² − 2·xᵢ·xⱼ`` so nothing bigger than the
    ``(n, n)`` result is ever allocated. Small negative values from
    floating-point cancellation are clipped to zero.

    Args:
        x: Points as an ``(n, d)`` array.

    Returns:
        The ``(n, n)`` matrix of squared Euclidean distances.
    """
    gram = x @ x.T  # (n, n)
    sq_norms = np.einsum("ij,ij->i", x, x)  # (n,)
    dists: np.ndarray = sq_norms[:, None] + sq_norms[None, :] - 2.0 * gram
    np.maximum(dists, 0.0, out=dists)  # clip tiny negatives from cancellation
    return dists
