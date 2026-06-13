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

Two measurement modes (``measure_memory(..., mode=...)``):

- ``heap`` (default) — memray allocator demand, in-process. Byte-exact, Python-only;
  the right tool for "where does my allocation peak". memray's ``peak_memory`` tracks
  the allocator directly, so unlike sampled RSS it doesn't miss the numpy/C detail or
  fold in interpreter baseline.
- ``rss`` — kernel resident high-water (``ru_maxrss``) of the workload run in a forked
  child. Page-granular and includes the runtime, but it's the uniform, language-agnostic
  *capacity* number, and — being a kernel high-water, not sampled — it can't miss a spike
  the way a polling sampler (ASV ``peakmem``, psutil) does. See :func:`_measure_rss`.
"""

from __future__ import annotations

import gc
import os
import platform
import signal
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

#: A zero-arg callable doing the work that gets memory-tracked.
Action = Callable[[], object]


class MemoryResult(NamedTuple):
    """One memory measurement, in bytes — mirroring what ``memray stats`` reports.

    With ``repeats > 1`` the reported :attr:`peak_bytes` is the *minimum* peak —
    peak memory is noisier than expected (GC timing, lazy imports, page cache),
    so min-of-N is the cleanest "floor this can hit". :attr:`peak_bytes_max` keeps
    the worst observed peak so callers can judge the spread; with one repeat the
    two are equal. :attr:`allocations` and :attr:`total_bytes` (memray's *total
    allocations* and *total memory allocated*) are the representative (min-peak)
    run's churn — they catch temporaries that GC frees, which peak hides.
    """

    peak_bytes: int
    peak_bytes_max: int
    allocations: int
    total_bytes: int
    repeats: int
    #: Which metric produced this blob — ``"heap"`` (memray allocator demand) or ``"rss"``
    #: (kernel resident high-water). They are *incomparable* metrics (allocator bytes vs
    #: resident pages), so the readers refuse to co-plot them. Older blobs lacking it read
    #: as ``"heap"``. NB :attr:`peak_bytes` is the mode's headline number: the allocator
    #: peak for heap, the *net* resident peak (above baseline) for rss.
    mode: str = "heap"
    #: rss-only: the forked no-op child's resident floor (bytes), subtracted from the gross
    #: high-water to give the net :attr:`peak_bytes`. ``0`` for heap. See :func:`_measure_rss`.
    baseline_bytes: int = 0
    #: rss-only: the gross resident high-water (bytes), baseline included — the capacity
    #: number ("how much the process held"). ``0`` for heap.
    gross_bytes: int = 0

    def as_dict(self) -> dict[str, Any]:
        """The JSON blob stored under pytest-benchmark ``extra_info["benchmem"]``.

        Mode-specific: ``heap`` carries memray's churn fields (``allocations`` /
        ``total_bytes``); ``rss`` carries the baseline/net pair instead — each mode
        only writes the fields it actually measures.
        """
        common = {
            "peak_bytes": self.peak_bytes,
            "peak_bytes_max": self.peak_bytes_max,
            "repeats": self.repeats,
            "mode": self.mode,
        }
        if self.mode == "rss":
            return {
                **common,
                "baseline_bytes": self.baseline_bytes,
                "gross_bytes": self.gross_bytes,
            }
        return {**common, "allocations": self.allocations, "total_bytes": self.total_bytes}


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


def _track_once(action: Action) -> tuple[int, int, int]:
    """One fresh tracker run → ``(peak_bytes, allocations, total_bytes)`` via memray stats."""
    import memray

    compute_statistics = _compute_statistics()
    with tempfile.TemporaryDirectory(prefix="pytest-benchmem-") as tmp:
        out = Path(tmp) / "track.bin"  # memray must create the file itself
        with memray.Tracker(out):
            action()
        s = compute_statistics(str(out))
        return (
            int(s.peak_memory_allocated),
            int(s.total_num_allocations),
            int(s.total_memory_allocated),
        )


def measure_memory(action: Action, repeats: int = 1, *, mode: str = "heap") -> MemoryResult:
    """Measure ``action()`` ``repeats`` times → :class:`MemoryResult`, dispatched by ``mode``.

    - ``heap`` (default) — memray allocator demand, in-process; byte-exact, Python-only.
    - ``rss`` — kernel resident high-water of the workload run in a forked child; the
      uniform, language-agnostic capacity number (page-granular). See :func:`_measure_rss`.

    Both report the *minimum* peak across repeats (see :class:`MemoryResult`).
    """
    if mode == "heap":
        return _measure_heap(action, repeats)
    if mode == "rss":
        return _measure_rss(action, repeats)
    raise ValueError(f"unknown memory mode {mode!r}; use 'heap' or 'rss'")


def _measure_heap(action: Action, repeats: int = 1) -> MemoryResult:
    """Heap engine (memray): each repeat gets a fresh tracker; min-peak is representative."""
    _require_memray()

    runs: list[tuple[int, int, int]] = []
    for _ in range(max(1, repeats)):
        runs.append(_track_once(action))
        gc.collect()

    peaks = [r[0] for r in runs]
    rep = min(runs, key=lambda r: r[0])
    return MemoryResult(
        peak_bytes=rep[0],
        peak_bytes_max=max(peaks),
        allocations=rep[1],
        total_bytes=rep[2],
        repeats=len(runs),
        mode="heap",
    )


# --- rss engine: kernel resident high-water via a forked child --------------------


def _require_rss() -> None:
    """Raise if the rss engine can't run — it needs ``os.fork`` (POSIX: Linux/macOS)."""
    if not hasattr(os, "fork") or not hasattr(os, "wait4"):
        raise RuntimeError(
            f"the 'rss' memory mode needs os.fork/os.wait4 (POSIX: Linux/macOS); "
            f"not available on {platform.system()}. Use mode='heap', or run on Linux/macOS."
        )


