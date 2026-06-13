"""Unit tests for the inline --benchmark-memory-compare plumbing (no memray needed)."""

from __future__ import annotations

from types import SimpleNamespace

from pytest_benchmem import pytest_plugin as P


def _config(**opts):
    return SimpleNamespace(getoption=lambda name: opts.get(name, False))


def test_compare_requested_off_by_default():
    compare, fail = P._compare_requested(_config())
    assert compare is False and fail == []


def test_compare_fail_implies_compare_latest():
    cfg = _config(
        **{"--benchmark-memory-compare": False, "--benchmark-memory-compare-fail": ["peak:10%"]}
    )
    compare, fail = P._compare_requested(cfg)
    assert compare is True  # fail with no explicit compare → compare against latest
    assert fail == ["peak:10%"]


def test_compare_explicit_ref_is_kept():
    cfg = _config(**{"--benchmark-memory-compare": "0007"})
    compare, fail = P._compare_requested(cfg)
    assert compare == "0007" and fail == []


def test_memory_blobs_picks_only_recorded():
    blob = {"peak_bytes": 100, "peak_bytes_max": 100, "allocations": 1, "repeats": 1}
    benchmarks = [
        SimpleNamespace(fullname="t::a", extra_info={"benchmem": blob}),
        SimpleNamespace(fullname="t::b", extra_info={}),  # timing only
        SimpleNamespace(fullname="t::c", extra_info={"benchmem": "nope"}),  # malformed
    ]
    assert P._memory_blobs(benchmarks) == {"t::a": blob}


def test_load_baseline_reads_latest_and_blobs():
    blob = {"peak_bytes": 42, "peak_bytes_max": 42, "allocations": 2, "repeats": 1}
    runs = [
        ("0001_old.json", {"benchmarks": [{"fullname": "t::a", "extra_info": {"benchmem": blob}}]}),
        ("0002_new.json", {"benchmarks": [{"fullname": "t::a", "extra_info": {"benchmem": blob}}]}),
    ]

    class _Storage:
        def load(self, *globs):
            return iter(runs)

    label, blobs = P._load_baseline(_Storage(), True)
    assert label == "0002_new.json"  # the most recent wins
    assert blobs == {"t::a": blob}


def test_load_baseline_empty_storage():
    class _Storage:
        def load(self, *globs):
            return iter([])

    assert P._load_baseline(_Storage(), True) == (None, {})
