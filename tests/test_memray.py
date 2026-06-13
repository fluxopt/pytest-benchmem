from __future__ import annotations

import platform

import pytest

from pytest_benchmem import measure_memory, measure_peak
from pytest_benchmem.memray import MemoryResult

pytest.importorskip("memray")
pytestmark = pytest.mark.skipif(
    platform.system() == "Windows", reason="memray unavailable on Windows"
)


def test_measure_peak_returns_positive_bytes():
    peak = measure_peak(lambda: [0] * 1_000_000)
    assert isinstance(peak, int)
    assert peak > 1_000_000  # a list of 1e6 ints is several MB; bytes, not MiB


def test_repeats_takes_min_of_n():
    # min-of-N: a smaller allocation never reports more than a larger one would.
    small = measure_peak(lambda: [0] * 100_000, repeats=3)
    big = measure_peak(lambda: [0] * 5_000_000, repeats=3)
    assert big > small


def test_measure_memory_returns_result_with_allocations():
    res = measure_memory(lambda: [bytearray(1024) for _ in range(50)], repeats=2)
    assert isinstance(res, MemoryResult)
    assert res.repeats == 2
    assert res.allocations > 0
    assert res.peak_bytes > 0
    # the reported peak is the floor; the worst observed peak is never below it
    assert res.peak_bytes_max >= res.peak_bytes
    assert res.as_dict()["peak_bytes"] == res.peak_bytes
