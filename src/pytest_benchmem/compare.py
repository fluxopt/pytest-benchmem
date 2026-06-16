"""Text comparison of two or more pytest-benchmark runs — keyed on the benchmark id.

:func:`compare_runs` prints the comparison table, modelled on pytest-benchmark's own:
rows are one per ``(benchmark × run)``, columns are ``metric × stat`` (``--columns``
picks the metrics, default ``time,peak``; ``--stat`` picks the stat, default ``all`` for
the full min/max/mean/median/stddev spread), every cell carries a relative ``(N.NN)``
multiplier vs its column's best (best green, worst red), and ``group_by`` splits the rows
into sub-tables.

The rest is the regression gate behind ``benchmem compare --fail-on``: parse a threshold
like ``peak:10%`` / ``peak:5MiB`` / ``allocations:5%`` / ``time:5%``, find the ids whose
chosen field grew past it, and hand them back so the CLI can exit non-zero in CI —
mirroring pytest-benchmark's ``--benchmark-compare-fail=min:5%`` grammar, for memory.
"""

from __future__ import annotations

import math
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO, cast

from pytest_benchmem.format import byte_unit, fmt_bytes, fmt_count, rank_style, signed_pct
from pytest_benchmem.snapshot import (
    RESERVED_COLUMNS,
    Metric,
    _human_bytes,
    from_pytest_benchmark,
    load_long_df,
    memory_from_pytest_benchmark,
)

#: fail-on field → (reader kind, reader field/stat, display unit).
_FIELD = {
    "peak": ("memory", "peak_bytes", "B"),
    "allocated": ("memory", "total_bytes", "B"),
    "allocations": ("memory", "allocations", ""),
    "time": ("time", "min", "s"),
}

