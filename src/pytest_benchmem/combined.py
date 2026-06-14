"""One table for both metrics — pytest-benchmark's timing columns plus memory.

When a run records memory, pytest-benchmem suppresses pytest-benchmark's own table
and prints this instead: the *same* timing columns, per-group scaling, sort, and
best/worst colouring pytest-benchmark would show, with ``peak`` / ``allocated`` /
``allocs`` folded on as extra columns.

It does not re-derive any timing maths. It reuses pytest-benchmark's already-computed
grouping (``bs.groups``), its configured ``columns`` / ``sort``, its ``name_format``,
and its ``pytest_benchmark_scale_unit`` hook — so the timing cells match what
pytest-benchmark prints, byte-for-byte, and we only *add* the memory side. That keeps
the coupling to reads of pytest-benchmark's public objects, never its renderer.

Cells are built as :class:`rich.text.Text`, not markup strings, so a parametrized id
like ``test_x[1000]`` is never mistaken for a ``rich`` markup tag.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from operator import itemgetter
from typing import TYPE_CHECKING, Any

from pytest_benchmem.snapshot import BENCHMEM_KEY
from pytest_benchmem.tables import _columns_for

if TYPE_CHECKING:
    from rich.text import Text

#: Render width. pytest-benchmark's table writes very wide lines and lets the terminal
#: wrap; rich would instead crop cells to the console width, so we hand it a generous
#: width and let the table size to its content (the terminal wraps the long lines).
_WIDE = 10_000

#: Timing columns whose cells are scaled floats (the rest are counts/strings). Mirrors
#: pytest_benchmark.table so our formatting matches theirs.
_SCALED = ("min", "max", "mean", "median", "iqr", "stddev")
#: Props pytest-benchmark finds a best/worst for (for colouring + unit scaling).
_RANKED = (*_SCALED, "ops")
_LABELS = {
    "min": "Min",
    "max": "Max",
    "mean": "Mean",
    "stddev": "StdDev",
    "rounds": "Rounds",
    "iterations": "Iterations",
    "iqr": "IQR",
    "median": "Median",
    "outliers": "Outliers",
    "ops": "OPS",
}
_NUMBER_FMT = "{0:,.4f}"

#: Scale hook: ``(unit, benchmarks, best, worst, sort) -> (unit_str, adjustment)``.
ScaleUnit = Callable[..., tuple[str, float]]


def _best_worst(benchmarks: Sequence[Any]) -> tuple[dict[str, float], dict[str, float]]:
    """Per-prop best/worst across a group, the way pytest-benchmark computes them."""
    best: dict[str, float] = {}
    worst: dict[str, float] = {}
    for prop in _RANKED:
        values = [b[prop] for b in benchmarks]
        # ops: bigger is better; everything else: smaller is better.
        best[prop], worst[prop] = (
            (max(values), min(values))
            if prop == "ops"
            else (
                min(values),
                max(values),
            )
        )
    for prop in ("outliers", "rounds", "iterations"):
        worst[prop] = max(b[prop] for b in benchmarks)
    return best, worst


def _cell(text: str, *, style: str | None = None) -> Text:
    """A non-markup table cell (so ``[...]`` in ids/values is taken literally)."""
    from rich.text import Text

    return Text(text, style=style or "")


def _rank_style(value: float, best: float, worst: float, *, solo: bool) -> str | None:
    """Green for the group best, red for the worst, nothing in between (or if solo)."""
    if solo:
        return None
    if value == best:
        return "green"
    if value == worst:
        return "red"
    return None


def _timing_cell(
    bench: Any,
    prop: str,
    *,
    adj: float,
    ops_adj: float,
    best: Mapping[str, float],
    worst: Mapping[str, float],
    solo: bool,
) -> Text:
    """One timing cell, scaled and coloured exactly as pytest-benchmark's table would."""
    if prop in _SCALED:
        value = bench[prop]
        return _cell(
            _NUMBER_FMT.format(value * adj),
            style=_rank_style(value, best[prop], worst[prop], solo=solo),
        )
    if prop == "ops":
        value = bench[prop]
        return _cell(
            _NUMBER_FMT.format(value * ops_adj),
            style=_rank_style(value, best[prop], worst[prop], solo=solo),
        )
    return _cell(str(bench[prop]))  # outliers / rounds / iterations — plain counts


