"""The reading spine — normalize pytest-benchmark JSON into a tidy frame for plots.

pytest-benchmem defines no on-disk format of its own. The source of truth is the JSON
pytest-benchmark writes under ``.benchmarks/<machine>/NNNN_*.json``; a single
file carries *both* metrics for each benchmark id:

- ``stats`` — timing (min/mean/median/…), in seconds.
- ``extra_info.benchmem`` — the memory blob written by the ``benchmark_memory``
  fixture: ``{peak_bytes, peak_bytes_max, allocations, repeats}``, in **bytes**
  (the raw memray unit; the display layer auto-scales).

So reads are *per metric*: :func:`from_pytest_benchmark` pulls timing,
:func:`memory_from_pytest_benchmark` pulls memory, each yielding a list of
:class:`Sample` — an opaque ``id``, a ``value``, and analysis ``dims``. Dims come
from the benchmark's ``params`` (``@pytest.mark.parametrize``) plus any scalar
``extra_info`` you set in the test. :func:`load_long_df` stacks several files
(e.g. one per version from a sweep) into the single frame every plot pivots.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

#: A value of a dim axis — categorical (str) or numeric (int/float).
DimValue = str | int | float

#: Which metric to read out of a pytest-benchmark file.
Metric = Literal["time", "memory"]

#: Default key under which ``benchmark_memory`` stores the peak (MiB).
PEAK_KEY = "peak_mib"

if TYPE_CHECKING:
    import pandas as pd


class Sample(NamedTuple):
    """One measured result: an opaque ``id``, a ``value``, and analysis ``dims``."""

    id: str
    value: float
    dims: Mapping[str, DimValue]


def _read_benchmarks(path: str | Path) -> tuple[Path, list[dict[str, Any]]]:
    """Read a pytest-benchmark file, returning ``(path, benchmarks)`` or raising."""
    p = Path(path)
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: not a readable JSON file ({exc})") from exc
    if "benchmarks" not in data:
        raise ValueError(f"{path}: not a pytest-benchmark file (no 'benchmarks' key)")
    return p, data["benchmarks"]


def _dims(bm: Mapping[str, Any]) -> dict[str, DimValue]:
    """Analysis dims for one benchmark — its parametrize ``params`` plus any
    scalar ``extra_info`` (minus the reserved ``peak_mib``). No id parsing.
    """
    dims: dict[str, DimValue] = {}
    params = bm.get("params")
    if isinstance(params, Mapping):
        dims.update(params)
    extra = bm.get("extra_info")
    if isinstance(extra, Mapping):
        dims.update({k: v for k, v in extra.items() if k != PEAK_KEY})
    return dims


def from_pytest_benchmark(
    path: str | Path, *, metric: str = "min"
) -> tuple[str, list[Sample], str]:
    """Read timing out of a pytest-benchmark file → ``(label, samples, "s")``.

    ``metric`` picks the stat (``min`` / ``median`` / …). Dims come from each
    benchmark's parametrize ``params`` and ``extra_info``.
    """
    p, benchmarks = _read_benchmarks(path)
    samples = [
        Sample(id=bm["fullname"], value=bm["stats"][metric], dims=_dims(bm)) for bm in benchmarks
    ]
    return p.stem, samples, "s"


def memory_from_pytest_benchmark(
    path: str | Path, *, key: str = PEAK_KEY
) -> tuple[str, list[Sample], str]:
    """Read peak memory out of a pytest-benchmark file → ``(label, samples, "MiB")``.

    The ``benchmark_memory`` fixture stores each run's peak under
    ``extra_info[key]``, keyed by the same benchmark id pytest-benchmark uses.
    Benchmarks lacking the key (timing-only tests) are skipped. Dims come from
    parametrize ``params`` and ``extra_info``.
    """
    p, benchmarks = _read_benchmarks(path)
    samples = [
        Sample(id=bm["fullname"], value=float(bm["extra_info"][key]), dims=_dims(bm))
        for bm in benchmarks
        if isinstance(bm.get("extra_info"), Mapping) and bm["extra_info"].get(key) is not None
    ]
    return p.stem, samples, "MiB"


def load_samples(
    path: str | Path, *, metric: Metric = "time", stat: str = "min"
) -> tuple[str, list[Sample], str]:
    """Read one pytest-benchmark file for the chosen ``metric`` → ``(label, samples, unit)``."""
    if metric == "time":
        return from_pytest_benchmark(path, metric=stat)
    if metric == "memory":
        return memory_from_pytest_benchmark(path)
    raise ValueError(f"metric must be 'time' or 'memory', got {metric!r}")


def discover_runs(root: str | Path = ".benchmarks") -> list[Path]:
    """Return pytest-benchmark JSON files under ``root`` (for CLI suggestions)."""
    base = Path(root)
    return sorted(base.rglob("*.json")) if base.exists() else []


def load_long_df(
    runs: Sequence[str | Path], *, metric: Metric = "time", stat: str = "min"
) -> tuple[pd.DataFrame, str]:
    """Stack pytest-benchmark files into one long frame → ``(df, unit)``.

    One row per ``(run, id)`` for the chosen ``metric``. Columns: ``snapshot``
    (the file stem / version label), ``id``, ``value``, then one column per dim
    key seen (missing dims are ``NaN``). Every plot view pivots this frame.
    """
    import pandas as pd

    rows: list[dict[str, object]] = []
    unit = ""
    for path in runs:
        label, samples, unit = load_samples(path, metric=metric, stat=stat)
        for s in samples:
            rows.append({"snapshot": label, "id": s.id, "value": s.value, **s.dims})
    return pd.DataFrame(rows), unit
