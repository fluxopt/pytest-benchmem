"""The reading spine — normalize pytest-benchmark JSON into a tidy frame for plots.

pytest-benchmem defines no on-disk format of its own. The source of truth is the JSON
pytest-benchmark writes under ``.benchmarks/<machine>/NNNN_*.json``; a single
file carries *both* metrics for each benchmark id:

- ``stats`` — timing (min/mean/median/…), in seconds.
- ``extra_info.benchmem`` — the memory blob written by the ``benchmark_memory``
  fixture: ``{peak_bytes, peak_bytes_max, allocations, total_bytes, repeats, mode}``;
  byte fields are in **bytes** (the raw memray unit; the display layer auto-scales).
  ``mode`` names the metric that produced the blob (``heap`` today) so the readers
  never compare incomparable metrics — see :func:`load_long_df`.

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

#: Which metric to read out of a pytest-benchmark file. Memory metrics split by mode
#: (see :data:`_METRIC_MODES`): ``peak`` / ``peak_max`` (the min- and max-of-repeats
#: peak) are shared; ``allocated`` (total bytes) and ``allocations`` (count) are
#: heap-only churn; ``gross`` (resident high-water incl. baseline) is rss-only.
#: ``memory`` is an alias for ``peak``.
Metric = Literal["time", "peak", "peak_max", "allocated", "allocations", "gross", "memory"]

#: User-facing metric aliases, normalized to a canonical name by :func:`_canonical_metric`.
_METRIC_ALIAS = {"memory": "peak"}

#: Memory metric → its blob field.
_METRIC_FIELD = {
    "peak": "peak_bytes",
    "peak_max": "peak_bytes_max",
    "allocated": "total_bytes",
    "allocations": "allocations",
    "gross": "gross_bytes",
}

#: Which measurement modes carry each memory metric. ``peak``/``peak_max`` are in every
#: blob; the churn metrics are heap-only; ``gross`` is rss-only. Asking for a metric the
#: blob's mode doesn't carry is an error, not a silent skip (see the reader).
_METRIC_MODES = {
    "peak": {"heap", "rss"},
    "peak_max": {"heap", "rss"},
    "allocated": {"heap"},
    "allocations": {"heap"},
    "gross": {"rss"},
}

#: Reverse of :data:`_METRIC_FIELD` (blob fields are unique), for mode-validating a read.
_FIELD_METRIC = {field: metric for metric, field in _METRIC_FIELD.items()}

#: Key under which ``benchmark_memory`` stores its memory blob in ``extra_info``.
BENCHMEM_KEY = "benchmem"

#: Prefix pytest-benchmark stamps onto a param it could not JSON-serialize (see
#: ``pytest_benchmark.utils.safe_dumps``: ``"UNSERIALIZABLE[%s]" % repr(...)``).
#: Such a value is identical across distinct objects of a type, so it's a broken
#: analysis axis — :func:`_dims` drops it rather than carry the garbage string.
#: Coupled to pytest-benchmark's internal format; ``test_dims_drops_unserializable``
#: pins it so a rename surfaces as a failure instead of silently-bad dims.
_UNSERIALIZABLE_PREFIX = "UNSERIALIZABLE["

#: Blob field naming the metric that produced it, and its default for older blobs.
MODE_KEY = "mode"
DEFAULT_MODE = "heap"

#: Long-frame columns that are *not* analysis dims — fixed axes plus ``mode``, which
#: is provenance (which metric produced the value), not something to plot over. Plot
#: views exclude these when inferring dim roles.
RESERVED_COLUMNS = ("snapshot", "id", "value", MODE_KEY)

#: Namespace for structural dims derived from the pytest node id and benchmark group
#: (``node.module`` / ``node.func`` / ``node.class`` / ``node.group``). Reserved on two
#: counts: it can't collide with user params (Python identifiers, no dot) or extra_info,
#: and plot views never *auto*-pick a ``node.`` dim — but you can name one explicitly
#: (``facet="node.func"``).
NODE_DIM_PREFIX = "node."

#: Display unit per memory blob field (count fields have no unit).
_FIELD_UNIT = {
    "peak_bytes": "B",
    "peak_bytes_max": "B",
    "total_bytes": "B",
    "gross_bytes": "B",
    "allocations": "",
}

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


def _metrics_for(mode: str) -> list[str]:
    """Memory metrics a blob measured in ``mode`` carries (for actionable errors)."""
    return [m for m, modes in _METRIC_MODES.items() if mode in modes]


def memory_from_pytest_benchmark(
    path: str | Path, *, field: str = "peak_bytes"
) -> tuple[str, list[Sample], str]:
    """Read memory out of a pytest-benchmark file → ``(label, samples, unit)``.

    The ``benchmark_memory`` fixture stores each run's memory blob under
    ``extra_info["benchmem"]``, keyed by the same benchmark id pytest-benchmark
    uses. ``field`` picks which blob number to read (``peak_bytes`` → unit ``B``,
    ``allocations`` → count). Benchmarks lacking the blob (timing-only tests) are
    skipped. A blob measured in a ``mode`` that doesn't carry ``field`` (e.g. the
    rss-only ``gross`` on a heap run) raises, rather than silently dropping the row.
    Dims come from parametrize ``params`` and ``extra_info``, plus the structural
    ``node.*`` dims (see :func:`_node_dims`).
    """
    p, benchmarks = _read_benchmarks(path)
    unit = _FIELD_UNIT.get(field, "")
    metric = _FIELD_METRIC.get(field, field)
    valid_modes = _METRIC_MODES.get(metric, {"heap", "rss"})
    samples = []
    for bm in benchmarks:
        blob = _benchmem(bm)
        if blob is None:
            continue  # timing-only benchmark
        mode = str(blob.get(MODE_KEY, DEFAULT_MODE))
        if mode not in valid_modes:
            want = " or ".join(sorted(valid_modes))
            raise ValueError(
                f"metric {metric!r} is {'/'.join(sorted(valid_modes))}-only, but "
                f"{bm['fullname']!r} was measured in {mode!r} mode. Pick a {mode} metric "
                f"({', '.join(_metrics_for(mode))}), or re-measure in {want} mode."
            )
        if blob.get(field) is None:
            continue  # right mode but the number is absent (e.g. a pre-migration blob)
        # mode rides along as a reserved provenance dim so readers/plots can refuse to
        # mix incomparable metrics; blobs predating it (pre-rss) read as the heap default.
        dims = {**_all_dims(bm), MODE_KEY: mode}
        samples.append(Sample(id=bm["fullname"], value=float(blob[field]), dims=dims))
    return p.stem, samples, unit


def _canonical_metric(metric: str) -> str:
    """Resolve a metric alias (e.g. ``memory`` → ``peak``) to its canonical name."""
    return _METRIC_ALIAS.get(metric, metric)


def load_samples(
    path: str | Path, *, metric: Metric = "time", stat: str = "min"
) -> tuple[str, list[Sample], str]:
    """Read one pytest-benchmark file for the chosen ``metric`` → ``(label, samples, unit)``."""
    metric = _canonical_metric(metric)  # type: ignore[assignment]
    if metric == "time":
        return from_pytest_benchmark(path, metric=stat)
    field = _METRIC_FIELD.get(metric)
    if field is None:
        raise ValueError(f"metric must be one of time, {', '.join(_METRIC_FIELD)}; got {metric!r}")
    return memory_from_pytest_benchmark(path, field=field)


def discover_runs(root: str | Path = ".benchmarks") -> list[Path]:
    """Return pytest-benchmark JSON files under ``root`` (for CLI suggestions)."""
    base = Path(root)
    return sorted(base.rglob("*.json")) if base.exists() else []


def _as_paths(runs: str | Path | Sequence[str | Path]) -> list[Path]:
    """Coerce one path (a bare ``str`` is one path, not characters) or a sequence into paths."""
    if isinstance(runs, (str, Path)):
        return [Path(runs)]
    return [Path(r) for r in runs]


def load_long_df(
    runs: str | Path | Sequence[str | Path], *, metric: Metric = "time", stat: str = "min"
) -> tuple[pd.DataFrame, str]:
    """Stack pytest-benchmark files (one path or a sequence) into one long frame → ``(df, unit)``.

    One row per ``(run, id)`` for the chosen ``metric``. Columns: ``snapshot``
    (the file stem / version label), ``id``, ``value``, then one column per dim
    key seen (missing dims are ``NaN``). Every plot view pivots this frame.
    """
    import pandas as pd

    rows: list[dict[str, object]] = []
    unit = ""
    for path in _as_paths(runs):
        label, samples, unit = load_samples(path, metric=metric, stat=stat)
        for s in samples:
            rows.append({"snapshot": label, "id": s.id, "value": s.value, **s.dims})
    df = pd.DataFrame(rows)
    _guard_single_mode(df)
    return df, unit


def _guard_single_mode(df: pd.DataFrame) -> None:
    """Refuse a frame that mixes memory ``mode``s — they're incomparable metrics.

    A ``heap`` peak (allocator bytes) and an ``rss`` peak (resident pages) wear the
    same unit but mean different things; stacking them into one comparison/plot axis
    is exactly the error :data:`MODE_KEY` exists to catch.
    """
    if MODE_KEY not in df.columns:
        return
    modes = sorted(df[MODE_KEY].dropna().unique())
    if len(modes) > 1:
        raise ValueError(
            f"these runs mix memory modes {modes}, which are not comparable "
            f"(e.g. heap allocator bytes vs rss resident pages). Read one mode at a time."
        )
