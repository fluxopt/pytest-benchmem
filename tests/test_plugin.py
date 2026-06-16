"""Exercises the benchmark_memory fixture end-to-end through a nested pytest run.

We run a tiny generated test suite with --benchmark-json and assert the produced
pytest-benchmark file carries both timing stats and our extra_info.benchmem blob,
then that pytest-benchmem's readers lift both back out.
"""

from __future__ import annotations

import json
import platform

import pytest

import pytest_benchmem.pytest_plugin as plugin
from pytest_benchmem.memray import Measurement, MemoryResult
from pytest_benchmem.snapshot import from_pytest_benchmark, memory_from_pytest_benchmark

pytest.importorskip("memray")
pytest.importorskip("pytest_benchmark")
pytestmark = pytest.mark.skipif(
    platform.system() == "Windows", reason="memray unavailable on Windows"
)

# --- ordering: the memray pass must run before timing (so memory is measured cold) ---


class _OrderSpyBenchmark:
    """Stand-in for pytest-benchmark's fixture that logs when the timing pass runs."""

    def __init__(self, events: list[str]) -> None:
        self.extra_info: dict[str, object] = {}
        self._events = events

    def __call__(self, fn, *a, **k):
        self._events.append("timing")
        return fn(*a, **k)

    def pedantic(self, target, args=(), kwargs=None, setup=None, **_):
        self._events.append("timing")
        return target(*args, **(kwargs or {}))


def _spy_measure(events: list[str]):
    """A measure_memory stand-in that logs when the memray pass runs (no real memray)."""

    def measure(action, repeats=None, **_):
        events.append("memory")
        action()
        return MemoryResult((Measurement(1, 1, 1),))

    return measure


def test_memory_runs_before_timing_call(monkeypatch):
    """Call form: the memray pass runs first (cold), then pytest-benchmark times the function."""
    events: list[str] = []
    monkeypatch.setattr(plugin, "measure_memory", _spy_measure(events))
    plugin.MemoryBenchmark(_OrderSpyBenchmark(events))(lambda: None)  # type: ignore[arg-type]
    assert events == ["memory", "timing"]


def test_memory_runs_before_timing_pedantic(monkeypatch):
    """Pedantic form: same order — memory first (cold), timing second."""
    events: list[str] = []
    monkeypatch.setattr(plugin, "measure_memory", _spy_measure(events))
    plugin.MemoryBenchmark(_OrderSpyBenchmark(events)).pedantic(lambda: None)  # type: ignore[arg-type]
    assert events == ["memory", "timing"]


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
    """By default a memory run prints ONE table: timing columns + peak only, no native table."""
    pytester.makepyfile(SUITE)
    result = pytester.runpytest_subprocess("--benchmark-only", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=3)
    out = result.stdout.str()
    assert "Min" in out and "peak·min" in out  # timing + the (spread) peak column, one table
    assert "allocated·" not in out  # allocated/allocations columns hidden by default (peak only)
    assert "also available" in out  # caption hints the hidden metrics exist
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
    assert "peak·min" in out and "allocated·" not in out  # our memory table, peak only by default


def test_memory_columns_flag_adds_opt_in_metrics(pytester):
    """--benchmark-memory-columns shows metrics beyond the peak-only default."""
    pytester.makepyfile(SUITE)
    result = pytester.runpytest_subprocess(
        "--benchmark-only", "--benchmark-memory-columns=peak,allocations", "-p", "no:cacheprovider"
    )
    result.assert_outcomes(passed=3)
    out = result.stdout.str()
    assert "peak·min" in out and "allocations·" in out  # both selected metrics shown
    assert "allocated·" not in out  # the one left out stays hidden


def test_memory_columns_bad_value_is_usage_error(pytester):
    """An unknown metric name fails fast as a clean usage error, not a traceback."""
    pytester.makepyfile(SUITE)
    result = pytester.runpytest_subprocess(
        "--benchmark-only", "--benchmark-memory-columns=bogus", "-p", "no:cacheprovider"
    )
    assert result.ret != 0
    assert "unknown memory metric" in (result.stderr.str() + result.stdout.str())


def test_memory_stats_bad_value_is_usage_error(pytester):
    """An unknown stat name fails fast as a clean usage error too."""
    pytester.makepyfile(SUITE)
    result = pytester.runpytest_subprocess(
        "--benchmark-only", "--benchmark-memory-stats=p99", "-p", "no:cacheprovider"
    )
    assert result.ret != 0
    assert "unknown memory stat" in (result.stderr.str() + result.stdout.str())


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
    assert alloc_blob["peak_bytes"][0] > 0
    assert alloc_blob["allocations"][0] > 0
    assert by_name["test_pedantic"]["extra_info"]["benchmem"]["peak_bytes"][0] > 0
    # the timing-only test has no memory recorded
    assert "benchmem" not in by_name["test_time_only"].get("extra_info", {})

    # pytest-benchmem readers lift both back out of the one file
    _l, time_samples, tunit = from_pytest_benchmark(out)
    _l, mem_samples, munit = memory_from_pytest_benchmark(out)
    assert tunit == "s" and munit == "B"
    assert len(time_samples) == 3  # all three timed
    assert {s.id.split("::")[-1] for s in mem_samples} == {"test_alloc", "test_pedantic"}


