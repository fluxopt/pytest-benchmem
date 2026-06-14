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

    def as_dict(self) -> dict[str, Any]:
        """The JSON blob stored under pytest-benchmark ``extra_info["benchmem"]``."""
        return {
            "peak_bytes": self.peak_bytes,
            "peak_bytes_max": self.peak_bytes_max,
            "allocations": self.allocations,
            "total_bytes": self.total_bytes,
            "repeats": self.repeats,
        }


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


def measure_memory(action: Action, repeats: int = 1) -> MemoryResult:
    """Run ``action()`` under ``memray.Tracker`` ``repeats`` times → :class:`MemoryResult`.

    Each repeat gets a fresh tracker; the representative peak is the minimum across
    repeats (see :class:`MemoryResult`), with the allocation count and total bytes
    taken from that same min-peak run.
    """
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
    )


def measure_peak(action: Action, repeats: int = 1) -> int:
    """Run ``action()`` under ``memray.Tracker`` and return peak **bytes**.

    The bare one-liner for a REPL or notebook; :func:`measure_memory` returns the
    full result (allocation count, spread).
    """
    return measure_memory(action, repeats=repeats).peak_bytes