def _maxrss_bytes(ru_maxrss: int) -> int:
    """Normalize ``getrusage`` ``ru_maxrss`` to bytes — Linux reports KiB, macOS bytes."""
    return ru_maxrss * 1024 if platform.system() == "Linux" else ru_maxrss


def _noop() -> None:  # the baseline workload — a child that allocates nothing
    pass


def _rss_child_gross(action: Action) -> int:
    """Run ``action`` in a forked child; return that child's peak RSS (bytes) via ``wait4``.

    ``gc.freeze()`` before the fork moves existing objects to the permanent generation
    the child's (still-enabled) collector won't scan — so the child can't COW-dirty the
    inherited heap and inflate its RSS. ``ru_maxrss`` is per-child (``wait4``), and is
    populated even if the child dies; a non-clean exit raises (the action failed).
    """
    gc.collect()
    gc.freeze()
    r_fd, w_fd = os.pipe()  # child → parent channel for a failure traceback
    pid = os.fork()
    if pid == 0:  # CHILD — GC stays on; freeze already spared the inherited heap
        os.close(r_fd)
        try:
            action()
        except BaseException:
            import contextlib
            import traceback

            with contextlib.suppress(OSError):
                os.write(w_fd, traceback.format_exc().encode("utf-8", "replace")[:8192])
            os._exit(70)  # distinct from a kernel SIGKILL
        os._exit(0)
    # PARENT
    os.close(w_fd)
    err = bytearray()
    while chunk := os.read(r_fd, 4096):
        err += chunk
    os.close(r_fd)
    _, status, ru = os.wait4(pid, 0)
    gc.unfreeze()
    if os.WIFSIGNALED(status):
        sig = os.WTERMSIG(status)
        hint = " — likely ran the machine out of memory" if sig == signal.SIGKILL else ""
        raise RuntimeError(
            f"the benchmarked action was killed by signal {sig} during rss measurement{hint}."
        )
    if os.WEXITSTATUS(status) != 0:
        detail = err.decode("utf-8", "replace").strip()
        raise RuntimeError(
            "the benchmarked action raised during rss measurement:\n" + detail
            if detail
            else f"the benchmarked action exited with status {os.WEXITSTATUS(status)}."
        )
    return _maxrss_bytes(ru.ru_maxrss)


def _noop_baseline(samples: int = 3) -> int:
    """The child's resident *floor* — a forked no-op child's peak RSS, min over a few.

    Subtracted from the workload's gross to isolate its marginal cost. Measured the same
    way as the workload (a forked child) on purpose: a forked child's RSS counts only the
    pages it touches *post-fork*, not the full inherited copy-on-write set, so the parent's
    own RSS would over-subtract. (Validated empirically; see the rss design issue.)
    """
    return min(_rss_child_gross(_noop) for _ in range(max(1, samples)))


def _measure_rss(action: Action, repeats: int = 1) -> MemoryResult:
    """RSS engine: fork per repeat, read each child's peak RSS, report the net high-water.

    The headline ``peak_bytes`` is **net** — the gross resident high-water minus the no-op
    child :func:`_noop_baseline` (the workload's marginal resident cost, the comparable
    number). The gross high-water (the capacity number, baseline included) is kept in
    ``gross_bytes``. Min across repeats; ``peak_bytes_max`` is the worst net so callers see
    the spread.
    """
    _require_rss()
    baseline = _noop_baseline()
    grosses = [_rss_child_gross(action) for _ in range(max(1, repeats))]
    gross = min(grosses)
    return MemoryResult(
        peak_bytes=max(0, gross - baseline),
        peak_bytes_max=max(0, max(grosses) - baseline),
        allocations=0,
        total_bytes=0,
        repeats=len(grosses),
        mode="rss",
        baseline_bytes=baseline,
        gross_bytes=gross,
    )


def measure_peak(action: Action, repeats: int = 1) -> int:
    """Run ``action()`` under ``memray.Tracker`` and return peak **bytes**.

    The bare one-liner for a REPL or notebook; :func:`measure_memory` returns the
    full result (allocation count, spread).
    """
    return measure_memory(action, repeats=repeats).peak_bytes
