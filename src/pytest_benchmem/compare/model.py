"""Shared substrate for the ``compare`` views — loading and the renderer-agnostic helpers.

Both the multiplier table (:mod:`.table`) and the diff view (:mod:`.diff`) build on this:
:func:`_load_columns` turns pytest-benchmark JSON into the ``(labels, values, units, dims)``
tuple every renderer reads, and the small helpers here (``--columns`` / ``--stat`` / ``--group-by``
parsing, row ordering, id shortening, value formatting) are format-agnostic. The regression gate
(:mod:`.gate`) reuses only the field table and unit maps.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pytest_benchmem.format import fmt_label
from pytest_benchmem.snapshot import (
    RESERVED_COLUMNS,
    STATS,
    Metric,
    _human_bytes,
    load_long_df,
)

#: fail-on field → (reader kind, reader field/stat, display unit).
_FIELD = {
    "peak": ("memory", "peak_bytes", "B"),
    "allocated": ("memory", "total_bytes", "B"),
    "allocations": ("memory", "allocations", ""),
    "rss": ("memory", "rss_bytes", "B"),
    "time": ("time", "min", "s"),
}

#: Absolute-threshold unit suffixes, per field family.
_BYTE_UNITS = {"": 1.0, "B": 1.0, "KiB": 1024.0, "MiB": 1024.0**2, "GiB": 1024.0**3}
_TIME_UNITS = {"": 1.0, "s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9}

#: Render width — generous so an N-run sweep table is never cropped (the terminal wraps).
_COMPARE_WIDTH = 10_000

#: Printed when ``rss`` was asked for but no run carries it — see :func:`compare_runs`.
_RSS_MISSING_NOTE = (
    "rss not recorded in these runs — mark the capacity benchmarks with "
    "@pytest.mark.benchmem(isolate=True) and re-run."
)


def _fmt_value(field: str, value: float) -> str:
    """Format a value in its field's unit: ``4.1 MiB``, ``1.2e-05s``, ``40``."""
    if _is_extra(field):
        return fmt_label(value)
    unit = _FIELD[field][2]
    if unit == "B":
        return _human_bytes(value)
    return f"{value:.4g}{unit}"


#: Metrics selectable as table columns (each carries its own unit), in canonical order.
_COLUMN_METRICS: tuple[Metric, ...] = ("time", "peak", "allocated", "allocations", "rss")

#: ``--columns`` prefix selecting a numeric ``extra_info`` value as a plain label column.
_EXTRA_PREFIX = "extra:"


def _is_extra(metric: str) -> bool:
    """Whether a column id names an ``extra_info`` label rather than a measured metric."""
    return metric.startswith(_EXTRA_PREFIX)


def _display_metric(metric: str) -> str:
    """The header/stem text for a column metric — ``extra:flows`` shows as ``flows``."""
    return metric[len(_EXTRA_PREFIX) :] if _is_extra(metric) else metric


def _col_id(metric: str, stat: str) -> str:
    """The value-map key for a ``metric × stat`` column; a stat-less label column is bare."""
    return f"{metric}:{stat}" if stat else metric


#: Valid ``--sort`` keys for the comparison table.
_SORTS = ("name", "value", "change")

#: Distribution stats a *memory* metric spreads into — the reducers :data:`snapshot.STATS`
#: applies to a per-repeat series, already in canonical (pytest-benchmark) order. Read off
#: that dict rather than restated, so a reducer added there can't go missing here.
_MEM_STATS: tuple[str, ...] = tuple(STATS)

#: Distribution stats a *timing* metric spreads into: the memory five plus ``iqr``, which
#: pytest-benchmark computes over its rounds and stores in the run file. Timing-only by
#: construction — see :func:`_stats_for` for why memory can't have it.
_TIME_STATS: tuple[str, ...] = ("min", "max", "mean", "median", "iqr", "stddev")

#: Every stat ``--stat`` accepts, canonical order. ``all`` (the default) expands each metric
#: into *its* stats, so no single statistic is privileged; a stat a metric doesn't support is
#: dropped from that metric rather than faked (:func:`_stats_for`).
_STATS: tuple[str, ...] = _TIME_STATS

#: Stats valid per metric. Only ``time`` is read from pytest-benchmark's own ``stats`` block;
#: every memory metric is reduced from the benchmem per-repeat series.
_METRIC_STATS: dict[str, tuple[str, ...]] = {"time": _TIME_STATS}

#: The default metric columns when ``--columns`` is unset — the two headline metrics
#: (speed + memory); ``allocated`` / ``allocations`` are opt-in via ``--columns``.
_DEFAULT_COLUMNS: tuple[Metric, ...] = ("time", "peak")

#: ``--group-by`` node keys → the ``node.*`` dim they read. ``fullname``/``name`` come
#: off the id and ``param:NAME`` off a param — mirroring pytest-benchmark's grammar.
_GROUP_NODE = {"func", "group", "module", "class"}


