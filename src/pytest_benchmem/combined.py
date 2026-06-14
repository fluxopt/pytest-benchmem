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
from typing import TYPE_CHECKING, Any, NamedTuple

from pytest_benchmem.snapshot import BENCHMEM_KEY

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


_BYTE_STEPS = (("KiB", 1024.0), ("MiB", 1024.0**2), ("GiB", 1024.0**3), ("TiB", 1024.0**4))


def _byte_unit(max_bytes: float) -> tuple[str, float]:
    """Unit ``(name, divisor)`` to render a byte column, chosen from its largest value."""
    name, factor = "B", 1.0
    for step_name, step_factor in _BYTE_STEPS:
        if max_bytes >= step_factor:
            name, factor = step_name, step_factor
    return name, factor


class _MemCol(NamedTuple):
    """A memory column: header (unit hoisted in), blob field, and the group best/worst.

    Smaller is better for every memory metric, so ``best`` is the column min, ``worst``
    its max — mirroring how a timing column colours and annotates against its best.
    """

    header: str
    field: str
    factor: float | None  # byte divisor, or None for a plain count
    best: float
    worst: float

    def scaled(self, value: float) -> str:
        """``value`` as a bare number in this column's unit (counts get a thousands sep)."""
        if self.factor is None:
            return f"{int(value):,}"
        return f"{value:,.0f}" if self.factor == 1.0 else f"{value / self.factor:,.2f}"


def _mem_columns(blobs: Mapping[str, Mapping[str, Any]]) -> list[_MemCol]:
    """Memory columns for a group — units hoisted into headers, with per-column best/worst.

    ``max`` (worst peak across repeats) appears only when some test used ``repeats > 1``;
    ``allocs`` is a count (no unit). Each byte column picks one unit from its own largest
    value, so cells are bare numbers like the timing side rather than per-cell ``KiB``/``MiB``.
    """
    if not blobs:
        return []
    byte_fields = [("peak", "peak_bytes"), ("allocated", "total_bytes")]
    if any(b.get("peak_bytes_max") != b.get("peak_bytes") for b in blobs.values()):
        byte_fields.insert(1, ("max", "peak_bytes_max"))

    cols: list[_MemCol] = []
    for label, field in byte_fields:
        values = [float(b[field]) for b in blobs.values() if b.get(field) is not None]
        if not values:
            continue
        unit, factor = _byte_unit(max(values))
        cols.append(_MemCol(f"{label} ({unit})", field, factor, min(values), max(values)))
    allocs = [float(b["allocations"]) for b in blobs.values() if b.get("allocations") is not None]
    if allocs:
        cols.append(_MemCol("allocs", "allocations", None, min(allocs), max(allocs)))
    return cols


def _mem_cell(col: _MemCol, blob: Mapping[str, Any] | None, *, solo: bool) -> Text:
    """One memory cell — scaled, ``(1.0)``-annotated, and ranked, exactly like a timing cell.

    The ``(ratio)`` is dropped when the column's best is zero: a ratio to a zero floor
    is undefined (every other row would read ``(inf)``), so the bare value is clearer.
    """
    if blob is None or blob.get(col.field) is None:
        return _cell("—")
    value = float(blob[col.field])
    text = col.scaled(value)
    if col.best > 0:
        text += _rel(value, col.best, solo=solo)
    return _cell(text, style=_rank_style(value, col.best, col.worst, solo=solo))


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
    ``allocs``) are appended for the benchmarks that recorded memory;
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
        mem_cols = _mem_columns(group_blobs)

        title = f"benchmark{'' if group is None else f' {group!r}'}: {len(benchmarks)} tests"
        # The memory columns come from a separate, untimed pass — say so, and divide them
        # off the timing distribution so peak isn't read as "over those rounds".
        caption = _MEMORY_CAPTION if mem_cols else None
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

        for bench in benchmarks:
            cells: list[Text] = [_cell(name_format(bench))]
            cells += [
                _timing_cell(bench, p, adj=adj, ops_adj=ops_adj, best=best, worst=worst, solo=solo)
                for p in columns
            ]
            if mem_cols:
                blob = _blob_of(bench)
                cells.append(_cell(_DIVIDER, style="dim"))
                cells += [_mem_cell(col, blob, solo=solo) for col in mem_cols]
            table.add_row(*cells)
        console.print(table)
