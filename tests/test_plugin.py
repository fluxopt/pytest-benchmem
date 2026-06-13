"""Exercises the benchmark_memory fixture end-to-end through a nested pytest run.

We run a tiny generated test suite with --benchmark-json and assert the produced
pytest-benchmark file carries both timing stats and our extra_info.peak_mib, then
that peakbench's readers lift both back out.
"""

from __future__ import annotations

import json
import platform

import pytest

from peakbench.snapshot import from_pytest_benchmark, memory_from_pytest_benchmark

pytest.importorskip("memray")
pytest.importorskip("pytest_benchmark")
pytestmark = pytest.mark.skipif(
    platform.system() == "Windows", reason="memray unavailable on Windows"
)

SUITE = """
def test_alloc(benchmark_memory):
    benchmark_memory(lambda: [0] * 500_000)

def test_pedantic(benchmark_memory):
    benchmark_memory.pedantic(lambda data: [x + 1 for x in data],
                              setup=lambda: ((list(range(1000)),), {}), rounds=2)

def test_time_only(benchmark):
    benchmark(lambda: sum(range(1000)))
"""


def _run_suite(pytester):
    pytester.makepyfile(SUITE)
    out = pytester.path / "bench.json"
    result = pytester.runpytest_subprocess(
        "--benchmark-only", f"--benchmark-json={out}", "-p", "no:cacheprovider"
    )
    result.assert_outcomes(passed=3)
    return out, json.loads(out.read_text())


def test_fixture_records_timing_and_memory(pytester):
    out, data = _run_suite(pytester)
    by_name = {b["name"]: b for b in data["benchmarks"]}

    # memory tests carry both stats (timing) and extra_info.peak_mib
    assert by_name["test_alloc"]["stats"]["min"] > 0
    assert by_name["test_alloc"]["extra_info"]["peak_mib"] > 0
    assert by_name["test_pedantic"]["extra_info"]["peak_mib"] > 0
    # the timing-only test has no peak recorded
    assert "peak_mib" not in by_name["test_time_only"].get("extra_info", {})

    # peakbench readers lift both back out of the one file
    _l, time_samples, tunit = from_pytest_benchmark(out)
    _l, mem_samples, munit = memory_from_pytest_benchmark(out)
    assert tunit == "s" and munit == "MiB"
    assert len(time_samples) == 3  # all three timed
    assert {s.id.split("::")[-1] for s in mem_samples} == {"test_alloc", "test_pedantic"}


def test_fixture_is_opt_in_per_test(pytester):
    """A test using only `benchmark` is untouched — no peak recorded."""
    _out, data = _run_suite(pytester)
    time_only = next(b for b in data["benchmarks"] if b["name"] == "test_time_only")
    assert time_only.get("extra_info", {}).get("peak_mib") is None
