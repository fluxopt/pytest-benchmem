"""Text table for one or more pytest-benchmark runs — keyed on the benchmark id.

:func:`compare_runs` prints the table, modelled on pytest-benchmark's own:
rows are one per ``(benchmark × run)``, columns are ``metric × stat`` (``--columns``
picks the metrics, default ``time,peak``; ``--stat`` picks the stat, default ``all`` for
the full min/max/mean/median/stddev spread), and ``group_by`` splits the rows into
sub-tables. With **two or more** runs every cell carries a relative ``(N.NN)`` multiplier
vs its column's best (best green, worst red); a **single** run is a plain readout — there's
no other run to rank against, so the multiplier and colour are dropped.

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

from pytest_benchmem.format import (
    byte_unit,
    fmt_bytes,
    fmt_count,
    growth,
    rank_style,
    signed_pct,
)
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
    "rss": ("memory", "rss_bytes", "B"),
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
_COLUMN_METRICS: tuple[Metric, ...] = ("time", "peak", "allocated", "allocations", "rss")

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
    runs: Sequence[str | Path],
    metrics: Sequence[Metric],
    stats: Sequence[str],
    pivot: str | None = None,
) -> tuple[list[str], dict[tuple[str, str, str], float], dict[str, str], dict[str, dict[str, Any]]]:
    """Load each ``metric × stat`` column into ``(labels, values, units, dims)``.

    Columns are keyed by a ``"metric:stat"`` id; ``values`` maps ``(col_id, id, series) →
    value``, ``units`` maps ``metric → unit``. The series labels keep their natural order —
    file order (oldest → newest) for run-files, or dim-value order when ``pivot`` folds a single
    run along a dim. Each stat reads pytest-benchmark's own ``stats`` for ``time`` and reduces
    the per-repeat series for the memory metrics.
    """
    paths = [Path(r) for r in runs]
    labels: list[str] = []
    values: dict[tuple[str, str, str], float] = {}
    units: dict[str, str] = {}
    dims: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        for stat in stats:
            df, unit = load_long_df(paths, metric=metric, stat=stat, pivot=pivot)
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


# --- the shared table model: computed once, rendered as a rich table or as markdown ----------

#: Printed when ``rss`` was asked for but no run carries it — see :func:`compare_runs`.
_RSS_MISSING_NOTE = (
    "rss not recorded in these runs — mark the capacity benchmarks with "
    "@pytest.mark.benchmem(isolate=True) and re-run."
)


@dataclass
class _Col:
    """One ``metric × stat`` column, byte-scaled to a unit suiting its magnitude with the group
    best/worst found — together they drive the ``(N.NN)`` multiplier and (in the rich view) the
    best-green/worst-red colour. ``unit`` is the base unit (``B`` / ``s`` / ``""``), ``uname`` the
    scaled unit shown in the header, ``factor`` the divisor mapping raw bytes onto it.
    """

    metric: str
    stat: str
    uname: str
    factor: float
    unit: str
    best: float | None
    worst: float | None

    @property
    def col_id(self) -> str:
        return f"{self.metric}:{self.stat}"


@dataclass
class _GroupView:
    """A computed sub-table: the header ``title``, ordered ``rows`` (``(id, series)`` pairs), the
    scaled ``cols``, and whether it holds a single id (so a row needs only its series label).
    """

    title: str
    rows: list[tuple[str, str]]
    single_id: bool
    cols: list[_Col]


def _scale_columns(
    cols: Sequence[tuple[str, str]],
    rows: Sequence[tuple[str, str]],
    values: dict[tuple[str, str, str], float],
    units: dict[str, str],
) -> list[_Col]:
    """Resolve each ``metric × stat`` column to a :class:`_Col` — a byte unit that suits its own
    magnitude (so a tiny stddev doesn't drag min/max into KiB) and the group best/worst.
    """
    scaled: list[_Col] = []
    for metric, stat in cols:
        col_id = f"{metric}:{stat}"
        unit = units.get(metric, "")
        present = [values[(col_id, i, lab)] for i, lab in rows if (col_id, i, lab) in values]
        uname, factor = byte_unit(present) if unit == "B" and present else (unit, 1.0)
        best, worst = (min(present), max(present)) if present else (None, None)
        scaled.append(_Col(metric, stat, uname, factor, unit, best, worst))
    return scaled


def _cell_body(value: float, factor: float, unit: str) -> str:
    """The unit-formatted number for a cell, without the multiplier: bytes / count / 4 sig figs."""
    if unit == "B":
        return fmt_bytes(value, factor)
    if unit == "":
        return fmt_count(value)
    return f"{value:.4g}"


def _row_label(test_id: str, series: str, single_id: bool) -> str:
    """The leftmost cell: just the series when the group has one id (its header already names it),
    else the short id alongside the series.
    """
    return f"({series})" if single_id else f"{_short(test_id)} ({series})"


def _group_title(key: tuple[str, ...]) -> str:
    """The sub-table header for a group key — the joined non-empty parts, or ``comparison``
    for the ungrouped whole.
    """
    return " ".join(p for p in key if p) if key else "comparison"


def _build_views(
    groups: dict[tuple[str, ...], list[str]],
    cols: Sequence[tuple[str, str]],
    values: dict[tuple[str, str, str], float],
    units: dict[str, str],
    labels: list[str],
    sort: str,
) -> list[_GroupView]:
    """One :class:`_GroupView` per group (sorted) — row ordering, the ``(id, series)`` rows that
    carry data, and the scaled columns. The renderer-agnostic model behind both output formats.
    """
    views: list[_GroupView] = []
    for key in sorted(groups):
        gids = _ordered_ids(groups[key], values, f"{cols[0][0]}:{cols[0][1]}", labels, sort)
        rows = [
            (i, lab)
            for i in gids
            for lab in labels
            if any((f"{m}:{s}", i, lab) in values for m, s in cols)
        ]
        single_id = len({i for i, _lab in rows}) == 1
        view = _GroupView(
            _group_title(key), rows, single_id, _scale_columns(cols, rows, values, units)
        )
        views.append(view)
    return views


def _render_rich(
    out: TextIO | None,
    views: Sequence[_GroupView],
    values: dict[tuple[str, str, str], float],
    *,
    single: bool,
    rss_missing: bool,
) -> None:
    """Print the comparison as rich tables (the terminal default): a bold group header, the
    timed│untimed divider, and best-green/worst-red colouring with the ``(N.NN)`` multiplier.
    """
    from rich import box
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    console = Console(file=out or sys.stdout, width=_COMPARE_WIDTH)
    if rss_missing:
        console.print(Text(_RSS_MISSING_NOTE, style="yellow"))
    for view in views:
        console.print(Text(view.title, style="bold"))
        table = Table(box=box.SIMPLE_HEAD, show_edge=False, padding=(0, 1))
        table.add_column("name", justify="left", no_wrap=True)
        prev_metric: str | None = None
        for c in view.cols:
            if prev_metric is not None and (c.metric == "time") != (prev_metric == "time"):
                table.add_column("│", justify="center", style="dim")  # timed | untimed boundary
            prev_metric = c.metric
            head = f"{c.metric} ({c.uname})\n{c.stat}" if c.uname else f"{c.metric}\n{c.stat}"
            table.add_column(head, justify="right")
        for i, lab in view.rows:
            cells = [Text(_row_label(i, lab, view.single_id))]
            prev_metric = None
            for c in view.cols:
                if prev_metric is not None and (c.metric == "time") != (prev_metric == "time"):
                    cells.append(Text("│", style="dim"))
                prev_metric = c.metric
                if (c.col_id, i, lab) not in values:
                    cells.append(Text("—"))
                    continue
                v = values[(c.col_id, i, lab)]
                text = _cell_body(v, c.factor, c.unit) + ("" if single else _mult(v, c.best))
                style = "" if single else (rank_style(v, c.best, c.worst) or "")
                cells.append(Text(text, style=style))
            table.add_row(*cells)
        console.print(table)
        console.print()  # one blank line between sub-tables


def _md_escape(text: str) -> str:
    """Escape ``|`` so a value or id can't break the markdown table grid."""
    return text.replace("|", "\\|")


def _render_markdown(
    out: TextIO | None,
    views: Sequence[_GroupView],
    values: dict[tuple[str, str, str], float],
    *,
    single: bool,
    rss_missing: bool,
) -> None:
    """Write the comparison as GitHub-flavored markdown — one ``####`` section per group with a
    native table. The ``(N.NN)`` multiplier carries best (``1.0``) and magnitude; there is no
    colour (GFM strips inline styles) and no timed│untimed divider (it isn't a real column).
    """
    lines: list[str] = []
    if rss_missing:
        lines += [f"> {_RSS_MISSING_NOTE}", ""]
    for view in views:
        headers = ["name"] + [
            f"{c.metric} ({c.uname}) {c.stat}" if c.uname else f"{c.metric} {c.stat}"
            for c in view.cols
        ]
        lines += [
            f"#### {view.title}",
            "",
            "| " + " | ".join(_md_escape(h) for h in headers) + " |",
            "| " + " | ".join([":---", *["---:"] * len(view.cols)]) + " |",
        ]
        for i, lab in view.rows:
            cells = [_row_label(i, lab, view.single_id)]
            for c in view.cols:
                if (c.col_id, i, lab) not in values:
                    cells.append("—")
                    continue
                v = values[(c.col_id, i, lab)]
                cells.append(_cell_body(v, c.factor, c.unit) + ("" if single else _mult(v, c.best)))
            lines.append("| " + " | ".join(_md_escape(x) for x in cells) + " |")
        lines.append("")
    (out or sys.stdout).write("\n".join(lines).rstrip() + "\n")


# --- the diff view: metrics on the row axis, one Δ column per run ------------------------------
#
# A benchmark id becomes one row *per metric*; the columns stay flat — a baseline value, then a
# signed Δ% per later run vs that baseline — no matter how many metrics are shown. The first series
# is the baseline (matching the --fail-on gate, which measures the last run against the first). A
# two-run diff is just `<metric> base | <run>`; a sweep adds one Δ column per further run. The
# per-run *absolute* value is dropped as redundant — it is recoverable as base × (1 + Δ).


@dataclass
class _DiffView:
    """A diff sub-table: the group ``title`` and its ordered ``ids``. Each id renders one row per
    metric column, so the table is *tall* (flat in metric count) rather than wide.
    """

    title: str
    ids: list[str]


@dataclass
class _DiffCell:
    """One rendered diff cell: its ``text`` (unit-formatted value or signed Δ%, or ``—``), the
    ``rank`` colour for a Δ cell (``green`` shrink / ``red`` growth / ``None``), and the numeric
    ``sort`` key the HTML view puts in ``data-v`` (raw value for a baseline cell, percent for a Δ).
    """

    text: str
    rank: str | None
    sort: float | None


@dataclass
class _DiffMetricRow:
    """One metric's row for an id: its ``stem`` (the metric label), the ``base`` baseline value
    cell, and one ``deltas`` cell per comparison run.
    """

    stem: str
    base: _DiffCell
    deltas: list[_DiffCell]


def _diff_stem(metric: str, stat: str, *, one_stat: bool) -> str:
    """The metric label for a diff row — just the metric when a single stat is shown (the common
    case), else ``metric stat`` so a multi-stat diff stays unambiguous.
    """
    return metric if one_stat else f"{metric} {stat}"


def _diff_headers(
    cols: Sequence[tuple[str, str]], comps: Sequence[str], *, one_stat: bool
) -> list[str]:
    """The column headers after ``name``. With more than one metric a ``metric`` column carries the
    per-row metric label and the baseline column is a plain ``base``; with a single metric that
    column is dropped and the metric folds into the baseline header (``peak base``). Every
    comparison run then contributes one column headed by its run label (its cells are Δ%).
    """
    multi = len(cols) > 1
    lead = ["metric", "base"] if multi else [f"{_diff_stem(*cols[0], one_stat=one_stat)} base"]
    return [*lead, *comps]


def _diff_value_cell(metric: str, value: float | None) -> _DiffCell:
    """A baseline value cell — unit-formatted, sorted on the raw value, never coloured."""
    return _DiffCell("—" if value is None else _fmt_value(metric, value), None, value)


def _diff_delta_cell(baseline: float | None, value: float | None) -> _DiffCell:
    """A Δ cell — signed percent vs the baseline, coloured by direction, sorted on the percent."""
    if baseline is None or value is None:
        return _DiffCell("—", None, None)
    text, rank = growth(baseline, value)
    pct = (value - baseline) / baseline * 100 if baseline > 0 else None
    return _DiffCell(text, rank, pct)


def _diff_metric_rows(
    i: str,
    cols: Sequence[tuple[str, str]],
    values: dict[tuple[str, str, str], float],
    labels: Sequence[str],
    *,
    one_stat: bool,
) -> list[_DiffMetricRow]:
    """The per-metric rows for one id: each metric's baseline value plus a Δ vs the baseline for
    every comparison run. The shared body behind all three diff renderers.
    """
    base_lab, comps = labels[0], labels[1:]
    rows: list[_DiffMetricRow] = []
    for metric, stat in cols:
        col_id = f"{metric}:{stat}"
        baseline = values.get((col_id, i, base_lab))
        deltas = [_diff_delta_cell(baseline, values.get((col_id, i, comp))) for comp in comps]
        rows.append(
            _DiffMetricRow(
                _diff_stem(metric, stat, one_stat=one_stat),
                _diff_value_cell(metric, baseline),
                deltas,
            )
        )
    return rows


def _build_diff_views(
    groups: dict[tuple[str, ...], list[str]],
    cols: Sequence[tuple[str, str]],
    values: dict[tuple[str, str, str], float],
    labels: Sequence[str],
    sort: str,
) -> list[_DiffView]:
    """One :class:`_DiffView` per group (sorted): the ids that carry data for any series, ordered
    by ``sort`` (``change`` puts the biggest last-vs-first growth first).
    """
    views: list[_DiffView] = []
    for key in sorted(groups):
        gids = _ordered_ids(groups[key], values, f"{cols[0][0]}:{cols[0][1]}", list(labels), sort)
        ids = [
            i
            for i in gids
            if any((f"{m}:{s}", i, lab) in values for m, s in cols for lab in labels)
        ]
        if ids:
            views.append(_DiffView(_group_title(key), ids))
    return views


def _render_rich_diff(
    out: TextIO | None,
    views: Sequence[_DiffView],
    cols: Sequence[tuple[str, str]],
    values: dict[tuple[str, str, str], float],
    labels: Sequence[str],
    *,
    one_stat: bool,
    rss_missing: bool,
) -> None:
    """Print the diff as rich tables: one row per id × metric, a baseline value then a
    red-on-growth, green-on-shrink Δ per comparison run. The id is shown once per benchmark (blank
    on its extra metric rows) so the eye groups them.
    """
    from rich import box
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    console = Console(file=out or sys.stdout, width=_COMPARE_WIDTH)
    if rss_missing:
        console.print(Text(_RSS_MISSING_NOTE, style="yellow"))
    multi = len(cols) > 1
    headers = _diff_headers(cols, labels[1:], one_stat=one_stat)
    for view in views:
        console.print(Text(view.title, style="bold"))
        table = Table(box=box.SIMPLE_HEAD, show_edge=False, padding=(0, 1))
        table.add_column("name", justify="left", no_wrap=True)
        for idx, head in enumerate(headers):
            metric_col = multi and idx == 0
            table.add_column(head, justify="left" if metric_col else "right")
        for i in view.ids:
            for row_idx, mrow in enumerate(
                _diff_metric_rows(i, cols, values, labels, one_stat=one_stat)
            ):
                cells = [Text(_short(i) if row_idx == 0 else "")]
                if multi:
                    cells.append(Text(mrow.stem))
                cells.append(Text(mrow.base.text))
                cells += [Text(d.text, style=d.rank or "") for d in mrow.deltas]
                table.add_row(*cells)
        console.print(table)
        console.print()


def _render_markdown_diff(
    out: TextIO | None,
    views: Sequence[_DiffView],
    cols: Sequence[tuple[str, str]],
    values: dict[tuple[str, str, str], float],
    labels: Sequence[str],
    *,
    one_stat: bool,
    rss_missing: bool,
) -> None:
    """Write the diff as GitHub-flavored markdown — one ``####`` section per group, a metric per row
    with a baseline and one Δ column per comparison run. The signed ``Δ%`` carries direction; there
    is no colour (GFM strips it).
    """
    multi = len(cols) > 1
    after = _diff_headers(cols, labels[1:], one_stat=one_stat)
    aligns = [":---", *[":---" if (multi and idx == 0) else "---:" for idx in range(len(after))]]
    lines: list[str] = []
    if rss_missing:
        lines += [f"> {_RSS_MISSING_NOTE}", ""]
    for view in views:
        lines += [
            f"#### {view.title}",
            "",
            "| " + " | ".join(_md_escape(h) for h in ["name", *after]) + " |",
            "| " + " | ".join(aligns) + " |",
        ]
        for i in view.ids:
            for row_idx, mrow in enumerate(
                _diff_metric_rows(i, cols, values, labels, one_stat=one_stat)
            ):
                cells = [_short(i) if row_idx == 0 else ""]
                if multi:
                    cells.append(mrow.stem)
                cells.append(mrow.base.text)
                cells += [d.text for d in mrow.deltas]
                lines.append("| " + " | ".join(_md_escape(x) for x in cells) + " |")
        lines.append("")
    (out or sys.stdout).write("\n".join(lines).rstrip() + "\n")


def compare_runs(
    runs: Sequence[str | Path],
    *,
    columns: Sequence[str] | str | None = None,
    stat: str | None = None,
    group_by: str | None = "fullname",
    sort: str = "name",
    pivot: str | None = None,
    out_format: str = "table",
    diff: bool = False,
    csv: Path | None = None,
    out: TextIO | None = None,
) -> None:
    """Print a per-(benchmark, series) table for one or more runs.

    Mirrors pytest-benchmark's table model: rows are one per ``(benchmark × series)``, where
    the **series axis** is the run-file by default (one column-group per run). With two or more
    series each cell carries a relative ``(N.NN)`` multiplier vs the group's best (best green,
    worst red); a single series is a plain readout with neither. ``columns`` selects which metric
    columns appear (``time`` / ``peak`` / ``allocated`` / ``allocations``). ``group_by`` splits
    the rows into sub-tables (``fullname`` / ``name`` / ``func`` / ``group`` / ``module`` /
    ``class`` / ``param:NAME``, comma-composable); with no ``group_by`` the whole comparison is
    one table.

    ``pivot`` re-points the series axis from the run-file onto a data dim (``param:NAME`` or a
    bare ``extra_info`` name), folding a *single* combined run along that dim: rows that differ
    only in it pair up and its values become the compared series — the A/B a run-file pair gives
    you today, without splitting the data into N files. Distinct from ``group_by`` (which only
    clusters rows into sub-tables, leaving the run-files as the compared series): ``pivot`` sets
    *what* is compared, ``group_by`` sets how rows cluster. It composes with ``columns`` /
    ``stat`` / ``sort`` / ``group_by`` unchanged and is mutually exclusive with multiple runs
    (one series axis per table).

    Every column is a ``metric × stat`` pair. ``columns`` is a comma list of metric names
    (default ``time,peak``); ``stat`` is one of ``min`` / ``max`` / ``mean`` / ``median`` /
    ``stddev`` or ``all`` (the default), which expands each metric into its full stat
    spread — so no single statistic is privileged. A metric absent from every run is
    dropped rather than shown all dashes (so timing-only runs collapse to just ``time``).
    ``sort`` orders rows within a group: ``name``, ``value`` (largest in the last series), or
    ``change`` (biggest growth first). ``out_format`` picks the rendering — ``table`` (the rich
    terminal default) or ``md`` (GitHub-flavored markdown to ``out``, for a PR comment or
    ``$GITHUB_STEP_SUMMARY``); both render the same model. ``csv`` also writes the raw (unscaled)
    comparison to a file.

    ``diff`` switches to the collapsed baseline view: metrics move onto the *row* axis (one row per
    benchmark × metric), and the columns stay flat — the first run's value, then one signed ``Δ%``
    per later run vs that baseline (coloured by direction, red on growth, green on shrink). The
    per-run absolute value is dropped as redundant (recoverable as ``base × (1 + Δ)``), so the table
    is tall rather than wide no matter how many runs or metrics. Δ is always measured against the
    first run (matching the ``--fail-on`` gate); a single metric drops the metric column. It needs
    at least two series — two or more runs, or one run folded with ``pivot`` over a multi-value
    dim — and defaults ``stat`` to ``min`` (pass ``--stat`` to override). Both ``table`` and ``md``
    render it.
    """
    if sort not in _SORTS:
        raise ValueError(f"unknown --sort {sort!r}; use one of {', '.join(_SORTS)}")
    if out_format not in ("table", "md"):
        raise ValueError(f"unknown --format {out_format!r}; use table or md")
    # The diff view is a base→head readout, so a full stat spread would triple every column; when
    # the user hasn't asked for a specific stat, show just the headline min.
    metrics = _resolve_columns(columns)
    stats = _resolve_stats("min" if diff and stat is None else stat)
    labels, values, units, dims = _load_columns(runs, metrics, stats, pivot)
    if not labels:
        raise ValueError("no benchmarks found in the given run(s)")
    if len(labels) < 2 and len(runs) > 1:  # noqa: PLR2004 — distinct paths collapsed to one series
        raise ValueError(
            f"compare needs at least two distinct runs; got {labels!r} "
            f"(the same file more than once?). Pass distinct files."
        )
    if diff and len(labels) < 2:  # noqa: PLR2004 — a diff needs a baseline and at least one head
        raise ValueError(
            f"compare --diff needs at least two series to diff; got {len(labels)} {labels!r}. "
            f"Pass two or more runs, or one run with --pivot over a multi-value dim."
        )
    # One run is a plain readout: with no other run to rank against, the (N.NN) multiplier and
    # the best/worst colour are meaningless (best == worst == the value), so they're dropped.
    single = len(labels) == 1
    with_data = {col_id for col_id, _i, _lab in values}
    all_cols = [(m, s) for m in metrics for s in stats]
    cols = [(m, s) for m, s in all_cols if f"{m}:{s}" in with_data] or all_cols  # drop empties
    ids = sorted({test_id for _c, test_id, _lab in values})
    if csv is not None:
        _write_csv(values, [f"{m}:{s}" for m, s in cols], ids, labels, csv)

    groups: dict[tuple[str, ...], list[str]] = {}
    for test_id in ids:
        groups.setdefault(_group_of(test_id, dims.get(test_id, {}), group_by), []).append(test_id)

    # rss asked for but no run carries it: note it rather than silently dropping the column (which
    # would conflate "timing-only file" with "forgot to mark the benchmark isolate").
    rss_missing = "rss" in metrics and not any(col.startswith("rss:") for col in with_data)
    if diff:
        one_stat = len(stats) == 1
        diff_views = _build_diff_views(groups, cols, values, labels, sort)
        diff_renderers = {"table": _render_rich_diff, "md": _render_markdown_diff}
        diff_renderers[out_format](
            out, diff_views, cols, values, labels, one_stat=one_stat, rss_missing=rss_missing
        )
        return
    views = _build_views(groups, cols, values, units, labels, sort)
    render = _render_markdown if out_format == "md" else _render_rich
    render(out, views, values, single=single, rss_missing=rss_missing)


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


#: Raised when an ``rss`` gate has no data on both sides — `rss` exists only for isolated runs,
#: so silently passing would be a gate that can never fire. Loud beats a false green in CI.
_RSS_GATE_EMPTY = (
    "--fail-on rss: no benchmark carries rss in both runs — rss is recorded only for benchmarks "
    "marked @pytest.mark.benchmem(isolate=True). Mark the capacity benchmarks, or drop the rss "
    "gate."
)


def find_regressions(a: str | Path, b: str | Path, thresholds: list[Threshold]) -> list[Regression]:
    """Ids in both runs whose field grew past a threshold (only growth counts)."""
    regressions: list[Regression] = []
    for th in thresholds:
        base, head = _read_field(a, th.field), _read_field(b, th.field)
        if th.field == "rss" and not (base.keys() & head.keys()):
            raise ValueError(_RSS_GATE_EMPTY)
        regressions.extend(_regressions_for(base, head, th))
    return regressions


def find_pivot_regressions(
    run: str | Path, pivot: str, thresholds: list[Threshold]
) -> list[Regression]:
    """Regressions along a ``--pivot`` axis within *one* run — the gate generalized the same way
    the table is: with run-files the base is ``runs[0]`` and the head ``runs[-1]``; here the base
    is the first value of the ``pivot`` dim and the head the last (mirroring oldest→newest). Each
    fold-collapsed id is paired across them and flagged only on growth, reusing
    :func:`_regressions_for`.
    """
    regressions: list[Regression] = []
    for th in thresholds:
        # ``pivot`` folds the run so ``snapshot`` carries the dim's values and ``id`` is the
        # collapsed pairing key; the fail-on field doubles as the metric to read (headline scalar).
        df, _unit = load_long_df(run, metric=cast("Metric", th.field), pivot=pivot)
        labels = list(dict.fromkeys(df["snapshot"]))
        if len(labels) < 2:  # noqa: PLR2004 — a growth gate needs a base value and a head value
            raise ValueError(
                f"--fail-on with --pivot {pivot!r} needs two distinct values to gate; got "
                f"{labels}. Does the run vary {pivot!r}?"
            )
        base_label, head_label = labels[0], labels[-1]
        rows = zip(df["id"], df["value"], df["snapshot"], strict=True)
        side: dict[str, dict[str, float]] = {base_label: {}, head_label: {}}
        for test_id, value, label in rows:
            if label in side:
                side[label][test_id] = float(value)
        base, head = side[base_label], side[head_label]
        if th.field == "rss" and not (base.keys() & head.keys()):
            raise ValueError(_RSS_GATE_EMPTY)
        regressions.extend(_regressions_for(base, head, th))
    return regressions


#: Memory-blob key per fail-on field — the fields ``--benchmark-memory-compare-fail`` gates on.
_BLOB_FIELD = {
    "peak": "peak_bytes",
    "allocated": "total_bytes",
    "allocations": "allocations",
    "rss": "rss_bytes",
}


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
        # the blob is the per-repeat series; the gate reads its derived headline scalar.
        # ``rss`` is ``None`` for in-process blobs — skip those (nothing to gate there).
        out: dict[str, float] = {}
        for i, b in blobs.items():
            if "peak_bytes" not in b:
                continue
            scalar = getattr(MemoryResult.from_blob(b), attr)
            if scalar is not None:
                out[i] = float(scalar)
        return out

    regressions: list[Regression] = []
    for th in thresholds:
        if th.field not in _BLOB_FIELD:
            allowed = " or ".join(_BLOB_FIELD)
            raise ValueError(
                f"--benchmark-memory-compare-fail can't gate on {th.field!r}; use {allowed} "
                f"(timing is pytest-benchmark's own --benchmark-compare-fail)"
            )
        key = _BLOB_FIELD[th.field]
        base_h, head_h = headline(base_blobs, key), headline(head_blobs, key)
        if th.field == "rss" and not (base_h.keys() & head_h.keys()):
            raise ValueError(_RSS_GATE_EMPTY)
        regressions.extend(_regressions_for(base_h, head_h, th))
    return regressions
