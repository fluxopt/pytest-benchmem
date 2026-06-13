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
    assert res.peak_bytes_max >= res.peak_bytes  # reported peak is the floor
    assert res.as_dict()["peak_bytes"] == res.peak_bytes


def test_total_bytes_mirrors_memray_stats():
    # churn: many temporaries freed each iteration — total allocated >> peak.
    def action():
        for _ in range(20):
            _ = [bytearray(4096) for _ in range(1000)]

    res = measure_memory(action)
    assert res.total_bytes > 0
    assert res.total_bytes >= res.peak_bytes  # cumulative ≥ high-water mark
    assert res.as_dict()["total_bytes"] == res.total_bytes


MIB = 1024 * 1024


def _alloc_touch(mib):
    """Allocate `mib` MiB and touch every page so it's actually resident."""
    import resource

    page = resource.getpagesize()
    buf = bytearray(mib * MIB)
    for i in range(0, len(buf), page):
        buf[i] = 1
    return buf


def test_rss_mode_measures_net_above_baseline():
    size = 80
    res = measure_memory(lambda: _alloc_touch(size), mode="rss")
    assert res.mode == "rss"
    want = size * MIB
    assert 0.8 * want <= res.peak_bytes <= 1.4 * want  # headline peak_bytes is NET ≈ allocated
    assert res.gross_bytes > res.baseline_bytes > 0  # gross (capacity) above the no-op floor
    assert res.peak_bytes <= res.gross_bytes  # net never exceeds gross


def test_rss_blob_carries_baseline_gross_not_churn():
    blob = measure_memory(lambda: _alloc_touch(40), mode="rss").as_dict()
    assert blob["mode"] == "rss"
    expected = {"peak_bytes", "peak_bytes_max", "baseline_bytes", "gross_bytes", "repeats"}
    assert expected <= blob.keys()
    assert "allocations" not in blob and "total_bytes" not in blob  # heap-only fields absent


def test_rss_failure_raises_with_child_traceback():
    def boom():
        raise ValueError("kaboom-xyz")

    with pytest.raises(RuntimeError, match="raised during rss measurement") as exc:
        measure_memory(boom, mode="rss")
    assert "kaboom-xyz" in str(exc.value)  # the child's traceback is surfaced


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="unknown memory mode"):
        measure_memory(lambda: None, mode="bogus")


def test_mode_defaults_to_heap_in_result_and_blob():
    res = measure_memory(lambda: [bytearray(1024) for _ in range(50)])
    assert res.mode == "heap"
    assert res.as_dict()["mode"] == "heap"


def test_memory_result_mode_is_overridable():
    # the field exists with a heap default but can be set (the rss engine will set it).
    assert MemoryResult(1, 1, 0, 0, 1).mode == "heap"
    assert MemoryResult(1, 1, 0, 0, 1, mode="rss").as_dict()["mode"] == "rss"


def test_compute_statistics_missing_raises_actionably(monkeypatch):
    import sys
    import types

    import pytest_benchmem.memray as m

    # simulate a memray that no longer exposes the internal stats fn
    monkeypatch.setitem(sys.modules, "memray._memray", types.ModuleType("memray._memray"))
    with pytest.raises(RuntimeError, match="compute_statistics"):
        m._compute_statistics()
