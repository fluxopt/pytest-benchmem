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
    stores (the ``series``). Unlike pytest-benchmark, which keeps a denormalized summary
    and gates the raw rounds behind ``--benchmark-save-data`` *because they number in the
    thousands*, our series is a handful of (expensive) memray passes, so storing it whole
    and deriving on read is both lossless and free.

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


def headline(blob: Mapping[str, Any]) -> dict[str, int]:
    """The denormalized headline scalars derived from a blob, for the display tables.

    Re-derives what the blob no longer stores: ``peak_bytes`` (the min/floor),
    ``peak_bytes_max`` (the worst peak, for the spread column), and the representative
    (min-peak run's) ``allocations`` / ``total_bytes``.
    """
    r = MemoryResult.from_blob(blob)
    return {
        "peak_bytes": r.peak_bytes,
        "peak_bytes_max": r.peak_bytes_max,
        "allocations": r.allocations,
        "total_bytes": r.total_bytes,
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


def _track_once(action: Action) -> Measurement:
    """One fresh tracker run → a :class:`Measurement` via memray stats."""
    import memray

    compute_statistics = _compute_statistics()
    with tempfile.TemporaryDirectory(prefix="pytest-benchmem-") as tmp:
        out = Path(tmp) / "track.bin"  # memray must create the file itself
        with memray.Tracker(out):
            action()
        s = compute_statistics(str(out))
        return Measurement(
            peak_bytes=int(s.peak_memory_allocated),
            allocations=int(s.total_num_allocations),
            total_bytes=int(s.total_memory_allocated),
        )


def measure_memory(action: Action, repeats: int = 1) -> MemoryResult:
    """Run ``action()`` under ``memray.Tracker`` ``repeats`` times → :class:`MemoryResult`.

    Each repeat gets a fresh tracker; the headline peak is the minimum across repeats
    (see :class:`MemoryResult`), and every repeat's :class:`Measurement` is retained for
    distribution stats.
    """
    _require_memray()

    samples = []
    for _ in range(max(1, repeats)):
        samples.append(_track_once(action))
        gc.collect()
    return MemoryResult(tuple(samples))


def measure_peak(action: Action, repeats: int = 1) -> int:
    """Run ``action()`` under ``memray.Tracker`` and return peak **bytes**.

    The bare one-liner for a REPL or notebook; :func:`measure_memory` returns the
    full result (allocation count, spread).
    """
    return measure_memory(action, repeats=repeats).peak_bytes
