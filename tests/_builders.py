"""Builders for the synthetic pytest-benchmark JSON the tests feed to readers.

Almost every test needs the same three shapes, so they live here once:

- :func:`blob` — a ``benchmem`` memory blob (a flat per-repeat series per field).
- :func:`bm` — one benchmark entry: timing ``stats`` plus an optional memory blob
  and ``params``, matching what ``benchmem compare``/``plot`` read back.
- :func:`write_run` — a whole run file (``{"benchmarks": [...]}``) written to a path.

Scenario-specific builders (a run folded along a dim, a mixed-axes sweep, …) stay
local to the test module that needs them; only these primitives are shared.
"""

from __future__ import annotations

import json
from pathlib import Path

_STATS = ("min", "max", "mean", "median", "stddev")


def _series(value, length):
    """A per-repeat series: an explicit list kept as-is, or a scalar repeated ``length`` times."""
    if isinstance(value, (list, tuple)):
        return [int(v) for v in value]
    return [int(value)] * length


def blob(peak, *, allocations=0, total_bytes=0, rss=None):
    """A ``benchmem`` blob — the flat per-repeat series recorded under ``extra_info``.

    ``peak`` sets the series length: pass a list for an explicit per-pass series, or a
    scalar for a single pass. The other fields accept the same (scalar broadcast to the
    peak length, or an explicit list). ``rss`` is included only when given — its absence
    marks an in-process (non-isolated) run.
    """
    peaks = _series(peak, 1)
    n = len(peaks)
    out = {
        "peak_bytes": peaks,
        "allocations": _series(allocations, n),
        "total_bytes": _series(total_bytes, n),
    }
    if rss is not None:
        out["rss_bytes"] = _series(rss, n)
    return out


def bm(name, *, t=0.0, peak=None, allocations=0, total_bytes=0, rss=None, params=None):
    """One benchmark entry: the full timing-stat spread, plus a memory blob when ``peak`` is set.

    Every timing stat is set to ``t`` (readers pick the one they need). A memory blob is
    attached only when ``peak`` is given; ``params`` become the pytest-benchmark param axis.
    """
    entry = {"fullname": name, "stats": {s: t for s in _STATS}}
    if peak is not None:
        entry["extra_info"] = {
            "benchmem": blob(peak, allocations=allocations, total_bytes=total_bytes, rss=rss)
        }
    if params is not None:
        entry["params"] = params
    return entry


def write_run(path, benchmarks):
    """Write a pytest-benchmark run file (``{"benchmarks": [...]}``) and return its path."""
    path = Path(path)
    path.write_text(json.dumps({"benchmarks": benchmarks}))
    return path
