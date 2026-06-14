from __future__ import annotations

import json
import platform

import pytest

from pytest_benchmem import measure_memory, measure_peak
from pytest_benchmem.memray import MemoryResult
from pytest_benchmem.snapshot import memory_from_pytest_benchmark

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


def test_blob_roundtrips_engine_to_reader(tmp_path):
    """Producer↔consumer contract in one place: the engine's ``as_dict()`` carries
    exactly the documented keys, and a reader lifts a metric back out of a real blob
    (the synthetic-JSON unit tests only assume this shape; here it's pinned)."""
    blob = measure_memory(lambda: [bytearray(1024) for _ in range(200)]).as_dict()
    assert set(blob) == {
        "peak_bytes",
        "peak_bytes_max",
        "allocations",
        "total_bytes",
        "repeats",
    }
    pb = tmp_path / "bench.json"
    pb.write_text(
        json.dumps(
            {
                "benchmarks": [
                    {"fullname": "t", "stats": {"min": 0.1}, "extra_info": {"benchmem": blob}}
                ]
            }
        )
    )
    _l, samples, unit = memory_from_pytest_benchmark(pb, field="peak_bytes")
    assert (samples[0].value, unit) == (float(blob["peak_bytes"]), "B")


def test_compute_statistics_missing_raises_actionably(monkeypatch):
    import sys
    import types

    import pytest_benchmem.memray as m

    # simulate a memray that no longer exposes the internal stats fn
    monkeypatch.setitem(sys.modules, "memray._memray", types.ModuleType("memray._memray"))
    with pytest.raises(RuntimeError, match="compute_statistics"):
        m._compute_statistics()
