"""Peak-memory measurement via ``memray`` — the core pytest-benchmem engine.

:func:`measure_memory` runs one action under a ``memray.Tracker`` and returns a
:class:`MemoryResult`: the peak in **bytes** (the source unit memray reports —
storing the raw integer is lossless and lets the display layer auto-scale
B/KiB/MiB/GiB), the worst peak across repeats, and the allocation count.
:func:`measure_peak` is the bare one-liner that returns just the peak bytes::

    from pytest_benchmem import measure_peak, measure_memory

    peak = measure_peak(lambda: build_model(1000))          # int bytes
    res = measure_memory(lambda: build_model(1000), repeats=5)
    res.peak_bytes, res.allocations, res.total_bytes        # mirror `memray stats`

Why memray and not RSS sampling: peak RSS (what ASV's ``peakmem`` and naive
samplers use) misses the numpy/C-allocation detail that's usually the point of
profiling a numeric library, and folds in interpreter baseline. memray's
``peak_memory`` tracks the allocator directly.
"""

from __future__ import annotations

import gc
import platform
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

#: A zero-arg callable doing the work that gets memory-tracked.
Action = Callable[[], object]

#: The three per-repeat quantities, in the blob's ``series`` sub-dict and as ``Measurement``
#: fields. Drives the series read-back so the names never drift between writer and reader.
SERIES_FIELDS = ("peak_bytes", "allocations", "total_bytes")


@dataclass(frozen=True)
class Measurement:
    """One repeat's raw ``memray stats`` numbers — peak high-water, allocation count,
    and total bytes allocated (cumulative churn, incl. temporaries GC later frees).
    """

    peak_bytes: int
    allocations: int
    total_bytes: int


@dataclass(frozen=True)
class MemoryResult:
    """A memory measurement across ``repeats`` passes, derived from the per-repeat samples.

    The per-repeat :attr:`samples` are the single source of truth — that's all the blob
    stores (the ``series``); everything else is derived from them on read.

    Peak memory is noisier than expected (GC timing, lazy imports, page cache), so the
    headline :attr:`peak_bytes` is the *minimum* peak — the cleanest "floor this can hit" —
    and :attr:`allocations` / :attr:`total_bytes` come from that same representative
    (min-peak) run, a coherent snapshot. :attr:`peak_bytes_max` is the worst peak, so the
    spread is visible.
    """

    samples: tuple[Measurement, ...]

    @property
    def repeats(self) -> int:
        """How many passes were measured."""
        return len(self.samples)

    @property
    def representative(self) -> Measurement:
        """The min-peak run — the one the headline peak/allocations/total_bytes come from."""
        return min(self.samples, key=lambda m: m.peak_bytes)

    @property
    def peak_bytes(self) -> int:
        """The headline peak — the minimum high-water across repeats (the cleanest floor)."""
        return self.representative.peak_bytes

    @property
    def peak_bytes_max(self) -> int:
        """The worst peak across repeats (equals :attr:`peak_bytes` with one repeat)."""
        return max(m.peak_bytes for m in self.samples)

    @property
    def allocations(self) -> int:
        """Allocation count from the representative (min-peak) run."""
        return self.representative.allocations

    @property
    def total_bytes(self) -> int:
        """Total bytes allocated by the representative (min-peak) run."""
        return self.representative.total_bytes

    def series(self, field: str) -> list[int]:
        """The per-repeat values of one :data:`SERIES_FIELDS` field."""
        return [getattr(m, field) for m in self.samples]

    def as_dict(self) -> dict[str, Any]:
        """The JSON blob stored under pytest-benchmark ``extra_info["benchmem"]``.

        Just the three per-repeat series, flat — no denormalized scalars and no
        ``repeats`` (it's ``len`` of any series). Everything else derives on read.
        """
        return {f: self.series(f) for f in SERIES_FIELDS}

    @classmethod
    def from_blob(cls, blob: Mapping[str, Any]) -> MemoryResult:
        """Rebuild from a blob's per-repeat series (one column per :data:`SERIES_FIELDS`)."""
        cols = [[int(v) for v in blob[f]] for f in SERIES_FIELDS]
        return cls(tuple(Measurement(*row) for row in zip(*cols, strict=True)))


def _require_memray() -> None:
    """Raise if memory measurement isn't supported — memray runs only on Linux/macOS."""
    if platform.system() not in ("Linux", "Darwin"):
        raise RuntimeError(
            "memory measurement requires memray, which supports only Linux and macOS "
            f"(this is {platform.system()}). Timing still works; run memory benchmarks "
            "on Linux or macOS."
        )


def _compute_statistics() -> Callable[[str], Any]:
    """Memray's per-run stats fn (what ``memray stats`` uses), or raise actionably.

    It's ``memray._memray.compute_statistics`` — internal, hence the upper-bounded
    ``memray`` pin and this guard: a version that moves/drops it fails loudly with
    a fix, not silently.
    """
    try:
        from memray._memray import compute_statistics
    except ImportError as exc:
        raise RuntimeError(
            "pytest-benchmem reads memray's per-run stats via "
            "memray._memray.compute_statistics (what `memray stats` uses); the installed "
            "memray doesn't expose it. Install a supported memray (the pin is in "
            "pytest-benchmem's deps), or report: "
            "https://github.com/fluxopt/pytest-benchmem/issues"
        ) from exc
    return compute_statistics


