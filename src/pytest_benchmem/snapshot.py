"""The reading spine — normalize pytest-benchmark JSON into a tidy frame for plots.

pytest-benchmem defines no on-disk format of its own. The source of truth is the JSON
pytest-benchmark writes under ``.benchmarks/<machine>/NNNN_*.json``; a single
file carries *both* metrics for each benchmark id:

- ``stats`` — timing (min/mean/median/…), in seconds.
- ``extra_info.benchmem`` — the memory blob written by the ``benchmark_memory``
  fixture: ``{peak_bytes, peak_bytes_max, allocations, total_bytes, repeats}``;
  byte fields are in **bytes** (the raw memray unit; the display layer auto-scales).

So reads are *per metric*: :func:`from_pytest_benchmark` pulls timing,
:func:`memory_from_pytest_benchmark` pulls memory, each yielding a list of
:class:`Sample` — an opaque ``id``, a ``value``, and analysis ``dims``. Dims come
from the benchmark's ``params`` (``@pytest.mark.parametrize``) plus any scalar
``extra_info`` you set in the test. :func:`load_long_df` stacks several files
(e.g. one per version from a sweep) into the single frame every plot pivots.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

#: A value of a dim axis — categorical (str) or numeric (int/float).
DimValue = str | int | float

#: Which metric to read out of a pytest-benchmark file — the memory ones mirror
#: ``memray stats``: ``peak`` / ``peak_max`` (the min- and max-of-repeats peak),
#: ``allocated`` (total bytes allocated), ``allocations`` (count). ``memory`` is an
#: alias for ``peak``. With ``repeats > 1`` each carries a per-repeat series, so a
#: ``stat`` (see :data:`STATS`) reports its distribution.
Metric = Literal["time", "peak", "peak_max", "allocated", "allocations", "memory"]

#: User-facing metric aliases, normalized to a canonical name by :func:`_canonical_metric`.
_METRIC_ALIAS = {"memory": "peak"}

#: Memory metric → its blob field (also the ``series`` key for the stat-able ones).
_METRIC_FIELD = {
    "peak": "peak_bytes",
    "peak_max": "peak_bytes_max",
    "allocated": "total_bytes",
    "allocations": "allocations",
}

#: Memory metrics whose per-repeat series a ``stat`` can reduce (``peak_max`` is itself a
#: stat of peak, and ``time`` is pytest-benchmark's). For these the metric's blob field
#: doubles as its ``series`` key — ``peak``→``peak_bytes``, etc.
_STATABLE = ("peak", "allocated", "allocations")

#: ``--stat`` choices → reducer over a per-repeat series. ``pstdev`` (population) so a
#: single repeat reads as ``0`` rather than raising.
STATS: dict[str, Callable[[list[float]], float]] = {
    "min": min,
    "max": max,
    "mean": statistics.fmean,
    "median": statistics.median,
    "stddev": statistics.pstdev,
}

#: Key under which ``benchmark_memory`` stores its memory blob in ``extra_info``.
BENCHMEM_KEY = "benchmem"

#: Prefix pytest-benchmark stamps onto a param it could not JSON-serialize (see
#: ``pytest_benchmark.utils.safe_dumps``: ``"UNSERIALIZABLE[%s]" % repr(...)``).
#: Such a value is identical across distinct objects of a type, so it's a broken
#: analysis axis — :func:`_dims` drops it rather than carry the garbage string.
#: Coupled to pytest-benchmark's internal format; ``test_dims_drops_unserializable``
#: pins it so a rename surfaces as a failure instead of silently-bad dims.
_UNSERIALIZABLE_PREFIX = "UNSERIALIZABLE["

#: Long-frame columns that are *not* analysis dims — the fixed axes. Plot views
#: exclude these when inferring dim roles.
RESERVED_COLUMNS = ("snapshot", "id", "value")

#: Namespace for structural dims derived from the pytest node id and benchmark group
#: (``node.module`` / ``node.func`` / ``node.class`` / ``node.group``). Reserved on two
#: counts: it can't collide with user params (Python identifiers, no dot) or extra_info,
#: and plot views never *auto*-pick a ``node.`` dim — but you can name one explicitly
#: (``facet="node.func"``).
NODE_DIM_PREFIX = "node."

#: Display unit per memory blob field (count fields have no unit).
_FIELD_UNIT = {"peak_bytes": "B", "peak_bytes_max": "B", "total_bytes": "B", "allocations": ""}

if TYPE_CHECKING:
    import pandas as pd


def human_bytes(n: float) -> str:
    """Auto-scale a byte count to a short IEC string: ``932 B``, ``4.1 MiB``, ``2.3 GiB``."""
    step = 1024.0
    value = float(n)
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < step or suffix == "TiB":
            return f"{value:.0f} {suffix}" if suffix == "B" else f"{value:.3g} {suffix}"
        value /= step
    return f"{value:.3g} TiB"  # unreachable; keeps type-checkers happy


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


def _is_dim_value(v: Any) -> bool:
    """A scalar usable as a dim axis — excludes pytest-benchmark's unserializable marker."""
    return isinstance(v, (str, int, float)) and not (
        isinstance(v, str) and v.startswith(_UNSERIALIZABLE_PREFIX)
    )