#: Absolute-threshold unit suffixes, per field family.
_BYTE_UNITS = {"": 1.0, "B": 1.0, "KiB": 1024.0, "MiB": 1024.0**2, "GiB": 1024.0**3}
_TIME_UNITS = {"": 1.0, "s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9}

#: Render width — generous so an N-run sweep table is never cropped (the terminal wraps).
_COMPARE_WIDTH = 10_000


def _fmt_value(field: str, value: float) -> str:
    """Format a value in its field's unit: ``4.1 MiB``, ``1.2e-05s``, ``40``."""
    unit = _FIELD[field][2]
    if unit == "B":
        return _human_bytes(value)
    return f"{value:.4g}{unit}"


#: Metrics selectable as table columns (each carries its own unit), in canonical order.
_COLUMN_METRICS: tuple[Metric, ...] = ("time", "peak", "allocated", "allocations")

#: Valid ``--sort`` keys for the comparison table.
_SORTS = ("name", "value", "change")

#: Distribution stats shown per metric, in canonical (pytest-benchmark) order. ``--stat``
#: picks one; ``all`` (the default) shows them all, so no single statistic is privileged.
_STATS: tuple[str, ...] = ("min", "max", "mean", "median", "stddev")

#: The default metric columns when ``--columns`` is unset — the two headline metrics
#: (speed + memory); ``allocated`` / ``allocations`` are opt-in via ``--columns``.
_DEFAULT_COLUMNS: tuple[Metric, ...] = ("time", "peak")

#: ``--group-by`` node keys → the ``node.*`` dim they read. ``fullname``/``name`` come
#: off the id and ``param:NAME`` off a param — mirroring pytest-benchmark's grammar.
_GROUP_NODE = {"func", "group", "module", "class"}


def _resolve_columns(columns: Sequence[str] | str | None) -> list[Metric]:
    """The metric columns to show: explicit ``columns``, else ``time,peak`` (the default)."""
    if columns:
        cols = columns.split(",") if isinstance(columns, str) else list(columns)
        cols = [c.strip() for c in cols]
    else:
        cols = list(_DEFAULT_COLUMNS)
    bad = [c for c in cols if c not in _COLUMN_METRICS]
    if bad:
        raise ValueError(
            f"unknown column metric(s): {', '.join(bad)}; choose from {', '.join(_COLUMN_METRICS)}"
        )
    return cast("list[Metric]", cols)


def _resolve_stats(stat: str | None) -> list[str]:
    """The stat columns per metric: ``all`` (or unset) → every stat, else just the one named."""
    if stat in (None, "all"):
        return list(_STATS)
    if stat not in _STATS:
        raise ValueError(f"unknown --stat {stat!r}; use one of {', '.join(_STATS)}, or all")
    return [stat]


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


def _load_columns(
    runs: Sequence[str | Path], metrics: Sequence[Metric], stats: Sequence[str]
) -> tuple[list[str], dict[tuple[str, str, str], float], dict[str, str], dict[str, dict[str, Any]]]:
    """Load each ``metric × stat`` column into ``(labels, values, units, dims)``.

    Columns are keyed by a ``"metric:stat"`` id; ``values`` maps ``(col_id, id, run) →
    value``, ``units`` maps ``metric → unit``. Runs keep file order (oldest → newest).
    Each stat reads pytest-benchmark's own ``stats`` for ``time`` and reduces the
    per-repeat series for the memory metrics.
    """
    paths = [Path(r) for r in runs]
    labels: list[str] = []
    values: dict[tuple[str, str, str], float] = {}
    units: dict[str, str] = {}
    dims: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        for stat in stats:
            df, unit = load_long_df(paths, metric=metric, stat=stat)
            units[metric] = unit
            if df.empty:  # metric absent from every run (e.g. memory on timing-only files)
                continue
            col_id = f"{metric}:{stat}"
            for lab in df["snapshot"]:
                if lab not in labels:
                    labels.append(lab)
            for lab, test_id, value in zip(df["snapshot"], df["id"], df["value"], strict=True):
                values[(col_id, test_id, lab)] = float(value)
            dim_cols = [c for c in df.columns if c not in RESERVED_COLUMNS]
            for idx, test_id in enumerate(df["id"]):
                dims.setdefault(test_id, {c: df[c].iloc[idx] for c in dim_cols})
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


def compare_runs(
    runs: Sequence[str | Path],
    *,
    columns: Sequence[str] | str | None = None,
    stat: str | None = None,
    group_by: str | None = "fullname",
    sort: str = "name",
    csv: Path | None = None,
    out: TextIO | None = None,
) -> None:
    """Print a per-(benchmark, run) comparison table across two or more runs.

    Mirrors pytest-benchmark's table model: rows are one per ``(benchmark × run)``,
    ``columns`` selects which metric columns appear (``time`` / ``peak`` / ``allocated``
    / ``allocations``), each cell carries the value plus a relative ``(N.NN)`` multiplier
    vs the group's best (best green, worst red), and ``group_by`` splits the rows into
    sub-tables (``fullname`` / ``name`` / ``func`` / ``group`` / ``module`` / ``class`` /
    ``param:NAME``, comma-composable). With no ``group_by`` the whole comparison is one
    table.

    Every column is a ``metric × stat`` pair. ``columns`` is a comma list of metric names
    (default ``time,peak``); ``stat`` is one of ``min`` / ``max`` / ``mean`` / ``median`` /
    ``stddev`` or ``all`` (the default), which expands each metric into its full stat
    spread — so no single statistic is privileged. A metric absent from every run is
    dropped rather than shown all dashes (so timing-only runs collapse to just ``time``).
    ``sort`` orders rows within a group: ``name``, ``value`` (largest in the last run), or
    ``change`` (biggest growth first). ``csv`` also writes the raw (unscaled) comparison.
    """
    from rich import box
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    if sort not in _SORTS:
        raise ValueError(f"unknown --sort {sort!r}; use one of {', '.join(_SORTS)}")
    metrics, stats = _resolve_columns(columns), _resolve_stats(stat)
    labels, values, units, dims = _load_columns(runs, metrics, stats)
    if len(labels) < 2:  # noqa: PLR2004 — a comparison needs two sides
        raise ValueError(
            f"compare needs at least two distinct runs; got {labels!r} "
            f"(the same file more than once?). Pass distinct files."
        )
    with_data = {col_id for col_id, _i, _lab in values}
    all_cols = [(m, s) for m in metrics for s in stats]
    cols = [(m, s) for m, s in all_cols if f"{m}:{s}" in with_data] or all_cols  # drop empties
    ids = sorted({test_id for _c, test_id, _lab in values})
    if csv is not None:
        _write_csv(values, [f"{m}:{s}" for m, s in cols], ids, labels, csv)

    groups: dict[tuple[str, ...], list[str]] = {}
    for test_id in ids:
        groups.setdefault(_group_of(test_id, dims.get(test_id, {}), group_by), []).append(test_id)

    console = Console(file=out or sys.stdout, width=_COMPARE_WIDTH)
    for key in sorted(groups):
        gids = _ordered_ids(groups[key], values, f"{cols[0][0]}:{cols[0][1]}", labels, sort)
        rows = [
            (i, lab)
            for i in gids
            for lab in labels
            if any((f"{m}:{s}", i, lab) in values for m, s in cols)
        ]
        # A bold section header names the group, so a single-id group (the common
        # --group-by fullname case) needs only the run label per row; a multi-id group
        # keeps the id alongside it. The compact box drops the blank padding rows that
        # otherwise dwarf a two-row base/head table.
        single_id = len({i for i, _lab in rows}) == 1
        console.print(Text(" ".join(p for p in key if p) if key else "comparison", style="bold"))
        table = Table(box=box.SIMPLE_HEAD, show_edge=False, padding=(0, 1))
        table.add_column("name", justify="left", no_wrap=True)

        # Each stat column is scaled and ranked on its own values: a byte unit that suits
        # its magnitude (so a tiny stddev doesn't drag min/max/mean into KiB) and a
        # best/worst — for the colour and the (N.NN) multiplier — comparing like-for-like
        # across the runs.
        cscale: dict[str, tuple[float, str, float | None, float | None]] = {}
        for metric, stat in cols:
            col_id = f"{metric}:{stat}"
            unit = units.get(metric, "")
            present = [values[(col_id, i, lab)] for i, lab in rows if (col_id, i, lab) in values]
            uname, factor = byte_unit(present) if unit == "B" and present else (unit, 1.0)
            best, worst = (min(present), max(present)) if present else (None, None)
            cscale[col_id] = (factor, unit, best, worst)
            table.add_column(f"{metric} ({uname})\n{stat}" if uname else f"{metric}\n{stat}",
                             justify="right")

        for i, lab in rows:
            cells = [Text(f"({lab})" if single_id else f"{_short(i)} ({lab})")]
            for metric, stat in cols:
                col_id = f"{metric}:{stat}"
                factor, unit, best, worst = cscale[col_id]
                if (col_id, i, lab) not in values:
                    cells.append(Text("—"))
                    continue
                v = values[(col_id, i, lab)]
                body = (
                    fmt_bytes(v, factor)
                    if unit == "B"
                    else fmt_count(v)
                    if unit == ""
                    else f"{v:.4g}"
                )
                cells.append(Text(body + _mult(v, best), style=rank_style(v, best, worst) or ""))
            table.add_row(*cells)
        console.print(table)
        console.print()  # one blank line between sub-tables


# --- regression gate (--fail-on) -------------------------------------------------


@dataclass(frozen=True)
class Threshold:
    """A parsed ``--fail-on`` rule: a ``field`` may grow by at most ``limit``."""

    field: str
    limit: float  # percent if is_pct, else absolute in the field's base unit
    is_pct: bool


@dataclass(frozen=True)
class Regression:
    """One id whose ``field`` grew past its threshold."""

    field: str
    id: str
    base: float
    head: float

    @property
    def pct(self) -> float:
        """Percent growth head-over-base (``inf`` if the baseline was zero)."""
        return (self.head - self.base) / self.base * 100 if self.base else float("inf")

    def format(self) -> str:
        """One human line: ``peak  test_x: 4.1 MiB → 5.0 MiB (+22.0%)``."""
        short = self.id.split("::")[-1]
        return (
            f"  {self.field:<12} {short}: "
            f"{_fmt_value(self.field, self.base)} → {_fmt_value(self.field, self.head)} "
            f"({signed_pct(self.pct)})"
        )


def parse_threshold(expr: str) -> Threshold:
    """Parse ``FIELD:THRESHOLD`` → :class:`Threshold` (``peak:10%``, ``peak:5MiB``)."""
    field, sep, raw = expr.partition(":")
    field, raw = field.strip().lower(), raw.strip()
    if not sep or not raw:
        raise ValueError(f"bad --fail-on {expr!r}: expected FIELD:THRESHOLD, e.g. peak:10%")
    if field not in _FIELD:
        raise ValueError(
            f"bad --fail-on {expr!r}: unknown field {field!r} (use {', '.join(_FIELD)})"
        )
    if raw.endswith("%"):
        return Threshold(field, _to_float(raw[:-1], expr), is_pct=True)
    return Threshold(field, _parse_abs(field, raw, expr), is_pct=False)


def _to_float(raw: str, expr: str) -> float:
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"bad --fail-on {expr!r}: {raw!r} is not a number") from None


