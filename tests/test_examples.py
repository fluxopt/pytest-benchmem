"""Tests for the worked doc examples in ``examples/``."""

from __future__ import annotations

import numpy as np
import pytest

from examples.pairwise import pairwise_sq_dists, pairwise_sq_dists_naive


@pytest.mark.parametrize("n, d", [(1, 3), (2, 1), (40, 5), (64, 16)])
def test_pairwise_matches_naive(n: int, d: int) -> None:
    """The optimised form gives the same distances as the naive broadcast form."""
    rng = np.random.default_rng(0)
    x = rng.standard_normal((n, d))
    assert np.allclose(pairwise_sq_dists(x), pairwise_sq_dists_naive(x), atol=1e-8)


def test_pairwise_properties() -> None:
    """Distances are symmetric, zero on the diagonal, and non-negative."""
    rng = np.random.default_rng(1)
    x = rng.standard_normal((32, 4))
    d = pairwise_sq_dists(x)
    assert np.allclose(d, d.T)
    assert np.allclose(np.diag(d), 0.0, atol=1e-8)
    assert np.all(d >= 0.0)


def test_pairwise_matches_manual() -> None:
    """A hand-computed distance matches, so the identity isn't self-referential."""
    x = np.array([[0.0, 0.0], [3.0, 4.0]])
    got = pairwise_sq_dists(x)
    assert got[0, 1] == pytest.approx(25.0)  # 3² + 4²