def _dims(bm: Mapping[str, Any]) -> dict[str, DimValue]:
    """Analysis dims for one benchmark — its parametrize ``params`` plus any
    scalar ``extra_info`` (minus the reserved ``benchmem`` blob). No id parsing.

    Only scalar values (``DimValue``) survive: non-scalars (lists/dicts, which are
    unhashable and break pandas groupby) and a param pytest-benchmark couldn't
    serialize (``"UNSERIALIZABLE[<repr>]"``) are dropped — neither is a usable
    axis. If a dropped value was the only thing distinguishing two benchmarks they
    collapse as dims, but stay distinct as samples (the ``fullname`` id still
    differs); mirror a clean scalar into ``extra_info`` to keep it as an axis.
    """
    dims: dict[str, DimValue] = {}
    for source in (bm.get("params"), bm.get("extra_info")):
        if isinstance(source, Mapping):
            dims.update({k: v for k, v in source.items() if k != BENCHMEM_KEY and _is_dim_value(v)})
    return dims


def _node_dims(bm: Mapping[str, Any]) -> dict[str, DimValue]:
    """Structural dims from the pytest node id and benchmark ``group``, namespaced
    under ``node.`` (see :data:`NODE_DIM_PREFIX`).

    Reads the *stable* node-id grammar ``module.py::Class::func[params]`` — the
    ``::`` structure only, never the ``[...]`` params payload (that's :func:`_dims`'
    job, and would be fragile). Whatever can't be determined is simply omitted
    (e.g. a doctest or a ``::``-less id yields no module/func).
    """
    out: dict[str, DimValue] = {}
    group = bm.get("group")
    if isinstance(group, str) and group:
        out[f"{NODE_DIM_PREFIX}group"] = group
    fullname = bm.get("fullname")
    if not isinstance(fullname, str) or "::" not in fullname:
        return out
    module, _, rest = fullname.partition("::")
    if module:
        out[f"{NODE_DIM_PREFIX}module"] = module
    segments = rest.split("::")  # [Class, ..., name]
    func = segments[-1].split("[", 1)[0]  # drop the params suffix
    if func:
        out[f"{NODE_DIM_PREFIX}func"] = func
    if len(segments) > 1:
        out[f"{NODE_DIM_PREFIX}class"] = segments[-2]  # innermost class qualifier
    return out


def _all_dims(bm: Mapping[str, Any]) -> dict[str, DimValue]:
    """Node dims plus param/extra_info dims; the latter win on the (improbable) clash."""
    return {**_node_dims(bm), **_dims(bm)}