def test_pedantic_setup_is_untracked(pytester):
    """pedantic(setup=...) runs setup outside the memray tracker — its memory isn't counted."""
    pytester.makepyfile(
        "def test_x(benchmark_memory):\n"
        "    def setup():\n"
        "        _ = bytearray(80 * 1024 * 1024)  # 80 MiB in setup — must stay untracked\n"
        "    benchmark_memory.pedantic(\n"
        "        lambda: [bytearray(1024) for _ in range(100)], setup=setup, rounds=1\n"
        "    )\n"
    )
    out = pytester.path / "b.json"
    result = pytester.runpytest_subprocess(
        "--benchmark-only", f"--benchmark-json={out}", "-p", "no:cacheprovider"
    )
    result.assert_outcomes(passed=1)
    blob = json.loads(out.read_text())["benchmarks"][0]["extra_info"]["benchmem"]
    assert max(blob["peak_bytes"]) < 10 * 1024**2  # setup's 80 MiB outside the tracked peak


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
    assert (
        by_name["test_plain"]["extra_info"]["benchmem"]["peak_bytes"][0] > 0
    )  # memory now recorded
    assert by_name["test_plain_pedantic"]["extra_info"]["benchmem"]["peak_bytes"][0] > 0


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
    assert len(by_name["test_marked_fixture"]["extra_info"]["benchmem"]["peak_bytes"]) == 3
    assert len(by_name["test_marked_plain"]["extra_info"]["benchmem"]["peak_bytes"]) == 4


# A suite mixing a marked test with an unmarked one, to check flag/marker precedence.
GLOBAL_REPEATS_SUITE = """
import pytest

def test_unmarked(benchmark_memory):
    benchmark_memory(lambda: [0] * 200_000)

@pytest.mark.benchmem(repeats=2)
def test_marked(benchmark_memory):
    benchmark_memory(lambda: [0] * 200_000)
"""


def test_global_repeats_flag_sets_default(pytester):
    """--benchmark-memory-repeats sets repeats suite-wide, with no per-test marker."""
    pytester.makepyfile(SUITE)
    out = pytester.path / "bench.json"
    result = pytester.runpytest_subprocess(
        "--benchmark-only",
        "--benchmark-memory-repeats=3",
        f"--benchmark-json={out}",
        "-p",
        "no:cacheprovider",
    )
    result.assert_outcomes(passed=3)
    by_name = {b["name"]: b for b in json.loads(out.read_text())["benchmarks"]}
    assert len(by_name["test_alloc"]["extra_info"]["benchmem"]["peak_bytes"]) == 3


def test_marker_overrides_global_repeats(pytester):
    """A per-test marker wins over the suite-wide --benchmark-memory-repeats default."""
    pytester.makepyfile(GLOBAL_REPEATS_SUITE)
    out = pytester.path / "bench.json"
    result = pytester.runpytest_subprocess(
        "--benchmark-only",
        "--benchmark-memory-repeats=5",
        f"--benchmark-json={out}",
        "-p",
        "no:cacheprovider",
    )
    result.assert_outcomes(passed=2)
    by_name = {b["name"]: b for b in json.loads(out.read_text())["benchmarks"]}
    assert len(by_name["test_unmarked"]["extra_info"]["benchmem"]["peak_bytes"]) == 5
    assert len(by_name["test_marked"]["extra_info"]["benchmem"]["peak_bytes"]) == 2


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


def test_isolate_records_rss_series_in_json(pytester):
    """isolate=True runs each pass in a fresh process and records an `rss_bytes` series in the
    JSON alongside memray's `peak_bytes`. The benchmarked fn lives in its own module so it's a
    top-level, picklable target the spawned child can import."""
    pytester.makepyfile(
        workload="def build():\n    return [bytearray(1024) for _ in range(3000)]\n"
    )
    pytester.makepyfile(
        """
        import pytest
        from workload import build

        @pytest.mark.benchmem(isolate=True, repeats=1, warmup=0)
        def test_iso(benchmark_memory):
            benchmark_memory(build)
        """
    )
    out = pytester.path / "bench.json"
    result = pytester.runpytest_subprocess(
        "--benchmark-only", f"--benchmark-json={out}", "-p", "no:cacheprovider"
    )
    result.assert_outcomes(passed=1)
    blob = json.loads(out.read_text())["benchmarks"][0]["extra_info"]["benchmem"]
    assert "peak_bytes" in blob  # memray still measured, in the child
    assert blob["rss_bytes"][0] > 0  # whole-process resident high-water, recorded from the child


