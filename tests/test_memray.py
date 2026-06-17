from __future__ import annotations

import json
import platform

import pytest

from pytest_benchmem import measure_memory, measure_peak
from pytest_benchmem.memray import Measurement, MemoryResult, _track_once
from pytest_benchmem.snapshot import memory_from_pytest_benchmark

pytest.importorskip("memray")
pytestmark = pytest.mark.skipif(
    platform.system() == "Windows", reason="memray unavailable on Windows"
)


def test_measure_peak_returns_positive_bytes():
    peak = measure_peak(lambda: [0] * 1_000_000)
    assert isinstance(peak, int)
    assert peak > 1_000_000  # a list of 1e6 ints is several MB; bytes, not MiB


def test_nested_tracker_raises_actionable_error(tmp_path):
    """If a memray Tracker is already active (e.g. pytest-memray's --memray on the same
    test), benchmem's pass re-raises memray's terse error as an actionable one."""
    import memray

    # outer Tracker stands in for pytest-memray's --memray; it must be active first
    with (
        memray.Tracker(tmp_path / "outer.bin"),
        pytest.raises(RuntimeError, match="another memray Tracker is already active"),
    ):
        measure_memory(lambda: [0] * 1000)


def test_repeats_takes_min_of_n():
    # min-of-N: a smaller allocation never reports more than a larger one would.
    small = measure_peak(lambda: [0] * 100_000, repeats=3)
    big = measure_peak(lambda: [0] * 5_000_000, repeats=3)
    assert big > small


def test_keep_bin_retains_the_profile(tmp_path):
    binp = tmp_path / "sub" / "track.bin"
    _track_once(lambda: [bytearray(1024) for _ in range(50)], keep_bin=binp)
    assert binp.exists() and binp.stat().st_size > 0  # parent created, .bin kept


def test_measure_memory_keep_bin_retains_first_pass(tmp_path):
    binp = tmp_path / "track.bin"
    measure_memory(lambda: [bytearray(512) for _ in range(20)], repeats=3, keep_bin=binp)
    assert binp.exists()  # adaptive/fixed passes still leave exactly the one retained bin


def test_native_capture_records_native_traces_in_kept_bin(tmp_path):
    # native=True flips memray's native_traces on for the kept .bin, so a flamegraph can
    # attribute C/Rust frames instead of one opaque native bucket.
    import memray

    binp = tmp_path / "native.bin"
    _track_once(lambda: [bytearray(1024) for _ in range(100)], keep_bin=binp, native=True)
    assert memray.FileReader(str(binp)).metadata.has_native_traces

    plain = tmp_path / "plain.bin"
    _track_once(lambda: [bytearray(1024) for _ in range(100)], keep_bin=plain, native=False)
    assert not memray.FileReader(str(plain)).metadata.has_native_traces


def test_native_ignored_without_kept_bin(tmp_path):
    # native only enriches a *kept* profile; a discarded pass gains nothing, so it's a no-op
    # (and must not error). measure_memory with native but no keep_bin still measures cleanly.
    res = measure_memory(lambda: [bytearray(512) for _ in range(20)], repeats=2, native=True)
    assert res.peak_bytes > 0


def test_measure_memory_native_enriches_only_the_kept_pass(tmp_path):
    import memray

    binp = tmp_path / "track.bin"
    measure_memory(
        lambda: [bytearray(512) for _ in range(40)], repeats=3, keep_bin=binp, native=True
    )
    assert memray.FileReader(str(binp)).metadata.has_native_traces


def test_kept_bin_is_a_valid_memray_capture(tmp_path):
    # the retained .bin must be renderable by memray's own reporters (flamegraph/tree/…)
    binp = tmp_path / "track.bin"
    _track_once(lambda: [bytearray(1024) for _ in range(100)], keep_bin=binp)
    from memray._memray import compute_statistics

    stats = compute_statistics(str(binp))
    assert stats.peak_memory_allocated > 0  # a real capture memray can read back


def test_setup_runs_untracked_before_each_pass():
    calls = {"n": 0}

    def setup():
        calls["n"] += 1
        _ = bytearray(60 * 1024 * 1024)  # 60 MiB allocated in setup — must NOT be counted

    res = measure_memory(lambda: [bytearray(1024) for _ in range(200)], repeats=4, setup=setup)
    assert calls["n"] == 5  # setup ran before the warmup run and before each of the 4 passes
    assert res.peak_bytes < 10 * 1024**2  # setup's 60 MiB is outside the tracker


def test_setup_makes_stateful_samples_independent():
    # a stateful action: the first call fills a carried-over cache (big), later calls reuse it
    # (small). Without setup, the warmup run fills the cache, so every measured pass is warm and
    # the headline min reads the *warm* under-estimate. With setup rebuilding fresh state per
    # pass (warmup included), every sample is cold and the min reflects the true allocation.
    cache: dict[str, bytearray] = {}

    def stateful():
        if "buf" not in cache:
            cache["buf"] = bytearray(40 * 1024 * 1024)  # allocated only when state is fresh
        return cache["buf"]

    drift = measure_memory(stateful, repeats=4)
    assert drift.peak_bytes < 10 * 1024**2  # warmup filled the cache → all passes warm → low min

    cache.clear()
    cold = measure_memory(stateful, repeats=4, setup=cache.clear)  # rebuild fresh state per pass
    assert cold.peak_bytes > 30 * 1024**2  # every sample is cold → min ≈ the true 40 MiB


def test_measure_memory_returns_result_with_allocations():
    res = measure_memory(lambda: [bytearray(1024) for _ in range(50)], repeats=2)
    assert isinstance(res, MemoryResult)
    assert res.repeats == 2
    assert res.allocations > 0
    assert res.peak_bytes > 0
    assert res.peak_bytes_max >= res.peak_bytes  # reported peak is the floor
    assert res.peak_bytes == min(res.as_dict()["peak_bytes"])  # headline = min of the series


