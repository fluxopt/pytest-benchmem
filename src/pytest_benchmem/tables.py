"""Render a per-run memory table for the terminal summary.

pytest-benchmark prints a timing table at the end of every run; this is its
memory counterpart. Given the ``{id: benchmem-blob}`` map the plugin collects
from ``extra_info``, :func:`build_run_table` returns a :class:`rich.table.Table`
to print — one row per benchmark that recorded memory, biggest peak first.

Memory-first, not a slavish copy of pytest-benchmark's table: rows sort by peak
*descending* (the heaviest consumer is what you came to find), each byte column
hoists one unit into its header (``peak (MiB)``, bare cells) the way pytest-benchmark
labels its timing unit, and the heaviest peak is tinted red, the lightest green.

A metric that *varies* across ``repeats`` spreads into ``min`` / ``mean`` / ``max``
columns (like pytest-benchmark's timing distribution); a constant one (e.g. a
deterministic allocation count) stays a single column. The column logic
(:func:`mem_columns`) is shared with the combined timing+memory table.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from rich.table import Table

    from pytest_benchmem.memray import MemoryResult


def _short(test_id: str) -> str:
    """The trailing node-id segment — ``module.py::test_x[1]`` → ``test_x[1]``."""
    return test_id.split("::")[-1]


def _byte_unit(max_bytes: float) -> tuple[str, float]:
    """Unit ``(name, divisor)`` for a byte column, chosen from its largest value."""
    name, factor = "B", 1.0
    for step_name, step_factor in (("KiB", 1024.0), ("MiB", 1024.0**2), ("GiB", 1024.0**3)):
        if max_bytes >= step_factor:
            name, factor = step_name, step_factor
    return name, factor


def _fmt_bytes(value: float, factor: float) -> str:
    """A byte value rendered bare in the column's unit."""
    return f"{value:,.0f}" if factor == 1.0 else f"{value / factor:,.2f}"


def _count(value: float) -> str:
    """A thousands-separated count."""
    return f"{int(value):,}"


class MemColumn(NamedTuple):
    """One memory column: a header and a ``MemoryResult`` → formatted-cell function."""

    header: str
    cell: Callable[[MemoryResult], str]


#: ``(label, series field, is_byte)`` per memory metric, in display order.
_METRICS = (
    ("peak", "peak_bytes", True),
    ("allocated", "total_bytes", True),
    ("allocs", "allocations", False),
)
#: The distribution stats a varying metric spreads into.
_STATS: tuple[tuple[str, Callable[[Sequence[float]], float]], ...] = (
    ("min", min),
    ("mean", statistics.fmean),
    ("max", max),
)


def _formatter(*, is_byte: bool, factor: float) -> Callable[[float], str]:
    """Cell formatter for a metric — bytes in ``factor``, or a plain count."""
    if is_byte:
        return lambda v: _fmt_bytes(v, factor)
    return _count


def _spread_cell(
    field: str, reduce: Callable[[Sequence[float]], float], fmt: Callable[[float], str]
) -> Callable[[MemoryResult], str]:
    """A cell that reduces ``field``'s per-repeat series with ``reduce`` (min/mean/max)."""
    return lambda r: fmt(reduce([float(v) for v in r.series(field)]))


def _single_cell(field: str, fmt: Callable[[float], str]) -> Callable[[MemoryResult], str]:
    """A cell for a metric that's constant across repeats — just the value."""
    return lambda r: fmt(float(r.series(field)[0]))


def mem_columns(results: Sequence[MemoryResult]) -> list[MemColumn]:
    """Adaptive memory columns for a set of benchmarks.

    A metric whose per-repeat series *varies* (across any benchmark) spreads into
    ``min`` / ``mean`` / ``max`` columns; a constant metric stays one column. Byte
    metrics hoist one unit into the header (on the first column of a spread group).
    """
    cols: list[MemColumn] = []
    for label, field, is_byte in _METRICS:
        per_series = [[float(v) for v in r.series(field)] for r in results]
        all_values = [v for series in per_series for v in series]
        if not all_values:
            continue
        unit, factor = _byte_unit(max(all_values)) if is_byte else ("", 1.0)
        fmt = _formatter(is_byte=is_byte, factor=factor)
        if any(min(s) != max(s) for s in per_series):  # varies across repeats → spread it
            for i, (stat_name, reduce) in enumerate(_STATS):
                header = f"{label}·{stat_name}" + (f" ({unit})" if is_byte and i == 0 else "")
                cols.append(MemColumn(header, _spread_cell(field, reduce, fmt)))
        else:
            header = f"{label} ({unit})" if is_byte else label
            cols.append(MemColumn(header, _single_cell(field, fmt)))
    return cols


