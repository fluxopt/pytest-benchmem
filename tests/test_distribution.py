"""The per-repeat series + ``--stat`` distribution machinery (no memray needed)."""

from __future__ import annotations

import json

import pytest

from pytest_benchmem.memray import Measurement, MemoryResult
from pytest_benchmem.snapshot import load_samples


def test_memory_result_derives_headline_from_min_peak_run():
    res = MemoryResult(
        (
            Measurement(peak_bytes=100, allocations=5, total_bytes=300),
            Measurement(peak_bytes=80, allocations=4, total_bytes=250),  # min peak → representative
            Measurement(peak_bytes=120, allocations=6, total_bytes=350),
        )
    )
    assert res.repeats == 3
    assert res.peak_bytes == 80 and res.peak_bytes_max == 120  # min / max peak
    assert res.allocations == 4 and res.total_bytes == 250  # the min-peak run's churn


def test_as_dict_is_flat_per_repeat_series():
    blob = MemoryResult((Measurement(100, 5, 300), Measurement(80, 4, 250))).as_dict()
    assert blob == {"peak_bytes": [100, 80], "allocations": [5, 4], "total_bytes": [300, 250]}


def test_from_blob_roundtrips():
    res = MemoryResult(
        (Measurement(100, 5, 300), Measurement(80, 4, 250), Measurement(120, 6, 350))
    )
    assert MemoryResult.from_blob(res.as_dict()).as_dict() == res.as_dict()


_SERIES_BLOB = {
    "peak_bytes": [10, 20, 30],
    "allocations": [1, 1, 1],
    "total_bytes": [100, 100, 100],
}


def _write_blob(tmp_path, blob):
    bm = {"fullname": "t::x", "stats": {"min": 1.0}, "extra_info": {"benchmem": blob}}
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"benchmarks": [bm]}))
    return p


def test_stat_reduces_the_series(tmp_path):
    p = _write_blob(tmp_path, _SERIES_BLOB)
    assert load_samples(p, metric="peak", stat="mean")[1][0].value == 20.0
    assert load_samples(p, metric="peak", stat="max")[1][0].value == 30.0
    assert load_samples(p, metric="peak", stat="min")[1][0].value == 10.0
    assert load_samples(p, metric="peak")[1][0].value == 10.0  # no stat → headline (min)
    assert load_samples(p, metric="peak", stat="mean")[2] == "B"  # unit preserved


def test_stat_works_on_allocations_series(tmp_path):
    blob = {"peak_bytes": [5, 5, 5], "allocations": [2, 4, 6], "total_bytes": [1, 1, 1]}
    p = _write_blob(tmp_path, blob)
    assert load_samples(p, metric="allocations", stat="mean")[1][0].value == 4.0


def test_rejects_unknown_stat(tmp_path):
    p = _write_blob(tmp_path, _SERIES_BLOB)
    with pytest.raises(ValueError, match="unknown stat"):
        load_samples(p, metric="peak", stat="p99")
