"""Peak-memory measurement via ``memray`` — the core pytest-benchmem engine.

:func:`measure_peak` runs one action under a ``memray.Tracker`` and returns the
peak in MiB. It's what the ``benchmark_memory`` pytest fixture calls for its
memory pass, and it doubles as a standalone one-liner for a REPL or notebook::

    from pytest_benchmem import measure_peak

    peak = measure_peak(lambda: build_model(1000))   # MiB

Why memray and not RSS sampling: peak RSS (what ASV's ``peakmem`` and naive
samplers use) misses the numpy/C-allocation detail that's usually the point of
profiling a numeric library. memray tracks the allocator directly.
"""

from __future__ import annotations

import gc
import platform
import tempfile
from collections.abc import Callable
from pathlib import Path

#: A zero-arg callable doing the work that gets memory-tracked.
Action = Callable[[], object]


def _require_memray() -> None:
    """Raise if memory measurement isn't supported — memray runs only on Linux/macOS."""
    if platform.system() not in ("Linux", "Darwin"):
        raise RuntimeError(
            "memory measurement requires memray, which supports only Linux and macOS "
            f"(this is {platform.system()}). Timing still works; run memory benchmarks "
            "on Linux or macOS."
        )


def measure_peak(action: Action, repeats: int = 1) -> float:
    """Run ``action()`` under ``memray.Tracker`` and return peak MiB.

    ``repeats > 1`` runs it that many times in fresh trackers and returns the
    *minimum* peak — peak memory is noisier than expected (GC timing, lazy
    imports, page cache), so min-of-N is the cleanest "floor this can hit".
    """
    _require_memray()

    import memray

    peaks: list[float] = []
    for _ in range(max(1, repeats)):
        with tempfile.TemporaryDirectory(prefix="pytest-benchmem-") as tmp:
            out = Path(tmp) / "track.bin"  # memray must create the file itself
            with memray.Tracker(out):
                action()
            peak_bytes = memray.FileReader(out).metadata.peak_memory
            peaks.append(round(peak_bytes / (1024**2), 3))
        gc.collect()

    return min(peaks)