# --- @pytest.mark.benchmem(max_*=...): action-scoped absolute ceilings -----------


@pytest.mark.parametrize(
    ("value", "is_bytes", "expected"),
    [
        ("100MiB", True, 100 * 1024**2),
        ("2KiB", True, 2048.0),
        ("512B", True, 512.0),
        ("1.5GiB", True, int(1.5 * 1024**3)),
        (1024, True, 1024.0),  # a bare int is already base units
        (5000, False, 5000.0),  # allocations: a bare count
        ("5000", False, 5000.0),
    ],
)
def test_parse_limit_accepts_sizes_and_counts(value, is_bytes, expected):
    assert plugin._parse_limit("max_peak", value, is_bytes=is_bytes) == expected


@pytest.mark.parametrize(
    ("kwarg", "value", "is_bytes", "match"),
    [
        ("max_peak", "100ZB", True, "unknown unit"),
        ("max_peak", "lots", True, "number with an optional unit"),
        ("max_allocations", "5000B", False, "count takes no unit"),
        ("max_peak", True, True, "not a bool"),  # bool is an int subclass
        ("max_peak", -1, True, "non-negative"),
        ("max_peak", ["x"], True, "expected a number or a string"),
    ],
)
def test_parse_limit_rejects_bad_values(kwarg, value, is_bytes, match):
    with pytest.raises(ValueError, match=match):
        plugin._parse_limit(kwarg, value, is_bytes=is_bytes)


class _FakeMarker:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeNode:
    def __init__(self, marker):
        self._marker = marker

    def get_closest_marker(self, name):
        return self._marker


def test_limits_from_node_picks_only_max_kwargs():
    """Only ``max_*`` kwargs become limits; ``repeats`` (and a missing marker) don't."""
    node = _FakeNode(_FakeMarker(repeats=3, max_peak="2KiB", max_allocations=10))
    assert plugin._limits_from_node(node) == {"max_peak": 2048.0, "max_allocations": 10.0}
    assert plugin._limits_from_node(_FakeNode(None)) == {}


def test_warmup_from_node_marker_wins_else_default():
    """``benchmem(warmup=N)`` wins; no marker (and no config) falls back to the default 1."""
    assert plugin._warmup_from_node(_FakeNode(_FakeMarker(warmup=3))) == 3
    assert plugin._warmup_from_node(_FakeNode(_FakeMarker(warmup=0))) == 0  # explicit disable
    assert plugin._warmup_from_node(_FakeNode(_FakeMarker(repeats=2))) == 1  # no warmup kwarg
    assert plugin._warmup_from_node(_FakeNode(None)) == 1


def test_isolate_from_node_marker_wins_else_default():
    """``benchmem(isolate=...)`` wins; no marker (and no config) falls back to ``False``."""
    assert plugin._isolate_from_node(_FakeNode(_FakeMarker(isolate=True))) is True
    assert plugin._isolate_from_node(_FakeNode(_FakeMarker(isolate=False))) is False
    assert plugin._isolate_from_node(_FakeNode(_FakeMarker(repeats=2))) is False  # no isolate kwarg
    assert plugin._isolate_from_node(_FakeNode(None)) is False


def _result(peak: int, allocs: int = 1, total: int = 1) -> MemoryResult:
    return MemoryResult((Measurement(peak_bytes=peak, allocations=allocs, total_bytes=total),))


def test_enforce_limits_raises_over_ceiling():
    with pytest.raises(AssertionError, match=r"test_x: peak .* exceeds max_peak"):
        plugin._enforce_limits(_result(2_000_000), {"max_peak": 1_000_000}, "test_x")


def test_enforce_limits_passes_under_ceiling():
    plugin._enforce_limits(_result(500), {"max_peak": 1_000_000}, "test_x")  # no raise


def test_enforce_limits_gates_on_worst_pass_not_min():
    # A ceiling is a worst-case budget: min peak under it but one pass over it must still fail.
    res = MemoryResult(
        (
            Measurement(peak_bytes=500, allocations=1, total_bytes=1),
            Measurement(peak_bytes=2_000_000, allocations=1, total_bytes=1),
        )
    )
    with pytest.raises(AssertionError, match=r"peak .* exceeds max_peak"):
        plugin._enforce_limits(res, {"max_peak": 1_000_000}, "test_x")