def _resolve_columns(columns: Sequence[str] | str | None) -> list[str]:
    """The columns to show: explicit ``columns``, else ``time,peak`` (the default).

    Metric names come from :data:`_COLUMN_METRICS`; ``extra:NAME`` selects the numeric
    ``extra_info`` value ``NAME`` as a stat-less label column (params share the same flat
    dim namespace, as with ``--pivot``).
    """
    if columns:
        cols = columns.split(",") if isinstance(columns, str) else list(columns)
        cols = [c.strip() for c in cols]
    else:
        cols = list(_DEFAULT_COLUMNS)
    bad = [c for c in cols if not _is_extra(c) and c not in _COLUMN_METRICS]
    bad += [c for c in cols if _is_extra(c) and not _display_metric(c)]
    if bad:
        raise ValueError(
            f"unknown column metric(s): {', '.join(bad)}; "
            f"choose from {', '.join(_COLUMN_METRICS)}, or extra:NAME for an extra_info label"
        )
    reserved = [c for c in cols if _is_extra(c) and _display_metric(c) in RESERVED_COLUMNS]
    if reserved:
        raise ValueError(
            f"reserved extra_info name(s): {', '.join(reserved)}; "
            f"{', '.join(RESERVED_COLUMNS)} are the long frame's own columns, not labels"
        )
    return cols


def _stats_for(metric: str, stats: Sequence[str]) -> list[str]:
    """``stats`` narrowed to those ``metric`` actually carries, order preserved.

    Only ``time`` has the full set: ``iqr`` comes from pytest-benchmark's own ``stats`` block,
    computed over its rounds. The memory metrics are reduced from the benchmem per-repeat
    series and have no quartiles — see :func:`_resolve_stats`.
    """
    valid = _METRIC_STATS.get(metric, _MEM_STATS)
    return [s for s in stats if s in valid]


def _timing_only(stats: Sequence[str]) -> list[str]:
    """The named stats that only ``time`` can supply — what a memory column must refuse."""
    return [s for s in stats if s not in _MEM_STATS]


def _resolve_stats(stat: str | None, metrics: Sequence[str]) -> list[str]:
    """The stat columns to build: ``all`` (or unset) → every stat, else the named comma list.

    ``--stat`` is a comma list like ``--columns`` and ``--group-by`` (``min,iqr,median``), in
    the order given. Each name must be one this run's ``metrics`` can supply: asking a memory
    column for a timing-only stat is an error rather than a silently missing column, because a
    caller who gets a number back reads it as a noise verdict. ``all`` instead expands *per
    metric* (:func:`_stats_for`) — it means "everything this metric has", not a fixed set — so
    it stays the no-single-statistic-privileged default without forcing that refusal on anyone.
    """
    if stat is None or stat == "all":
        return list(_STATS)
    names = [s.strip() for s in stat.split(",") if s.strip()]
    if not names:
        raise ValueError(f"empty --stat {stat!r}; use one of {', '.join(_STATS)}, or all")
    bad = [s for s in names if s not in _STATS]
    if bad:
        raise ValueError(
            f"unknown --stat {', '.join(repr(s) for s in bad)}; use {', '.join(_STATS)} "
            f"(comma-composable), or all"
        )
    mem_cols = [m for m in metrics if not _is_extra(m) and m not in _METRIC_STATS]
    if mem_cols and (timing := _timing_only(names)):
        named, verb = "/".join(mem_cols), "records" if len(mem_cols) == 1 else "record"
        raise ValueError(
            f"--stat {', '.join(timing)} is a timing statistic. "
            f"{named} {verb} one exact value per pass and there are only a handful of them, "
            f"so a quartile spread over them is arithmetic on 3-10 numbers rather than a "
            f"noise estimate — use min,max for the range. "
            f"Drop {named} from --columns, or use --stat all "
            f"(which gives each metric the stats it has)."
        )
    return list(dict.fromkeys(names))


def _group_of(test_id: str, dims: dict[str, Any], group_by: str | None) -> tuple[str, ...]:
    """The group key for an id under ``group_by`` (comma-composable, pytest-benchmark grammar)."""
    if not group_by:
        return ()
    parts: list[str] = []
    for raw in group_by.split(","):
        key = raw.strip()
        if key == "fullname":
            parts.append(test_id)
        elif key == "name":
            parts.append(test_id.split("::")[-1])
        elif key in _GROUP_NODE:
            parts.append(str(dims.get(f"node.{key}", "")))
        elif key.startswith("param:"):
            name = key[len("param:") :]
            parts.append(f"{name}={dims.get(name)}")
        else:
            allowed = "fullname, name, func, group, module, class, param:NAME"
            raise ValueError(f"unknown --group-by key {key!r}; use {allowed}")
    return tuple(parts)


def _mult(value: float, best: float | None) -> str:
    """pytest-benchmark's relative annotation: ``(1.0)`` for the best, else ``(N.NN)``×."""
    if best is None or best <= 0:
        return ""
    if value == best:
        return " (1.0)"
    scale = value / best
    if scale > 1000:  # noqa: PLR2004 — pytest-benchmark's own cap
        return " (inf)" if math.isinf(scale) else " (>1000.0)"
    return f" ({scale:.2f})"


