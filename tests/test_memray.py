from __future__ import annotations

import platform

import pytest

from pytest_benchmem import measure_peak

pytest.importorskip("memray")
pytestmark = pytest.mark.skipif(
    platform.system() == "Windows", reason="memray unavailable on Windows"
)


def test_measure_peak_returns_positive_mib():
    peak = measure_peak(lambda: [0] * 1_000_000)
    assert peak > 0


def test_repeats_takes_min_of_n():
    # min-of-N: a smaller allocation never reports more than a larger one would.
    small = measure_peak(lambda: [0] * 100_000, repeats=3)
    big = measure_peak(lambda: [0] * 5_000_000, repeats=3)
    assert big > small
