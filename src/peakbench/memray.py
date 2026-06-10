"""Peak-memory measurement via ``memray`` — the core peakbench engine.

:func:`measure_peak` runs one action under a ``memray.Tracker`` and returns the
peak in MiB. :func:`measure` runs a stream of :class:`~peakbench.case.Case` and
returns ``{id: peak}`` — each case's setup (build inputs) runs *outside* the
tracker, so the peak reflects only the measured action.

Why memray and not RSS sampling: peak RSS (what ASV's ``peakmem`` and naive
samplers use) misses the numpy/C-allocation detail that's usually the point of
profiling a numeric library. memray tracks the allocator directly.
"""

from __future__ import annotations

import gc
import platform
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

from peakbench.case import Action, Case
from peakbench.snapshot import Sample


def _require_memray() -> None:
    """Raise if memory measurement isn't supported (Windows has no memray)."""
    if platform.system() == "Windows":
        raise RuntimeError(
            "memory measurement requires memray, which is unavailable on Windows. "
            "Run memory benchmarks on Linux or macOS."
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
        fd, tmp = tempfile.mkstemp(suffix=".bin")
        Path(tmp).unlink()  # memray must create the file itself
        try:
            from os import close as _close

            _close(fd)
        except OSError:
            pass
        try:
            with memray.Tracker(tmp):
                action()
            peak_bytes = memray.FileReader(tmp).metadata.peak_memory
            peaks.append(round(peak_bytes / (1024**2), 3))
        finally:
            Path(tmp).unlink(missing_ok=True)
        gc.collect()

    return min(peaks)


def measure(
    cases: Iterable[Case],
    *,
    repeats: int = 1,
    on_result: Callable[[str, float], None] | None = None,
    on_error: Callable[[str, Exception], None] | None = None,
) -> list[Sample]:
    """Measure peak memory for each case and return a list of :class:`Sample`.

    Each sample carries the case's ``id``, the peak (MiB), and the case's
    ``dims``. ``on_result(id, peak)`` fires per success; ``on_error(id, exc)``
    fires for a case whose action raised (it's skipped, not fatal — surface it
    via this hook).

    ``measure`` runs every case it's handed — selection is the consumer's job,
    done *before* building cases. Keep your own rich case type (carrying whatever
    you select on — a spec object, solver availability, a size tier), filter it,
    and map only the survivors to :class:`Case`::

        cases = [
            Case(id=mk_id(c), dims=mk_dims(c), run=c.run)
            for c in my_cases
            if not c.skip and dep_available(c) and c.size in tier
        ]
        measure(cases)

    This keeps consumer state on your side of the seam and ``Case`` minimal —
    rather than a ``select=``/``meta=`` channel pushing it through the library.
    """
    _require_memray()
    samples: list[Sample] = []
    for case in cases:
        try:
            with case.run() as action:
                peak = measure_peak(action, repeats=repeats)
        except Exception as exc:  # noqa: BLE001 — one bad case shouldn't sink the run
            if on_error is not None:
                on_error(case.id, exc)
            continue
        samples.append(Sample(id=case.id, value=peak, dims=case.dims))
        if on_result is not None:
            on_result(case.id, peak)
        gc.collect()
    return samples