def test_enforce_limits_counts_use_plain_number_and_no_name_prefix():
    with pytest.raises(AssertionError, match=r"^allocations 42 exceeds max_allocations 10$"):
        plugin._enforce_limits(_result(1, allocs=42), {"max_allocations": 10}, "")


# A suite that trips a ceiling on the fixture path and one well under it.
LIMIT_SUITE = """
import pytest

@pytest.mark.benchmem(max_peak="1KiB")
def test_over(benchmark_memory):
    benchmark_memory(lambda: [0] * 200_000)

@pytest.mark.benchmem(max_peak="500MiB")
def test_under(benchmark_memory):
    benchmark_memory(lambda: [0] * 200_000)
"""


def test_max_peak_marker_fails_over_passes_under(pytester):
    """The fixture path: a test over its max_peak fails, one under it passes."""
    pytester.makepyfile(LIMIT_SUITE)
    result = pytester.runpytest_subprocess("--benchmark-only", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(["*exceeds max_peak 1*KiB*"])


def test_max_peak_marker_fires_on_the_benchmark_memory_patch_path(pytester):
    """The --benchmark-memory patch enforces the ceiling on a plain benchmark() call too."""
    pytester.makepyfile(
        "import pytest\n"
        "@pytest.mark.benchmem(max_peak='1KiB')\n"
        "def test_over_plain(benchmark):\n"
        "    benchmark(lambda: [0] * 200_000)\n"
    )
    result = pytester.runpytest_subprocess(
        "--benchmark-only", "--benchmark-memory", "-p", "no:cacheprovider"
    )
    result.assert_outcomes(failed=1)


def test_max_peak_marker_is_noop_without_memory_measurement(pytester):
    """A plain benchmark() with the marker but no --benchmark-memory measures nothing,
    so there's no peak to gate on — the test passes (documented limitation)."""
    pytester.makepyfile(
        "import pytest\n"
        "@pytest.mark.benchmem(max_peak='1KiB')\n"
        "def test_unmeasured(benchmark):\n"
        "    benchmark(lambda: [0] * 200_000)\n"
    )
    result = pytester.runpytest_subprocess("--benchmark-only", "-p", "no:cacheprovider")
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
    out = cand.stdout.str()
    assert "Δ peak" in out and "base (" in out  # baseline folded into the combined table
    assert "Min" in out  # one table — timing + memory + compare, all together


def test_memory_compare_rejects_time_field(pytester):
    """--benchmark-memory-compare-fail gates memory only; time points back to pytest-benchmark."""
    storage = str(pytester.path / "store")
    _run_compare(pytester, _SMALL, storage, "--benchmark-autosave").assert_outcomes(passed=1)
    cand = _run_compare(pytester, _SMALL, storage, "--benchmark-memory-compare-fail=time:5%")
    assert cand.ret != 0
    cand.stderr.fnmatch_lines(["*can't gate on time*"])


# --- --benchmark-memory-profile: keep the .bin for debugging ---------------------

_TWO = (
    "def test_small(benchmark):\n    benchmark(lambda: [0] * 50_000)\n\n"
    "def test_big(benchmark):\n    benchmark(lambda: [0] * 6_000_000)\n"
)


def test_profile_no_gate_saves_every_measured(pytester):
    """Without a gate, --benchmark-memory-profile keeps a .bin per measured benchmark."""
    pytester.makepyfile(_TWO)
    out = pytester.path / "profiles"
    result = pytester.runpytest_subprocess(
        "--benchmark-only",
        "--benchmark-memory",
        f"--benchmark-memory-profile={out}",
        "-p",
        "no:cacheprovider",
    )
    result.assert_outcomes(passed=2)
    bins = {p.name for p in out.glob("*.bin")}
    assert any("test_small" in n for n in bins) and any("test_big" in n for n in bins)
    result.stdout.fnmatch_lines(["*saved 2 memory profile(s)*", "*memray flamegraph*"])


def test_profile_with_gate_saves_offenders_only(pytester):
    """With a fail-gate, only the regressing id's .bin is kept (clean ids get nothing)."""
    storage = str(pytester.path / "store")
    out = pytester.path / "profiles"
    _run_compare(pytester, _SMALL, storage, "--benchmark-autosave").assert_outcomes(passed=1)
    cand = _run_compare(
        pytester,
        _BIG,
        storage,
        "--benchmark-memory-compare-fail=peak:10%",
        f"--benchmark-memory-profile={out}",
    )
    assert cand.ret != 0  # the gate still fails the session
    bins = [p.name for p in out.glob("*.bin")]
    assert len(bins) == 1 and "test_m" in bins[0]  # only the offender's profile kept
    cand.stdout.fnmatch_lines(["*saved 1 memory profile(s)*", "*memray flamegraph*"])