def _parse_abs(field: str, raw: str, expr: str) -> float:
    """Parse an absolute threshold with an optional unit suffix → base units."""
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*([A-Za-zµ]*)", raw)
    if m is None:
        raise ValueError(f"bad --fail-on {expr!r}: {raw!r} is not a number with an optional unit")
    num, suffix = float(m.group(1)), m.group(2)
    if field == "allocations":
        if suffix:
            raise ValueError(f"bad --fail-on {expr!r}: allocations is a count, drop {suffix!r}")
        return num
    units = _BYTE_UNITS if field in ("peak", "allocated") else _TIME_UNITS
    if suffix not in units:
        known = ", ".join(k for k in units if k)
        raise ValueError(f"bad --fail-on {expr!r}: unknown unit {suffix!r} (use {known})")
    return num * units[suffix]


def _read_field(path: str | Path, field: str) -> dict[str, float]:
    """``{id: value}`` for one fail-on field out of a pytest-benchmark file."""
    metric, key, _unit = _FIELD[field]
    if metric == "time":
        _l, samples, _u = from_pytest_benchmark(path, metric=key)
    else:
        _l, samples, _u = memory_from_pytest_benchmark(path, field=key)
    return {s.id: s.value for s in samples}


def _regressions_for(
    base: dict[str, float], head: dict[str, float], th: Threshold
) -> list[Regression]:
    """Shared core: ids in both maps whose value grew past ``th`` (growth only)."""
    out: list[Regression] = []
    for test_id in sorted(base.keys() & head.keys()):
        vb, vh = base[test_id], head[test_id]
        grew = vh - vb
        if grew <= 0:
            continue
        over = (vb > 0 and grew / vb * 100 > th.limit) if th.is_pct else grew > th.limit
        if over:
            out.append(Regression(th.field, test_id, vb, vh))
    return out


