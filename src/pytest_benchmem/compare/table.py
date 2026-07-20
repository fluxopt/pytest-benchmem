"""The multiplier table — the default ``compare`` view, in rich (terminal) or markdown.

Rows are one per ``(benchmark × run)``, columns are ``metric × stat``; with two or more runs
every cell carries a relative ``(N.NN)`` multiplier vs its column's best (best green, worst red in
the terminal). :func:`_build_views` computes the model once and :func:`_render_rich` /
:func:`_render_markdown` emit it, so the two formats can't drift.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TextIO

from pytest_benchmem.compare.model import (
    _COMPARE_WIDTH,
    _RSS_MISSING_NOTE,
    _group_title,
    _md_escape,
    _mult,
    _ordered_ids,
    _short,
)
from pytest_benchmem.format import byte_unit, fmt_bytes, fmt_count, rank_style


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
