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
from math import isinf
from operator import itemgetter
from typing import TYPE_CHECKING, Any

from pytest_benchmem.snapshot import BENCHMEM_KEY

if TYPE_CHECKING:
    from rich.text import Text

    from pytest_benchmem.memray import MemoryResult

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

#: Visual break between the timing distribution and the memory columns, with a caption
#: spelling out that memory is a separate measurement — not part of the timed rounds.
_DIVIDER = "│"
_MEMORY_CAPTION = (
    "memory (right of │): a separate, untimed pass — single shot, not the timed rounds"
)

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


def _rel(value: float, best: float, *, solo: bool) -> str:
    """The ``(1.0)`` / ``(5.23)`` baseline-relative suffix pytest-benchmark appends.

    Ratio to the group best (scale-invariant, so raw values are fine). Empty for a
    solo group — pytest-benchmark drops it there too.
    """
    if solo:
        return ""
    if value == best:
        return " (1.0)"
    scale = abs(value / best) if best else float("inf")
    if scale > 1000:  # noqa: PLR2004 — pytest-benchmark's own cutoff
        return " (inf)" if isinf(scale) else " (>1000.0)"
    return f" ({scale:.2f})"


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
    """One timing cell, scaled, ranked, and annotated exactly as pytest-benchmark's would."""
    if prop in _SCALED or prop == "ops":
        value = bench[prop]
        scale = ops_adj if prop == "ops" else adj
        text = _NUMBER_FMT.format(value * scale) + _rel(value, best[prop], solo=solo)
        return _cell(text, style=_rank_style(value, best[prop], worst[prop], solo=solo))
    return _cell(str(bench[prop]))  # outliers / rounds / iterations — plain counts


def _result_of(bench: Any) -> MemoryResult | None:
    """The :class:`MemoryResult` for a benchmark, or ``None`` for a timing-only test.

    ``bs.groups`` holds pytest-benchmark's *flat dicts* (``bench.as_dict(flat=True)``),
    so reads go through ``[...]``. The stored blob is the per-repeat series.
    """
    from pytest_benchmem.memray import MemoryResult

    try:
        extra = bench["extra_info"]
    except (KeyError, TypeError):
        return None
    blob = extra.get(BENCHMEM_KEY) if isinstance(extra, Mapping) else None
    return MemoryResult.from_blob(blob) if isinstance(blob, Mapping) else None


def _peak_delta_cells(
    base: MemoryResult | None, res: MemoryResult | None, factor: float
) -> list[Text]:
    """``[baseline-peak, Δ%]`` for the compare fold — baseline peak bare in ``factor``.

    A missing baseline or current peak yields ``—``; growth is tinted red, a shrink green.
    """
    if base is None or res is None:
        return [_cell("—"), _cell("—")]
    bp, cp = float(base.peak_bytes), float(res.peak_bytes)
    delta = f"{(cp - bp) / bp * 100:+.1f}%" if bp > 0 else "—"
    style = "red" if cp > bp else "green" if cp < bp else ""
    base_str = f"{bp:,.0f}" if factor == 1.0 else f"{bp / factor:,.2f}"
    return [_cell(base_str), _cell(delta, style=style)]


def render_combined_tables(
    groups: Sequence[tuple[str | None, Sequence[Any]]],
    *,
    columns: Sequence[str],
    sort: str,
    name_format: Callable[[Any], str],
    scale_unit: ScaleUnit,
    baseline: Mapping[str, Mapping[str, Any]] | None = None,
    baseline_label: str | None = None,
) -> None:
    """Print one rich table per group: pytest-benchmark's timing columns plus memory.

    ``groups`` is ``bs.groups`` (``(group_name, [Metadata, ...])``); ``columns`` /
    ``sort`` / ``name_format`` / ``scale_unit`` are pytest-benchmark's own, so the
    timing side renders identically. Memory columns (``peak`` / ``allocated`` /
    ``allocs``) are appended for the benchmarks that recorded memory;
    timing-only rows show ``—`` there.

    Pass ``baseline`` (an ``{id: blob}`` map from a prior run) to fold the memory
    comparison into the *same* table: a ``base`` peak column (in the peak column's
    unit) and a ``Δ peak`` column tinted by regression. New ids show ``—``.
    """
    from rich import box
    from rich.console import Console
    from rich.table import Table

    from pytest_benchmem.memray import MemoryResult
    from pytest_benchmem.tables import _byte_unit, mem_columns

    console = Console(width=_WIDE)
    base_results = (
        {i: MemoryResult.from_blob(b) for i, b in baseline.items()}
        if baseline is not None
        else None
    )
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

        results = {b["fullname"]: r for b in benchmarks if (r := _result_of(b)) is not None}
        mem_cols = mem_columns(list(results.values()))
        comparing = base_results is not None and bool(mem_cols)
        peak_factor = 1.0
        if comparing and base_results is not None:
            peaks = [r.peak_bytes for r in results.values()]
            peaks += [r.peak_bytes for r in base_results.values()]
            base_unit, peak_factor = _byte_unit(max(peaks)) if peaks else ("B", 1.0)

        title = f"benchmark{'' if group is None else f' {group!r}'}: {len(benchmarks)} tests"
        # The memory columns come from a separate, untimed pass — say so, and divide them
        # off the timing distribution so peak isn't read as "over those rounds".
        caption = _MEMORY_CAPTION if mem_cols else None
        if comparing and caption:
            caption += f"; Δ peak vs {baseline_label or 'baseline'}"
        table = Table(
            title=title,
            caption=caption,
            box=box.SIMPLE,
            title_justify="left",
            title_style="yellow",
            caption_justify="left",
            caption_style="dim",
        )
        table.add_column(f"Name (time in {unit}s)", justify="left", no_wrap=True)
        for prop in columns:
            label = _LABELS.get(prop, prop)
            table.add_column(
                f"OPS ({ops_unit}ops/s)" if prop == "ops" and ops_unit else label, justify="right"
            )
        if mem_cols:
            table.add_column(_DIVIDER, justify="center", style="dim")
        for col in mem_cols:
            table.add_column(col.header, justify="right")
        if comparing:
            table.add_column(f"base ({base_unit})", justify="right")
            table.add_column("Δ peak", justify="right")

        for bench in benchmarks:
            cells: list[Text] = [_cell(name_format(bench))]
            cells += [
                _timing_cell(bench, p, adj=adj, ops_adj=ops_adj, best=best, worst=worst, solo=solo)
                for p in columns
            ]
            if mem_cols:
                res = results.get(bench["fullname"])
                cells.append(_cell(_DIVIDER, style="dim"))
                cells += [_cell(col.cell(res)) if res else _cell("—") for col in mem_cols]
                if comparing and base_results is not None:
                    cells += _peak_delta_cells(
                        base_results.get(bench["fullname"]), res, peak_factor
                    )
            table.add_row(*cells)
        console.print(table)
