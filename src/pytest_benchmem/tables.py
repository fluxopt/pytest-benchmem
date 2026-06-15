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
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, NamedTuple

from pytest_benchmem.format import byte_unit, fmt_bytes, fmt_count, growth

if TYPE_CHECKING:
    from rich.table import Table

    from pytest_benchmem.memray import MemoryResult


def _short(test_id: str) -> str:
    """The trailing node-id segment — ``module.py::test_x[1]`` → ``test_x[1]``."""
    return test_id.split("::")[-1]


class MemColumn(NamedTuple):
    """One memory column: a header and a ``MemoryResult`` → formatted-cell function."""

    header: str
    cell: Callable[[MemoryResult], str]


#: ``label -> (series field, is_byte)`` per memory metric, in canonical order.
_METRIC_SPEC: dict[str, tuple[str, bool]] = {
    "peak": ("peak_bytes", True),
    "allocated": ("total_bytes", True),
    "allocs": ("allocations", False),
}
#: Every metric, in order — what a direct library render shows.
ALL_METRICS: tuple[str, ...] = tuple(_METRIC_SPEC)
#: The default metric shown in a pytest run — peak is the headline; the rest are opt-in.
DEFAULT_METRICS: tuple[str, ...] = ("peak",)
#: The distribution stats a multi-repeat metric can spread into.
_STAT_FNS: dict[str, Callable[[Sequence[float]], float]] = {
    "min": min,
    "mean": statistics.fmean,
    "max": max,
    "median": statistics.median,
    "stddev": lambda xs: statistics.stdev(xs) if len(xs) > 1 else 0.0,
}
#: Default spread stats shown when a benchmark was measured more than once.
DEFAULT_STATS: tuple[str, ...] = ("min", "mean", "max")


def parse_metrics(spec: Sequence[str] | None) -> tuple[str, ...]:
    """Validate a memory-metric selection (order preserved); default = peak only."""
    if not spec:
        return DEFAULT_METRICS
    bad = [m for m in spec if m not in _METRIC_SPEC]
    if bad:
        raise ValueError(
            f"unknown memory metric(s): {', '.join(bad)}; choose from {', '.join(ALL_METRICS)}"
        )
    return tuple(spec)


def parse_stats(spec: Sequence[str] | None) -> tuple[str, ...]:
    """Validate a spread-stat selection (order preserved); default = min/mean/max."""
    if not spec:
        return DEFAULT_STATS
    bad = [s for s in spec if s not in _STAT_FNS]
    if bad:
        raise ValueError(
            f"unknown memory stat(s): {', '.join(bad)}; choose from {', '.join(_STAT_FNS)}"
        )
    return tuple(spec)


def _formatter(*, is_byte: bool, factor: float) -> Callable[[float], str]:
    """Cell formatter for a metric — bytes in ``factor``, or a plain count."""
    if is_byte:
        return lambda v: fmt_bytes(v, factor)
    return fmt_count


def _spread_cell(
    field: str, reduce: Callable[[Sequence[float]], float], fmt: Callable[[float], str]
) -> Callable[[MemoryResult], str]:
    """A cell that reduces ``field``'s per-repeat series with ``reduce`` (min/mean/max)."""
    return lambda r: fmt(reduce([float(v) for v in r.series(field)]))


def _single_cell(field: str, fmt: Callable[[float], str]) -> Callable[[MemoryResult], str]:
    """A cell for a single-pass metric — just the one measured value."""
    return lambda r: fmt(float(r.series(field)[0]))


def mem_columns(
    results: Sequence[MemoryResult],
    *,
    metrics: Sequence[str] = ALL_METRICS,
    stats: Sequence[str] = DEFAULT_STATS,
) -> list[MemColumn]:
    """Memory columns for a set of benchmarks.

    ``metrics`` selects which of ``peak`` / ``allocated`` / ``allocs`` appear, in order.
    When any benchmark was measured more than once (``repeats > 1``), every shown metric
    spreads into one column per ``stats`` entry (``min`` / ``mean`` / ``max`` / ``median``
    / ``stddev``) — always, even where the values coincide, so the distribution is honest
    and the table schema is stable. A single-pass run stays one column per metric (there
    is nothing to distribute). Byte metrics hoist one unit into the header (on the first
    column of a spread group). Selections are validated upstream by :func:`parse_metrics`
    / :func:`parse_stats`.
    """
    cols: list[MemColumn] = []
    for label in metrics:
        field, is_byte = _METRIC_SPEC[label]
        per_series = [[float(v) for v in r.series(field)] for r in results]
        all_values = [v for series in per_series for v in series]
        if not all_values:
            continue
        unit, factor = byte_unit(max(all_values)) if is_byte else ("", 1.0)
        fmt = _formatter(is_byte=is_byte, factor=factor)
        if any(len(s) > 1 for s in per_series):  # measured more than once → show the spread
            for i, stat_name in enumerate(stats):
                header = f"{label}·{stat_name}" + (f" ({unit})" if is_byte and i == 0 else "")
                cols.append(MemColumn(header, _spread_cell(field, _STAT_FNS[stat_name], fmt)))
        else:
            header = f"{label} ({unit})" if is_byte else label
            cols.append(MemColumn(header, _single_cell(field, fmt)))
    return cols


def peak_scale(*result_groups: Iterable[MemoryResult]) -> tuple[str, float]:
    """The shared ``(unit, divisor)`` for the baseline peak column — one scale across
    every benchmark's peak in the given groups (current + baseline), so the ``base``
    cell and the headline ``peak`` cell read on the same unit.
    """
    peaks = [r.peak_bytes for group in result_groups for r in group]
    return byte_unit(max(peaks)) if peaks else ("B", 1.0)


def hidden_metrics_hint(metrics: Sequence[str]) -> str | None:
    """Caption note naming the metrics *not* shown, or ``None`` when all are shown."""
    hidden = [m for m in ALL_METRICS if m not in metrics]
    if not hidden:
        return None
    return f"also available via --benchmark-memory-columns: {', '.join(hidden)}"


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
    pct, style = growth(vb, vh)
    return fmt_bytes(vb, factor), pct, style


def build_run_table(
    blobs: Mapping[str, Mapping[str, Any]],
    *,
    metrics: Sequence[str] = ALL_METRICS,
    stats: Sequence[str] = DEFAULT_STATS,
    baseline: Mapping[str, Mapping[str, Any]] | None = None,
    baseline_label: str | None = None,
    title: str = "Memory",
) -> Table | None:
    """A rich table of this run's memory — biggest peak first, or ``None`` if empty.

    ``blobs`` maps benchmark id → its ``extra_info["benchmem"]`` blob (per-repeat
    series). ``metrics`` selects which columns appear; with ``repeats > 1`` each spreads
    into the ``stats`` columns. Rows sort by the headline peak (min) descending.

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
    cols = mem_columns(list(results.values()), metrics=metrics, stats=stats)
    order = sorted(results, key=lambda i: results[i].peak_bytes, reverse=True)
    comparing = base_results is not None

    heading = (
        f"{title} vs {baseline_label or 'baseline'}"
        if comparing
        else f"{title} — {len(results)} benchmark(s)"
    )
    table = Table(
        title=heading,
        caption=hidden_metrics_hint(metrics),
        box=box.SIMPLE,
        title_justify="left",
        caption_justify="left",
        caption_style="dim",
    )
    table.add_column("name", justify="left", no_wrap=True)
    for col in cols:
        table.add_column(col.header, justify="right")

    peak_factor = 1.0
    if comparing and base_results is not None:
        unit, peak_factor = peak_scale(results.values(), base_results.values())
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