def find_regressions(a: str | Path, b: str | Path, thresholds: list[Threshold]) -> list[Regression]:
    """Ids in both runs whose field grew past a threshold (only growth counts)."""
    regressions: list[Regression] = []
    for th in thresholds:
        base, head = _read_field(a, th.field), _read_field(b, th.field)
        regressions.extend(_regressions_for(base, head, th))
    return regressions


#: Memory-blob key per fail-on field — the fields ``--benchmark-memory-compare-fail`` gates on.
_BLOB_FIELD = {"peak": "peak_bytes", "allocated": "total_bytes", "allocations": "allocations"}


def memory_regressions(
    base_blobs: dict[str, dict[str, Any]],
    head_blobs: dict[str, dict[str, Any]],
    thresholds: list[Threshold],
) -> list[Regression]:
    """Regressions between two ``{id: benchmem-blob}`` maps (for the inline gate).

    Only ``peak`` / ``allocations`` are supported — timing is pytest-benchmark's
    own ``--benchmark-compare-fail``. Raises on an out-of-scope field.
    """
    from pytest_benchmem.memray import MemoryResult

    def headline(blobs: dict[str, dict[str, Any]], attr: str) -> dict[str, float]:
        # the blob is the per-repeat series; the gate reads its derived headline scalar
        return {
            i: float(getattr(MemoryResult.from_blob(b), attr))
            for i, b in blobs.items()
            if "peak_bytes" in b
        }

    regressions: list[Regression] = []
    for th in thresholds:
        if th.field not in _BLOB_FIELD:
            allowed = " or ".join(_BLOB_FIELD)
            raise ValueError(
                f"--benchmark-memory-compare-fail can't gate on {th.field!r}; use {allowed} "
                f"(timing is pytest-benchmark's own --benchmark-compare-fail)"
            )
        key = _BLOB_FIELD[th.field]
        regressions.extend(
            _regressions_for(headline(base_blobs, key), headline(head_blobs, key), th)
        )
    return regressions