def _blob_of(bench: Any) -> Mapping[str, Any] | None:
    """The memory blob on a benchmark, or ``None`` for a timing-only test.

    ``bs.groups`` holds pytest-benchmark's *flat dicts* (``bench.as_dict(flat=True)``),
    so reads go through ``[...]`` — which also works on the ``Metadata`` objects.
    """
    try:
        extra = bench["extra_info"]
    except (KeyError, TypeError):
        return None
    blob = extra.get(BENCHMEM_KEY) if isinstance(extra, Mapping) else None
    return blob if isinstance(blob, Mapping) else None


def render_combined_tables(
    groups: Sequence[tuple[str | None, Sequence[Any]]],
    *,
    columns: Sequence[str],
    sort: str,
    name_format: Callable[[Any], str],
    scale_unit: ScaleUnit,
) -> None:
    """Print one rich table per group: pytest-benchmark's timing columns plus memory.

    ``groups`` is ``bs.groups`` (``(group_name, [Metadata, ...])``); ``columns`` /
    ``sort`` / ``name_format`` / ``scale_unit`` are pytest-benchmark's own, so the
    timing side renders identically. Memory columns (``peak`` / ``allocated`` /
    ``allocs``, mode-aware) are appended for the benchmarks that recorded memory;
    timing-only rows show ``—`` there.
    """
    from rich import box
    from rich.console import Console
    from rich.table import Table

    console = Console(width=_WIDE)
    for group, benchmarks in groups:
        benchmarks = sorted(benchmarks, key=itemgetter(sort))
        solo = len(benchmarks) == 1
        best, worst = _best_worst(benchmarks)
        unit, adj = scale_unit(
            unit="seconds", benchmarks=benchmarks, best=best, worst=worst, sort=sort
        )
        ops_unit, ops_adj = scale_unit(
            unit="operations", benchmarks=benchmarks, best=best, worst=worst, sort=sort
        )

        group_blobs = {b["fullname"]: blob for b in benchmarks if (blob := _blob_of(b)) is not None}
        mem_cols = _columns_for(_mode_of(group_blobs), group_blobs)[1:] if group_blobs else []
        peaks = [float(b["peak_bytes"]) for b in group_blobs.values()] if group_blobs else []
        peak_best, peak_worst = (min(peaks), max(peaks)) if peaks else (0.0, 0.0)

        title = f"benchmark{'' if group is None else f' {group!r}'}: {len(benchmarks)} tests"
        table = Table(title=title, box=box.SIMPLE, title_justify="left", title_style="yellow")
        table.add_column(f"Name (time in {unit}s)", justify="left", no_wrap=True)
        for prop in columns:
            label = _LABELS.get(prop, prop)
            table.add_column(
                f"OPS ({ops_unit}ops/s)" if prop == "ops" and ops_unit else label, justify="right"
            )
        for col in mem_cols:
            table.add_column(col.header, justify="right")

        for bench in benchmarks:
            cells: list[Text] = [_cell(name_format(bench))]
            cells += [
                _timing_cell(bench, p, adj=adj, ops_adj=ops_adj, best=best, worst=worst, solo=solo)
                for p in columns
            ]
            blob = _blob_of(bench)
            for col in mem_cols:
                if blob is None:
                    cells.append(_cell("—"))
                    continue
                style = None
                if col.header == "peak" and not solo and peaks:
                    style = _rank_style(float(blob["peak_bytes"]), peak_best, peak_worst, solo=solo)
                cells.append(_cell(col.cell(blob), style=style))
            table.add_row(*cells)
        console.print(table)


def _mode_of(blobs: Mapping[str, Mapping[str, Any]]) -> str:
    """The measurement mode of a group's blobs (heap unless an rss blob leads)."""
    from pytest_benchmem.snapshot import DEFAULT_MODE, MODE_KEY

    return str(next(iter(blobs.values())).get(MODE_KEY, DEFAULT_MODE)) if blobs else DEFAULT_MODE
