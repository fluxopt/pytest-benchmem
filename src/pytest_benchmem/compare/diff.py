"""The diff view — metrics on the row axis, one Δ column per run.

A benchmark id becomes one row *per metric*; the columns stay flat — a baseline value, then a
signed Δ% per later run vs that baseline — no matter how many metrics are shown. The first series
is the baseline (matching the ``--fail-on`` gate, which measures the last run against the first). A
two-run diff is just ``<metric> base | <run>``; a sweep adds one Δ column per further run. The
per-run *absolute* value is dropped as redundant — it is recoverable as ``base × (1 + Δ)``.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TextIO

from pytest_benchmem.compare.model import (
    _COMPARE_WIDTH,
    _RSS_MISSING_NOTE,
    _col_id,
    _display_metric,
    _fmt_value,
    _group_title,
    _md_escape,
    _ordered_ids,
    _short,
)
from pytest_benchmem.format import growth


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
    case), else ``metric stat`` so a multi-stat diff stays unambiguous. A stat-less
    ``extra:NAME`` label column is always just its name.
    """
    name = _display_metric(metric)
    return name if one_stat or not stat else f"{name} {stat}"


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
        col_id = _col_id(metric, stat)
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
        gids = _ordered_ids(groups[key], values, _col_id(*cols[0]), list(labels), sort)
        ids = [
            i
            for i in gids
            if any((_col_id(m, s), i, lab) in values for m, s in cols for lab in labels)
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
