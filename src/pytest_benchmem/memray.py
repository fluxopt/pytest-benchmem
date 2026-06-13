"""Peak-memory measurement via ``memray`` — the core pytest-benchmem engine.

:func:`measure_memory` runs one action under a ``memray.Tracker`` and returns a
:class:`MemoryResult`: the peak in **bytes** (the source unit memray reports —
storing the raw integer is lossless and lets the display layer auto-scale
B/KiB/MiB/GiB), the worst peak across repeats, and the allocation count.
:func:`measure_peak` is the bare one-liner that returns just the peak bytes::

    from pytest_benchmem import measure_peak, measure_memory

    peak = measure_peak(lambda: build_model(1000))          # int bytes
    res = measure_memory(lambda: build_model(1000), repeats=5)
    res.peak_bytes, res.allocations, res.peak_bytes_max

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
from typing import NamedTuple

#: A zero-arg callable doing the work that gets memory-tracked.
Action = Callable[[], object]


class MemoryResult(NamedTuple):
    """One memory measurement, in bytes.

    With ``repeats > 1`` the reported :attr:`peak_bytes` is the *minimum* peak —
    peak memory is noisier than expected (GC timing, lazy imports, page cache),
    so min-of-N is the cleanest "floor this can hit". :attr:`peak_bytes_max` keeps
    the worst observed peak so callers can judge the spread; with one repeat the
    two are equal. :attr:`allocations` is memray's allocation count for the
    representative (min-peak) run — near-deterministic, so a low-noise tripwire.
    """

    peak_bytes: int
    peak_bytes_max: int
    allocations: int
    repeats: int

    def as_dict(self) -> dict[str, int]:
        """The JSON blob stored under pytest-benchmark ``extra_info["benchmem"]``."""
        return {
            "peak_bytes": self.peak_bytes,
            "peak_bytes_max": self.peak_bytes_max,
            "allocations": self.allocations,
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


def _track_once(action: Action) -> tuple[int, int]:
    """Run ``action`` under one fresh tracker → ``(peak_bytes, allocations)``."""
    import memray

    with tempfile.TemporaryDirectory(prefix="pytest-benchmem-") as tmp:
        out = Path(tmp) / "track.bin"  # memray must create the file itself
        with memray.Tracker(out):
            action()
        meta = memray.FileReader(out).metadata
        return int(meta.peak_memory), int(meta.total_allocations)


def measure_memory(action: Action, repeats: int = 1) -> MemoryResult:
    """Run ``action()`` under ``memray.Tracker`` ``repeats`` times → :class:`MemoryResult`.

    Each repeat gets a fresh tracker; the representative peak is the minimum across
    repeats (see :class:`MemoryResult`), with the allocation count taken from that
    same min-peak run.
    """
    _require_memray()

    runs: list[tuple[int, int]] = []
    for _ in range(max(1, repeats)):
        runs.append(_track_once(action))
        gc.collect()

    peaks = [r[0] for r in runs]
    representative = min(runs, key=lambda r: r[0])  # (peak, allocations) at the floor
    return MemoryResult(
        peak_bytes=representative[0],
        peak_bytes_max=max(peaks),
        allocations=representative[1],
        repeats=len(runs),
    )


def measure_peak(action: Action, repeats: int = 1) -> int:
    """Run ``action()`` under ``memray.Tracker`` and return peak **bytes**.

    The bare one-liner for a REPL or notebook; :func:`measure_memory` returns the
    full result (allocation count, spread).
    """
    return measure_memory(action, repeats=repeats).peak_bytes