def _row_style(rank: int, total: int) -> str | None:
    """Colour cue by peak rank: heaviest red, lightest green, the rest unstyled."""
    if total < 2:  # noqa: PLR2004 — a single row has no best/worst to contrast
        return None
    if rank == 0:
        return "red"
    if rank == total - 1:
        return "green"
    return None


def _baseline_delta(
    base: MemoryResult | None, res: MemoryResult, factor: float
) -> tuple[str, str, str | None]:
    """``(baseline-peak, Δ%, row-style)`` comparing ``res`` to its baseline.

    The baseline peak renders bare in the peak column's unit. A new benchmark (no
    baseline) or a zero baseline yields ``—`` and no tint; otherwise the row is tinted
    red on growth, green on a shrink.
    """
    if base is None:
        return "—", "—", None
    vb, vh = float(base.peak_bytes), float(res.peak_bytes)
    if vb <= 0:
        return _fmt_bytes(vb, factor), "—", None
    pct = f"{(vh - vb) / vb * 100:+.1f}%"
    return _fmt_bytes(vb, factor), pct, "red" if vh > vb else "green" if vh < vb else None


def build_run_table(
    blobs: Mapping[str, Mapping[str, Any]],
    *,
    baseline: Mapping[str, Mapping[str, Any]] | None = None,
    baseline_label: str | None = None,
    title: str = "Memory",
) -> Table | None:
    """A rich table of this run's memory — biggest peak first, or ``None`` if empty.

    ``blobs`` maps benchmark id → its ``extra_info["benchmem"]`` blob (per-repeat
    series). A metric that varies across repeats spreads into min/mean/max columns;
    rows sort by the headline peak (min) descending.

    Pass ``baseline`` (an ``{id: blob}`` map for a prior run) to fold the comparison
    into the *same* table: ``base`` peak + ``change`` columns, rows tinted by regression
    (growth red, a shrink green). Ids absent from the baseline show ``—``.
    """
    if not blobs:
        return None
    from rich import box
    from rich.table import Table

    from pytest_benchmem.memray import MemoryResult

    results = {i: MemoryResult.from_blob(b) for i, b in blobs.items()}
    base_results = (
        {i: MemoryResult.from_blob(b) for i, b in baseline.items()}
        if baseline is not None
        else None
    )
    cols = mem_columns(list(results.values()))
    order = sorted(results, key=lambda i: results[i].peak_bytes, reverse=True)
    comparing = base_results is not None

    heading = (
        f"{title} vs {baseline_label or 'baseline'}"
        if comparing
        else f"{title} — {len(results)} benchmark(s)"
    )
    table = Table(title=heading, box=box.SIMPLE, title_justify="left")
    table.add_column("name", justify="left", no_wrap=True)
    for col in cols:
        table.add_column(col.header, justify="right")

    peak_factor = 1.0
    if comparing and base_results is not None:
        peaks = [r.peak_bytes for r in results.values()]
        peaks += [r.peak_bytes for r in base_results.values()]
        unit, peak_factor = _byte_unit(max(peaks))
        table.add_column(f"base ({unit})", justify="right")
        table.add_column("change", justify="right")

    for rank, test_id in enumerate(order):
        res = results[test_id]
        cells = [_short(test_id)] + [col.cell(res) for col in cols]
        if comparing and base_results is not None:
            base_cell, change_cell, style = _baseline_delta(
                base_results.get(test_id), res, peak_factor
            )
            cells += [base_cell, change_cell]
        else:
            style = _row_style(rank, len(order))
        table.add_row(*cells, style=style)
    return table
