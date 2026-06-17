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


#: The three per-repeat quantities memray always yields, in the blob's ``series`` sub-dict and
#: as ``Measurement`` fields. Drives the series read-back so names never drift writer↔reader.
SERIES_FIELDS = ("peak_bytes", "allocations", "total_bytes")

#: Per-repeat series present in the blob only when measured. ``rss_bytes`` (whole-process
#: resident high-water) comes from an **isolated** pass; absent for in-process runs. ``from_blob``
#: tolerates its absence, so old/in-process blobs stay valid.
OPTIONAL_SERIES_FIELDS = ("rss_bytes",)


@dataclass(frozen=True)
class Measurement:
    """One repeat's raw numbers — memray's peak high-water, allocation count, and total bytes
    allocated (cumulative churn, incl. temporaries GC later frees), plus an optional
    whole-process resident high-water.

    ``rss_bytes`` is ``getrusage``'s ``ru_maxrss`` from an **isolated** pass (a fresh child
    process); ``None`` in-process, where a process-global RSS isn't attributable to the action.
    """

    peak_bytes: int
    allocations: int
    total_bytes: int
    rss_bytes: int | None = None


@dataclass(frozen=True)
class MemoryResult:
    """A memory measurement across ``repeats`` passes, derived from the per-repeat samples.

    The per-repeat :attr:`samples` are the single source of truth — that's all the blob
    stores (the ``series``); everything else is derived from them on read.

    The headline :attr:`peak_bytes` is the **minimum** peak across passes — the fresh-process
    floor, unbiased by the in-process warm plateau (repeated runs fragment/grow arenas and
    allocate more) that a central stat would report. :attr:`allocations` / :attr:`total_bytes`
    come from that same min-peak run (a coherent snapshot); :attr:`peak_bytes_max` is the worst
    peak, so the spread is visible. A warm-plateau / steady-state read is available via the
    ``mean`` / ``median`` ``--stat``. A single pass collapses all of these to its own values.
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
        """The headline peak — the minimum high-water across passes (the fresh-process floor)."""
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

    @property
    def rss_bytes(self) -> int | None:
        """Headline whole-process RSS — the **minimum** ``ru_maxrss`` across isolated passes
        (the cold floor, like :attr:`peak_bytes`), or ``None`` if memory wasn't measured in
        isolation (in-process has no attributable process-global RSS).
        """
        present = [m.rss_bytes for m in self.samples if m.rss_bytes is not None]
        return min(present) if present else None

    def series(self, field: str) -> list[Any]:
        """The per-repeat values of one series field (``SERIES_FIELDS`` or optional)."""
        return [getattr(m, field) for m in self.samples]

    def as_dict(self) -> dict[str, Any]:
        """The JSON blob stored under pytest-benchmark ``extra_info["benchmem"]``.

        The three core per-repeat series, flat, plus any :data:`OPTIONAL_SERIES_FIELDS`
        that were measured (all-or-nothing per result). No denormalized scalars and no
        ``repeats`` (it's ``len`` of any series). Everything else derives on read.
        """
        blob: dict[str, Any] = {f: self.series(f) for f in SERIES_FIELDS}
        for f in OPTIONAL_SERIES_FIELDS:
            vals = self.series(f)
            if vals and all(v is not None for v in vals):
                blob[f] = vals
        return blob

    @classmethod
    def from_blob(cls, blob: Mapping[str, Any]) -> MemoryResult:
        """Rebuild from a blob's per-repeat series. Core columns are required; any
        :data:`OPTIONAL_SERIES_FIELDS` are read when present (else left ``None``).
        """
        core = {f: [int(v) for v in blob[f]] for f in SERIES_FIELDS}
        optional = {f: [int(v) for v in blob[f]] for f in OPTIONAL_SERIES_FIELDS if f in blob}
        n = len(next(iter(core.values())))
        samples = tuple(
            Measurement(
                **{f: col[i] for f, col in core.items()},
                **{f: col[i] for f, col in optional.items()},
            )
            for i in range(n)
        )
        return cls(samples)


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


def _track_to(out: Path, action: Action, *, native: bool = False) -> Measurement:
    """Track ``action`` to the ``out`` ``.bin`` (which memray creates) → a :class:`Measurement`.

    With ``native=True`` the tracker also captures native (C/C++/Rust) stacks, so a flamegraph
    of the kept ``.bin`` attributes memory inside extension code (polars/numpy/solver bindings)
    instead of collapsing it into one unresolved ``??? at ???`` bucket. It costs runtime and a
    bigger ``.bin``, so it's only used for a *kept* profile (see :func:`_track_once`).

    memray allows only one active ``Tracker`` per process, so if one is already
    running — most often pytest-memray's ``--memray`` profiling the same test — the
    nested ``Tracker`` raises. We translate that into an actionable error rather than
    surfacing memray's terse one.
    """
    import memray

    compute_statistics = _compute_statistics()
    try:
        with memray.Tracker(out, native_traces=native):
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


def _track_once(action: Action, keep_bin: Path | None = None, native: bool = False) -> Measurement:
    """One fresh tracker run → a :class:`Measurement`.

    With ``keep_bin`` the profile ``.bin`` is written there and retained (for a later
    :func:`render_flamegraph`); otherwise it goes to a temp dir and is discarded. ``native``
    capture is honored only for a kept ``.bin`` — a discarded profile gains nothing from the
    extra runtime and disk cost.
    """
    if keep_bin is not None:
        keep_bin.parent.mkdir(parents=True, exist_ok=True)
        keep_bin.unlink(missing_ok=True)  # memray must create the file itself
        return _track_to(keep_bin, action, native=native)
    with tempfile.TemporaryDirectory(prefix="pytest-benchmem-") as tmp:
        return _track_to(Path(tmp) / "track.bin", action)


#: Adaptive-sampling defaults, used when ``repeats`` is ``None`` (the default). memray
#: gives an *exact* peak per pass — unlike timing, there's no resolution to average out — so
#: passes exist only to find the floor and quantify spread (this is sequential sampling, not
#: calibration in pytest-benchmark's timer-resolution sense). Rather than a fixed count that's
#: wasteful for deterministic code and too few for noisy code, run until the headline min
#: settles, bounded by these.
_ADAPTIVE_MIN_PASSES = 2  # always take ≥2 — one pass can't show the run-to-run spread
_ADAPTIVE_MAX_PASSES = 10  # hard ceiling: cost is linear in passes, so cap the noisy case
_ADAPTIVE_PATIENCE = 2  # stop once this many consecutive passes set no new (lower) min
_DEFAULT_WARMUP = 1  # untracked dry-run(s) before measuring, to shed one-time allocations


def measure_memory(
    action: Action,
    repeats: int | None = None,
    *,
    warmup: int = _DEFAULT_WARMUP,
    isolate: bool = False,
    max_time: float | None = None,
    min_passes: int = _ADAPTIVE_MIN_PASSES,
    max_passes: int = _ADAPTIVE_MAX_PASSES,
    patience: int = _ADAPTIVE_PATIENCE,
    keep_bin: Path | None = None,
    native: bool = False,
    setup: Action | None = None,
) -> MemoryResult:
    """Run ``action()`` under ``memray.Tracker`` → :class:`MemoryResult`, one pass per repeat.

    ``warmup`` untracked dry-runs run first to shed one-time costs; then each measured pass
    gets a fresh tracker. The headline is the **min** across passes (see :class:`MemoryResult`);
    every pass's :class:`Measurement` is kept for spread stats.

    With ``isolate=True`` each measured pass runs in a **fresh spawned process** (each warming
    itself), and that child's whole-process resident high-water (``ru_maxrss``) is recorded as
    :attr:`Measurement.rss_bytes` — a physical-memory reading attributable to the action, which
    an in-process pass can't give. The action (and ``setup``) must be **picklable** (a top-level
    callable, not a lambda/closure); ``keep_bin`` is ignored in this mode.

    Two modes, by ``repeats``:

    - ``repeats=N`` (an int) — run exactly ``N`` passes. Fixed and reproducible; what CI
      gating and saved-baseline comparisons want.
    - ``repeats=None`` (default) — **sample adaptively**: keep running passes until the min
      stops moving (no new low for ``patience`` passes), bounded by ``min_passes`` (≥2),
      ``max_passes``, and an optional ``max_time`` budget. Deterministic code settles in a few
      passes; noisy code runs more.

    Args:
        action: The zero-argument callable to measure.
        repeats: Fixed pass count, or ``None`` to sample adaptively.
        warmup: Untracked dry-runs (``setup`` + ``action``) before measuring; ``0`` disables.
        isolate: Run each pass in a fresh spawned process and record its ``ru_maxrss`` as
            :attr:`Measurement.rss_bytes`. Requires a picklable ``action``/``setup``.
        max_time: Wall-clock budget (seconds) for adaptive sampling; ``None`` = no time bound.
        min_passes: Minimum passes when sampling adaptively.
        max_passes: Hard ceiling on passes when sampling adaptively.
        patience: Stop adaptive sampling after this many consecutive passes with no new min.
        keep_bin: If set, the *first* pass's profile ``.bin`` is retained here (for a later
            :func:`render_flamegraph`); the rest still go to temp dirs and are discarded.
        native: Capture native (C/C++/Rust) stacks in the **kept** ``.bin`` so a flamegraph can
            attribute memory inside extension code instead of an opaque native bucket. Costs
            runtime and disk; only meaningful with ``keep_bin`` (ignored otherwise).
        setup: Optional zero-arg callable run **untracked** before each pass (and each warmup
            run) — its allocations are not measured. Use it to rebuild fresh state so a stateful
            ``action`` (one that caches on or mutates a carried-over object) gives *independent*
            samples instead of a decaying/accumulating series. Mirrors pytest-benchmark's
            ``pedantic(setup=...)``.

    Returns:
        A :class:`MemoryResult` over every measured pass (warmup runs are not retained).
    """
    _require_memray()

    # In-process warmup happens once, here; isolated passes each warm inside their own child.
    if not isolate:
        for _ in range(max(0, warmup)):
            if setup is not None:
                setup()
            action()
        if warmup > 0:
            gc.collect()  # clean heap for the first measured pass

    def _one(first: bool) -> Measurement:
        if isolate:
            return _isolated_run(action, setup, warmup)
        return _run_pass(action, setup=setup, keep_bin=keep_bin if first else None, native=native)

    if repeats is not None:
        samples = [_one(i == 0) for i in range(max(1, repeats))]
        return MemoryResult(tuple(samples))

    samples = []
    best: int | None = None
    stale = 0
    cap = max(min_passes, max_passes)
    start = perf_counter()
    while True:
        sample = _one(not samples)
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


def _run_pass(
    action: Action,
    setup: Action | None = None,
    keep_bin: Path | None = None,
    native: bool = False,
) -> Measurement:
    """``setup()`` (untracked) then one tracked pass, then a ``gc.collect()`` for a clean heap."""
    if setup is not None:
        setup()  # rebuild fresh state outside the tracker — its memory isn't counted
    sample = _track_once(action, keep_bin=keep_bin, native=native)
    gc.collect()
    return sample


def _ru_maxrss_bytes() -> int:
    """Whole-process resident high-water (``getrusage`` ``ru_maxrss``), normalized to **bytes**.

    ``ru_maxrss`` is reported in **KiB on Linux, bytes on macOS** — normalize so callers always
    get bytes (matching every other field).
    """
    import resource

    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw if platform.system() == "Darwin" else raw * 1024


def _isolated_child(queue: Any, action: Action, setup: Action | None, warmup: int) -> None:
    """Body of an isolated pass, run in a fresh spawned process: warm, one tracked pass, read
    ``ru_maxrss``; put the :class:`Measurement` (or the raised exception) on ``queue``.
    """
    try:
        _require_memray()
        for _ in range(max(0, warmup)):
            if setup is not None:
                setup()
            action()
        gc.collect()
        m = _track_once(action)
        queue.put(
            Measurement(m.peak_bytes, m.allocations, m.total_bytes, rss_bytes=_ru_maxrss_bytes())
        )
    except BaseException as exc:  # noqa: BLE001 — ship any failure back, don't die silently
        queue.put(exc)


#: Pickled-action size above which we warn it's shipping heavy pre-built state — a recipe over
#: lightweight inputs pickles to bytes/KiB; a partial closing over a built object is MiB+, and
#: then the isolated rss measures *deserializing* it, not building it.
_HEAVY_PICKLE_WARN_BYTES = 1024 * 1024


def _isolated_run(action: Action, setup: Action | None, warmup: int) -> Measurement:
    """One measured pass in a **fresh** spawned process, so the heap is cold and ``ru_maxrss``
    is attributable to the action. Returns the child's :class:`Measurement` incl. ``rss_bytes``.

    The action (and ``setup``) must be picklable for ``spawn`` — a top-level callable, not a
    lambda/closure. A non-picklable target, or a child that dies (segfault/OOM), raises an
    actionable error; a heavy pickled payload warns (it'd measure deserialization, not building).
    """
    import multiprocessing
    import pickle
    import warnings

    # Pickle up front: catch a non-picklable target with an actionable error, and flag a heavy
    # payload (closing over pre-built state → rss measures deserializing it, not building).
    try:
        payload = pickle.dumps((action, setup))
    except (pickle.PicklingError, AttributeError, TypeError) as exc:
        raise RuntimeError(
            "isolate=True needs a picklable action — a top-level function that builds what it "
            "operates on from lightweight args, e.g. measure_memory(partial(build_and_write, "
            "spec, n), isolate=True). A lambda/closure can't be pickled; and closing over a "
            "pre-built object would measure *deserializing* it, not building it. Isolated rss is "
            "a whole-job (build+operate) number — the child starts empty, so the construction "
            f"must be inside the callable. Or measure in-process (isolate=False). Pickling: {exc}"
        ) from exc
    if len(payload) > _HEAVY_PICKLE_WARN_BYTES:
        warnings.warn(
            f"isolate=True action pickles to {len(payload) / 1024**2:.1f} MiB — it likely closes "
            "over heavy pre-built state, so the isolated rss measures *deserializing* that state, "
            "not building it. Build from lightweight inputs inside the callable (see the docs).",
            stacklevel=2,
        )

    ctx = multiprocessing.get_context("spawn")
    queue = ctx.SimpleQueue()
    proc = ctx.Process(target=_isolated_child, args=(queue, action, setup, warmup))
    proc.start()
    proc.join()
    if queue.empty():  # nothing was put → the child died before returning a result
        raise RuntimeError(
            f"isolated memory pass died before reporting (exit code {proc.exitcode}) — the "
            "action likely segfaulted or was OOM-killed in its child process."
        )
    payload = queue.get()
    if isinstance(payload, BaseException):
        raise payload
    assert isinstance(payload, Measurement)  # the child puts a Measurement or an exception
    return payload


def measure_peak(action: Action, repeats: int | None = None) -> int:
    """Run ``action()`` under ``memray.Tracker`` and return peak **bytes**.

    The bare one-liner for a REPL or notebook; :func:`measure_memory` returns the
    full result (allocation count, spread). ``repeats`` behaves as there — ``None``
    (default) samples adaptively, an int forces a fixed pass count.

    Args:
        action: The zero-argument callable to measure.
        repeats: Fixed pass count, or ``None`` to sample adaptively.

    Returns:
        Peak bytes (the headline ``peak`` = min across passes, after warmup).
    """
    return measure_memory(action, repeats=repeats).peak_bytes
