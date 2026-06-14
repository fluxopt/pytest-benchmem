"""Exercises the benchmark_memory fixture end-to-end through a nested pytest run.

We run a tiny generated test suite with --benchmark-json and assert the produced
pytest-benchmark file carries both timing stats and our extra_info.benchmem blob,
then that pytest-benchmem's readers lift both back out.
"""

from __future__ import annotations

import json
import platform

import pytest

from pytest_benchmem.snapshot import from_pytest_benchmark, memory_from_pytest_benchmark

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


def test_combined_table_is_default(pytester):
    """By default a memory run prints ONE table: timing columns + memory, no native table."""
    pytester.makepyfile(SUITE)
    result = pytester.runpytest_subprocess("--benchmark-only", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=3)
    out = result.stdout.str()
    assert "Min" in out and "peak" in out and "allocs" in out  # timing + memory, one table
    assert "OPS: Operations Per Second" not in out  # pytest-benchmark's own table is suppressed
    assert "│" in out  # divider between timing and memory
    assert "separate, untimed pass" in out  # caption flags memory's distinct provenance


def test_split_table_keeps_native_and_separate_memory(pytester):
    """--benchmark-memory-table=split leaves pytest-benchmark's table and adds ours below."""
    pytester.makepyfile(SUITE)
    result = pytester.runpytest_subprocess(
        "--benchmark-only", "--benchmark-memory-table=split", "-p", "no:cacheprovider"
    )
    result.assert_outcomes(passed=3)
    out = result.stdout.str()
    assert "OPS: Operations Per Second" in out  # native pytest-benchmark table present
    assert "peak" in out and "allocs" in out  # our separate memory table present


def test_combined_table_respects_grouping(pytester):
    """--benchmark-group-by=group yields one combined table per group (timing + memory)."""
    pytester.makepyfile("""
        import pytest

        @pytest.mark.benchmark(group="alpha")
        def test_a(benchmark_memory):
            benchmark_memory(lambda: [0] * 100_000)

        @pytest.mark.benchmark(group="beta")
        def test_b(benchmark_memory):
            benchmark_memory(lambda: [0] * 200_000)
    """)
    result = pytester.runpytest_subprocess(
        "--benchmark-only", "--benchmark-group-by=group", "-p", "no:cacheprovider"
    )
    result.assert_outcomes(passed=2)
    out = result.stdout.str()
    assert "benchmark 'alpha'" in out and "benchmark 'beta'" in out  # one table per group
    assert "peak" in out  # memory folded into each


def test_fixture_records_timing_and_memory(pytester):
    out, data = _run_suite(pytester)
    by_name = {b["name"]: b for b in data["benchmarks"]}

    # memory tests carry both stats (timing) and the extra_info.benchmem blob
    assert by_name["test_alloc"]["stats"]["min"] > 0
    alloc_blob = by_name["test_alloc"]["extra_info"]["benchmem"]
    assert alloc_blob["peak_bytes"] > 0
    assert alloc_blob["allocations"] > 0
    assert by_name["test_pedantic"]["extra_info"]["benchmem"]["peak_bytes"] > 0
    # the timing-only test has no memory recorded
    assert "benchmem" not in by_name["test_time_only"].get("extra_info", {})

    # pytest-benchmem readers lift both back out of the one file
    _l, time_samples, tunit = from_pytest_benchmark(out)
    _l, mem_samples, munit = memory_from_pytest_benchmark(out)
    assert tunit == "s" and munit == "B"
    assert len(time_samples) == 3  # all three timed
    assert {s.id.split("::")[-1] for s in mem_samples} == {"test_alloc", "test_pedantic"}


def test_fixture_is_opt_in_per_test(pytester):
    """Without --benchmark-memory, a plain `benchmark` test records no memory."""
    _out, data = _run_suite(pytester)
    time_only = next(b for b in data["benchmarks"] if b["name"] == "test_time_only")
    assert time_only.get("extra_info", {}).get("benchmem") is None


# A suite using only the stock `benchmark` fixture — no benchmark_memory anywhere.
PLAIN_SUITE = """
def test_plain(benchmark):
    benchmark(lambda: [0] * 500_000)

def test_plain_pedantic(benchmark):
    benchmark.pedantic(lambda data: [x + 1 for x in data],
                       setup=lambda: ((list(range(1000)),), {}), rounds=2)
"""


def _run_plain(pytester, *extra):
    pytester.makepyfile(PLAIN_SUITE)
    out = pytester.path / "bench.json"
    result = pytester.runpytest_subprocess(
        "--benchmark-only", f"--benchmark-json={out}", "-p", "no:cacheprovider", *extra
    )
    result.assert_outcomes(passed=2)
    return json.loads(out.read_text())