def test_total_bytes_mirrors_memray_stats():
    # churn: many temporaries freed each iteration — total allocated >> peak.
    def action():
        for _ in range(20):
            _ = [bytearray(4096) for _ in range(1000)]

    res = measure_memory(action, repeats=1)
    assert res.total_bytes > 0
    assert res.total_bytes >= res.peak_bytes  # cumulative ≥ high-water mark
    assert res.as_dict()["total_bytes"] == [res.total_bytes]  # one-repeat series


def test_blob_roundtrips_engine_to_reader(tmp_path):
    """Producer↔consumer contract in one place: the engine's ``as_dict()`` carries
    exactly the documented keys, and a reader lifts a metric back out of a real blob
    (the synthetic-JSON unit tests only assume this shape; here it's pinned)."""
    blob = measure_memory(lambda: [bytearray(1024) for _ in range(200)]).as_dict()
    assert set(blob) == {"peak_bytes", "allocations", "total_bytes"}  # flat per-repeat series
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
    assert (samples[0].value, unit) == (float(min(blob["peak_bytes"])), "B")  # headline = min


def _feed_peaks(monkeypatch, peaks):
    """Drive ``measure_memory``'s adaptive loop with a fixed sequence of per-pass peaks."""
    import pytest_benchmem.memray as m

    seq = iter(peaks)
    monkeypatch.setattr(m, "_require_memray", lambda: None)
    monkeypatch.setattr(
        m, "_track_once", lambda action, keep_bin=None, native=False: Measurement(next(seq), 1, 1)
    )


def test_explicit_repeats_runs_exactly_n(monkeypatch):
    # An int repeats forces a fixed count — no calibration, even if the floor settled.
    _feed_peaks(monkeypatch, [100] * 20)
    assert measure_memory(lambda: None, repeats=5).repeats == 5


def test_adaptive_stops_once_floor_settles(monkeypatch):
    # Constant peak: the min never improves, so it stops as soon as patience is exhausted —
    # a few passes, not the cap.
    _feed_peaks(monkeypatch, [100] * 20)
    res = measure_memory(lambda: None)
    assert 2 <= res.repeats < 10  # ≥ min_passes, well short of the cap


def test_adaptive_takes_at_least_min_passes(monkeypatch):
    # Even when pass 1 is already low, take ≥2 so the warmup pass can't be the lone sample.
    _feed_peaks(monkeypatch, [10] * 20)
    assert measure_memory(lambda: None).repeats >= 2


def test_adaptive_runs_to_cap_while_floor_keeps_dropping(monkeypatch):
    # A strictly-decreasing peak always sets a new min → never goes stale → hits the cap.
    _feed_peaks(monkeypatch, list(range(10_000, 0, -100)))
    assert measure_memory(lambda: None).repeats == 10  # _ADAPTIVE_MAX_PASSES


def test_adaptive_honors_max_time(monkeypatch):
    # A decreasing peak would run to the cap, but the wall-clock budget cuts it short.
    import pytest_benchmem.memray as m

    _feed_peaks(monkeypatch, list(range(10_000, 0, -100)))
    clock = iter([0.0, 0.0, 0.0, 100.0])  # start, then below-budget until the 3rd check
    monkeypatch.setattr(m, "perf_counter", lambda: next(clock))
    res = measure_memory(lambda: None, max_time=5.0)
    assert 2 <= res.repeats < 10  # stopped by the budget, before the cap


def test_compute_statistics_missing_raises_actionably(monkeypatch):
    import sys
    import types

    import pytest_benchmem.memray as m

    # simulate a memray that no longer exposes the internal stats fn
    monkeypatch.setitem(sys.modules, "memray._memray", types.ModuleType("memray._memray"))
    with pytest.raises(RuntimeError, match="compute_statistics"):
        m._compute_statistics()


# --- isolate=True: a fresh child process per pass, recording whole-process RSS ---


def _alloc_for_isolation():
    """Module-level (so it's picklable for the spawn child) ~2 MiB allocation."""
    return [bytearray(1024) for _ in range(2000)]


def test_isolate_records_rss_from_child():
    res = measure_memory(_alloc_for_isolation, repeats=1, warmup=0, isolate=True)
    assert res.peak_bytes > 0  # memray still measured, in the child
    assert res.rss_bytes is not None and res.rss_bytes > 0  # whole-process resident, from the child
    assert all(m.rss_bytes is not None for m in res.samples)
    assert res.as_dict()["rss_bytes"][0] == res.rss_bytes  # series carried in the blob


def test_in_process_run_has_no_rss():
    res = measure_memory(_alloc_for_isolation, repeats=2, warmup=0)
    assert res.rss_bytes is None  # no attributable process-global RSS in-process
    assert "rss_bytes" not in res.as_dict()  # optional series omitted, blob stays back-compatible


def test_isolate_rejects_unpicklable_action():
    with pytest.raises(RuntimeError, match="picklable"):
        measure_memory(lambda: bytearray(1024), repeats=1, warmup=0, isolate=True)


def _consume(buf: bytes) -> int:
    return len(buf)  # module-level so the partial is picklable


def test_isolate_warns_on_heavy_pickled_action():
    # a partial closing over a big pre-built object pickles heavy → rss would measure
    # deserializing it, not building it. Warn (the build-inside-the-callable rule).
    from functools import partial

    action = partial(_consume, bytes(2 * 1024 * 1024))  # 2 MiB shipped in the pickle
    with pytest.warns(UserWarning, match="deserializing"):
        measure_memory(action, repeats=1, warmup=0, isolate=True)