def _benchmem(bm: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The memory blob for one benchmark, or ``None`` if it's timing-only."""
    extra = bm.get("extra_info")
    if isinstance(extra, Mapping):
        blob = extra.get(BENCHMEM_KEY)
        if isinstance(blob, Mapping):
            return blob
    return None


def from_pytest_benchmark(
    path: str | Path, *, metric: str = "min"
) -> tuple[str, list[Sample], str]:
    """Read timing out of a pytest-benchmark file → ``(label, samples, "s")``.

    ``metric`` picks the stat (``min`` / ``median`` / …). Dims come from each
    benchmark's parametrize ``params`` and ``extra_info``, plus the structural
    ``node.*`` dims (see :func:`_node_dims`).
    """
    p, benchmarks = _read_benchmarks(path)
    samples = [
        Sample(id=bm["fullname"], value=bm["stats"][metric], dims=_all_dims(bm))
        for bm in benchmarks
    ]
    return p.stem, samples, "s"


def _field_series(blob: Mapping[str, Any], field: str) -> list[float] | None:
    """The per-repeat series for ``field``, or ``[blob[field]]`` if only the scalar was kept."""
    series = blob.get("series")
    if isinstance(series, Mapping) and isinstance(series.get(field), Sequence):
        values = series[field]
        if values:
            return [float(v) for v in values]
    one = blob.get(field)
    return None if one is None else [float(one)]


def memory_from_pytest_benchmark(
    path: str | Path,
    *,
    field: str = "peak_bytes",
    reduce: Callable[[list[float]], float] | None = None,
) -> tuple[str, list[Sample], str]:
    """Read memory out of a pytest-benchmark file → ``(label, samples, unit)``.

    The ``benchmark_memory`` fixture stores each run's memory blob under
    ``extra_info["benchmem"]``, keyed by the same benchmark id pytest-benchmark
    uses. ``field`` picks which blob number to read (``peak_bytes`` → unit ``B``,
    ``allocations`` → count). Pass ``reduce`` to instead compute a distribution stat
    over ``field``'s per-repeat series (a blob without a stored series falls back to its
    single scalar). Benchmarks lacking the blob (timing-only tests) are skipped. Dims
    come from parametrize ``params`` and ``extra_info``, plus the structural ``node.*``
    dims (see :func:`_node_dims`).
    """
    p, benchmarks = _read_benchmarks(path)
    unit = _FIELD_UNIT.get(field, "")
    samples = []
    for bm in benchmarks:
        blob = _benchmem(bm)
        if blob is None:
            continue
        if reduce is not None:
            series = _field_series(blob, field)
            if series is None:
                continue
            value = float(reduce(series))
        elif blob.get(field) is None:
            continue
        else:
            value = float(blob[field])
        samples.append(Sample(id=bm["fullname"], value=value, dims=_all_dims(bm)))
    return p.stem, samples, unit


def _canonical_metric(metric: str) -> str:
    """Resolve a metric alias (e.g. ``memory`` → ``peak``) to its canonical name."""
    return _METRIC_ALIAS.get(metric, metric)


def load_samples(
    path: str | Path, *, metric: Metric = "time", stat: str | None = None
) -> tuple[str, list[Sample], str]:
    """Read one pytest-benchmark file for the chosen ``metric`` → ``(label, samples, unit)``.

    ``stat`` selects a distribution stat over the per-repeat series for ``peak`` /
    ``allocated`` / ``allocations`` (``min`` / ``max`` / ``mean`` / ``median`` /
    ``stddev``); ``None`` reads the headline scalar. For ``time`` it picks the
    pytest-benchmark stat (defaulting to ``min``).
    """
    metric = _canonical_metric(metric)  # type: ignore[assignment]
    if metric == "time":
        return from_pytest_benchmark(path, metric=stat or "min")
    field = _METRIC_FIELD.get(metric)
    if field is None:
        raise ValueError(f"metric must be one of time, {', '.join(_METRIC_FIELD)}; got {metric!r}")
    reduce = None
    if stat is not None:
        if metric not in _STATABLE:
            raise ValueError(
                f"--stat doesn't apply to metric {metric!r}; use one of {', '.join(_STATABLE)}"
            )
        reduce = STATS.get(stat)
        if reduce is None:
            raise ValueError(f"unknown stat {stat!r}; use one of {', '.join(STATS)}")
    return memory_from_pytest_benchmark(path, field=field, reduce=reduce)


def discover_runs(root: str | Path = ".benchmarks") -> list[Path]:
    """Return pytest-benchmark JSON files under ``root`` (for CLI suggestions)."""
    base = Path(root)
    return sorted(base.rglob("*.json")) if base.exists() else []


def _as_paths(runs: str | Path | Sequence[str | Path]) -> list[Path]:
    """Coerce one path (a bare ``str`` is one path, not characters) or a sequence into paths."""
    if isinstance(runs, (str, Path)):
        return [Path(runs)]
    return [Path(r) for r in runs]


def _default_labels(paths: list[Path]) -> list[str]:
    """Snapshot labels from file stems, disambiguated by parent dir where distinct
    files share a stem (e.g. ``v1/bench.json`` vs ``v2/bench.json`` → ``v1/bench`` /
    ``v2/bench``), so colliding stems don't silently merge into one series.
    """
    stems = [p.stem for p in paths]
    clashing = {s for s in stems if stems.count(s) > 1}
    return [f"{p.parent.name}/{p.stem}" if p.stem in clashing else p.stem for p in paths]


def load_long_df(
    runs: str | Path | Sequence[str | Path],
    *,
    metric: Metric = "time",
    stat: str | None = None,
    labels: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, str]:
    """Stack pytest-benchmark files (one path or a sequence) into one long frame → ``(df, unit)``.

    One row per ``(run, id)`` for the chosen ``metric``. Columns: ``snapshot``
    (the series/version label), ``id``, ``value``, then one column per dim key seen
    (missing dims are ``NaN``). Every plot view pivots this frame.

    ``labels`` overrides the ``snapshot`` label per run (one per path, same order),
    decoupling the display name from the filename; defaults to each file's stem.
    """
    import pandas as pd

    paths = _as_paths(runs)
    if labels is not None and len(labels) != len(paths):
        raise ValueError(f"labels has {len(labels)} entries but there are {len(paths)} snapshot(s)")
    label_list = list(labels) if labels is not None else _default_labels(paths)

    rows: list[dict[str, object]] = []
    unit = ""
    for label, path in zip(label_list, paths, strict=True):
        _stem, samples, unit = load_samples(path, metric=metric, stat=stat)
        for s in samples:
            rows.append({"snapshot": label, "id": s.id, "value": s.value, **s.dims})
    return pd.DataFrame(rows), unit