def test_benchmark_memory_flag_augments_plain_benchmark(pytester):
    """--benchmark-memory records memory for stock benchmark() calls, no test changes."""
    data = _run_plain(pytester, "--benchmark-memory")
    by_name = {b["name"]: b for b in data["benchmarks"]}
    assert by_name["test_plain"]["stats"]["min"] > 0  # timing still works
    assert by_name["test_plain"]["extra_info"]["benchmem"]["peak_bytes"] > 0  # memory now recorded
    assert by_name["test_plain_pedantic"]["extra_info"]["benchmem"]["peak_bytes"] > 0


def test_no_flag_leaves_plain_benchmark_memory_free(pytester):
    """Without the flag, the same plain suite records no memory (and isn't patched)."""
    data = _run_plain(pytester)  # no --benchmark-memory
    for b in data["benchmarks"]:
        assert b.get("extra_info", {}).get("benchmem") is None


# A suite exercising the @pytest.mark.benchmem(repeats=N) marker on both paths.
MARKER_SUITE = """
import pytest

@pytest.mark.benchmem(repeats=3)
def test_marked_fixture(benchmark_memory):
    benchmark_memory(lambda: [0] * 200_000)

@pytest.mark.benchmem(repeats=4)
def test_marked_plain(benchmark):
    benchmark(lambda: [0] * 200_000)
"""


def test_benchmem_marker_sets_repeats(pytester):
    """The marker drives repeats for the fixture and the --benchmark-memory patch alike."""
    pytester.makepyfile(MARKER_SUITE)
    out = pytester.path / "bench.json"
    result = pytester.runpytest_subprocess(
        "--benchmark-only",
        "--benchmark-memory",
        f"--benchmark-json={out}",
        "-p",
        "no:cacheprovider",
    )
    result.assert_outcomes(passed=2)
    by_name = {b["name"]: b for b in json.loads(out.read_text())["benchmarks"]}
    assert by_name["test_marked_fixture"]["extra_info"]["benchmem"]["repeats"] == 3
    assert by_name["test_marked_plain"]["extra_info"]["benchmem"]["repeats"] == 4


def test_benchmem_marker_is_registered(pytester):
    """The marker is declared, so --strict-markers doesn't reject it."""
    pytester.makepyfile(
        "import pytest\n"
        "@pytest.mark.benchmem(repeats=2)\n"
        "def test_x(benchmark_memory):\n"
        "    benchmark_memory(lambda: [0] * 1000)\n"
    )
    result = pytester.runpytest_subprocess(
        "--benchmark-only", "--strict-markers", "-p", "no:cacheprovider"
    )
    result.assert_outcomes(passed=1)


# --- inline --benchmark-memory-compare[-fail] ------------------------------------

_SMALL = "def test_m(benchmark_memory):\n    benchmark_memory(lambda: [0] * 100_000)\n"
_BIG = "def test_m(benchmark_memory):\n    benchmark_memory(lambda: [0] * 6_000_000)\n"


def _run_compare(pytester, body, storage, *extra):
    pytester.makepyfile(body)
    return pytester.runpytest_subprocess(
        "--benchmark-only",
        f"--benchmark-storage={storage}",
        "-p",
        "no:cacheprovider",
        *extra,
    )


def test_memory_compare_fails_on_regression(pytester):
    """A big candidate vs a small saved baseline trips --benchmark-memory-compare-fail."""
    storage = str(pytester.path / "store")
    base = _run_compare(pytester, _SMALL, storage, "--benchmark-autosave")
    base.assert_outcomes(passed=1)

    cand = _run_compare(
        pytester, _BIG, storage, "--benchmark-memory-compare-fail=peak:10%"
    )  # fail implies compare-against-latest; ~48MB vs ~0.8MB is well over 10%
    assert cand.ret != 0
    cand.stdout.fnmatch_lines(["*Memory regressions over threshold*"])


def test_memory_compare_passes_within_threshold(pytester):
    """Re-running the same small suite stays within a generous threshold → exit 0."""
    storage = str(pytester.path / "store")
    base = _run_compare(pytester, _SMALL, storage, "--benchmark-autosave")
    base.assert_outcomes(passed=1)

    cand = _run_compare(
        pytester,
        _SMALL,
        storage,
        "--benchmark-memory-compare",
        "--benchmark-memory-compare-fail=peak:50%",
    )
    assert cand.ret == 0
    cand.stdout.fnmatch_lines(["*Memory*vs*"])  # the combined table names the baseline


def test_memory_compare_rejects_time_field(pytester):
    """--benchmark-memory-compare-fail gates memory only; time points back to pytest-benchmark."""
    storage = str(pytester.path / "store")
    _run_compare(pytester, _SMALL, storage, "--benchmark-autosave").assert_outcomes(passed=1)
    cand = _run_compare(pytester, _SMALL, storage, "--benchmark-memory-compare-fail=time:5%")
    assert cand.ret != 0
    cand.stderr.fnmatch_lines(["*can't gate on time*"])