def _short(test_id: str) -> str:
    """The trailing node-id segment — ``module.py::test_x[1]`` → ``test_x[1]``."""
    return test_id.split("::")[-1]


def _group_title(key: tuple[str, ...]) -> str:
    """The sub-table header for a group key — the joined non-empty parts, or ``comparison``
    for the ungrouped whole.
    """
    return " ".join(p for p in key if p) if key else "comparison"


def _md_escape(text: str) -> str:
    """Escape ``|`` so a value or id can't break the markdown table grid."""
    return text.replace("|", "\\|")


def _load_columns(
    runs: Sequence[str | Path],
    metrics: Sequence[Metric],
    stats: Sequence[str],
    pivot: str | None = None,
    extras: Sequence[str] = (),
) -> tuple[list[str], dict[tuple[str, str, str], float], dict[str, str], dict[str, dict[str, Any]]]:
    """Load each ``metric × stat`` column into ``(labels, values, units, dims)``.

    Columns are keyed by a ``"metric:stat"`` id; ``values`` maps ``(col_id, id, series) →
    value``, ``units`` maps ``metric → unit``. The series labels keep their natural order —
    file order (oldest → newest) for run-files, or dim-value order when ``pivot`` folds a single
    run along a dim. Each stat reads pytest-benchmark's own ``stats`` for ``time`` and reduces
    the per-repeat series for the memory metrics.

    ``extras`` names ``extra_info`` labels loaded per ``(id, series)`` under the stat-less
    ``extra:NAME`` column id — so a label that legitimately differs between runs (a model
    size after a formulation change) shows per series. Only numeric values are kept.
    """
    paths = [Path(r) for r in runs]
    labels: list[str] = []
    values: dict[tuple[str, str, str], float] = {}
    units: dict[str, str] = {}
    dims: dict[str, dict[str, Any]] = {}

    def collect(df: Any) -> None:
        """Register the series labels, dims and ``extras`` values one long df carries."""
        for lab in df["snapshot"]:
            if lab not in labels:
                labels.append(lab)
        dim_cols = [c for c in df.columns if c not in RESERVED_COLUMNS]
        for idx, test_id in enumerate(df["id"]):
            dims.setdefault(test_id, {c: df[c].iloc[idx] for c in dim_cols})
        for name in extras:
            if name not in df.columns:
                continue
            col_id = _EXTRA_PREFIX + name
            units.setdefault(col_id, "")
            for lab, test_id, v in zip(df["snapshot"], df["id"], df[name], strict=True):
                if isinstance(v, bool):
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if not math.isnan(fv):
                    values.setdefault((col_id, test_id, lab), fv)

    for metric in metrics:
        for stat in _stats_for(metric, stats):
            df, unit = load_long_df(paths, metric=metric, stat=stat, pivot=pivot)
            units[metric] = unit
            if df.empty:  # metric absent from every run (e.g. memory on timing-only files)
                continue
            col_id = _col_id(metric, stat)
            for lab, test_id, value in zip(df["snapshot"], df["id"], df["value"], strict=True):
                values[(col_id, test_id, lab)] = float(value)
            collect(df)
    # No metric df populated the frame — label-only columns, or every requested metric absent
    # (e.g. rss on non-isolated runs) — so the labels still need one pass over the runs.
    if extras and not labels:
        df, _unit = load_long_df(paths, metric="time", stat="min", pivot=pivot)
        if not df.empty:
            collect(df)
    return labels, values, units, dims


def _ordered_ids(
    ids: list[str],
    values: dict[tuple[str, str, str], float],
    col0: str,
    labels: list[str],
    sort: str,
) -> list[str]:
    """Row order within a group per ``sort``, keyed on the first column metric."""
    if sort == "name":
        return sorted(ids)
    first, last = labels[0], labels[-1]
    if sort == "value":
        return sorted(
            ids,
            key=lambda i: (
                values.get((col0, i, last)) is None,
                -(values.get((col0, i, last)) or 0.0),
            ),
        )

    def growth(test_id: str) -> float:  # sort == "change"
        a, b = values.get((col0, test_id, first)), values.get((col0, test_id, last))
        return (b - a) / a if a and b and a > 0 else float("-inf")

    return sorted(ids, key=lambda i: -growth(i))


def _write_csv(
    values: dict[tuple[str, str, str], float],
    columns: Sequence[str],
    ids: list[str],
    labels: list[str],
    path: Path,
) -> None:
    """Write the raw (unscaled) comparison: one row per id, a column per ``metric:run``."""
    import pandas as pd

    rows = [
        {"id": i, **{f"{m}:{lab}": values.get((m, i, lab)) for m in columns for lab in labels}}
        for i in ids
    ]
    pd.DataFrame(rows).set_index("id").to_csv(path)