#: Substring of memray's error when a second ``Tracker`` is started while one is active.
#: memray raises a bare ``RuntimeError("No more than one Tracker instance can be active
#: at the same time")``; we match on this to turn it into an actionable message.
_NESTED_TRACKER_MARKER = "more than one Tracker"


def _track_once(action: Action) -> Measurement:
    """One fresh tracker run → a :class:`Measurement` via memray stats.

    memray allows only one active ``Tracker`` per process, so if one is already
    running — most often pytest-memray's ``--memray`` profiling the same test — the
    nested ``Tracker`` raises. We translate that into an actionable error rather than
    surfacing memray's terse one.
    """
    import memray

    compute_statistics = _compute_statistics()
    with tempfile.TemporaryDirectory(prefix="pytest-benchmem-") as tmp:
        out = Path(tmp) / "track.bin"  # memray must create the file itself
        try:
            with memray.Tracker(out):
                action()
        except RuntimeError as exc:
            if _NESTED_TRACKER_MARKER in str(exc):
                raise RuntimeError(
                    "pytest-benchmem couldn't start its memray pass because another memray "
                    "Tracker is already active — most likely pytest-memray's `--memray` running "
                    "on the same test. memray allows only one Tracker per process. Run the two "
                    "on different tests (or different sessions): pytest-memray for whole-test "
                    "limits/leaks, pytest-benchmem for the benchmarked action's memory."
                ) from exc
            raise
        s = compute_statistics(str(out))
        return Measurement(
            peak_bytes=int(s.peak_memory_allocated),
            allocations=int(s.total_num_allocations),
            total_bytes=int(s.total_memory_allocated),
        )


#: Adaptive-sampling defaults, used when ``repeats`` is ``None`` (the default). memray
#: gives an *exact* peak per pass — unlike timing, there's no resolution to average out — so
#: passes exist only to find the floor and quantify spread (this is sequential sampling, not
#: calibration in pytest-benchmark's timer-resolution sense). Rather than a fixed count that's
#: wasteful for deterministic code and too few for noisy code, run until the headline min
#: settles, bounded by these.
_ADAPTIVE_MIN_PASSES = 2  # always take ≥2 — the 1st pass carries one-time warmup the min sheds
_ADAPTIVE_MAX_PASSES = 10  # hard ceiling: cost is linear in passes, so cap the noisy case
_ADAPTIVE_PATIENCE = 2  # stop once this many consecutive passes set no new (lower) min


def measure_memory(
    action: Action,
    repeats: int | None = None,
    *,
    max_time: float | None = None,
    min_passes: int = _ADAPTIVE_MIN_PASSES,
    max_passes: int = _ADAPTIVE_MAX_PASSES,
    patience: int = _ADAPTIVE_PATIENCE,
) -> MemoryResult:
    """Run ``action()`` under ``memray.Tracker`` → :class:`MemoryResult`, one pass per repeat.

    Each pass gets a fresh tracker; the headline peak is the minimum across them (see
    :class:`MemoryResult`), and every pass's :class:`Measurement` is retained for spread stats.

    Two modes, by ``repeats``:

    - ``repeats=N`` (an int) — run exactly ``N`` passes. Fixed and reproducible; what CI
      gating and saved-baseline comparisons want.
    - ``repeats=None`` (default) — **sample adaptively**: keep running passes until the min
      stops improving (no new low for ``patience`` passes), bounded by ``min_passes`` (warmup
      is shed by the min, so always take ≥2), ``max_passes``, and an optional ``max_time``
      wall-clock budget. Deterministic code settles in a few passes; noisy code runs more,
      exactly where extra passes pay off.

    Args:
        action: The zero-argument callable to measure.
        repeats: Fixed pass count, or ``None`` to sample adaptively.
        max_time: Wall-clock budget (seconds) for adaptive sampling; ``None`` = no time bound.
        min_passes: Minimum passes when sampling adaptively.
        max_passes: Hard ceiling on passes when sampling adaptively.
        patience: Stop adaptive sampling after this many consecutive passes with no new min.

    Returns:
        A :class:`MemoryResult` over every pass run.
    """
    _require_memray()

    if repeats is not None:
        samples = [_run_pass(action) for _ in range(max(1, repeats))]
        return MemoryResult(tuple(samples))

    samples = []
    best: int | None = None
    stale = 0
    cap = max(min_passes, max_passes)
    start = perf_counter()
    while True:
        sample = _run_pass(action)
        samples.append(sample)
        if best is None or sample.peak_bytes < best:
            best, stale = sample.peak_bytes, 0
        else:
            stale += 1
        if len(samples) < min_passes:
            continue
        if len(samples) >= cap or stale >= patience:
            break
        if max_time is not None and perf_counter() - start >= max_time:
            break
    return MemoryResult(tuple(samples))


def _run_pass(action: Action) -> Measurement:
    """One tracked pass, then a ``gc.collect()`` so the next pass starts from a clean heap."""
    sample = _track_once(action)
    gc.collect()
    return sample


def measure_peak(action: Action, repeats: int | None = None) -> int:
    """Run ``action()`` under ``memray.Tracker`` and return peak **bytes**.

    The bare one-liner for a REPL or notebook; :func:`measure_memory` returns the
    full result (allocation count, spread). ``repeats`` behaves as there — ``None``
    (default) samples adaptively, an int forces a fixed pass count.

    Args:
        action: The zero-argument callable to measure.
        repeats: Fixed pass count, or ``None`` to sample adaptively.

    Returns:
        Peak resident bytes (the headline ``peak`` = min across passes).
    """
    return measure_memory(action, repeats=repeats).peak_bytes
