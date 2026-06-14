"""Render a per-run memory table for the terminal summary.

pytest-benchmark prints a timing table at the end of every run; this is its
memory counterpart. Given the ``{id: benchmem-blob}`` map the plugin collects
from ``extra_info``, :func:`build_run_table` returns a :class:`rich.table.Table`
to print — one row per benchmark that recorded memory, biggest peak first.

Memory-first, not a slavish copy of pytest-benchmark's table: rows sort by peak
*descending* (the heaviest consumer is what you came to find), bytes auto-scale
via :func:`~pytest_benchmem.snapshot.human_bytes`, the heaviest peak is tinted red
and the lightest green, and the columns shown follow the measurement ``mode`` —
heap churn (allocated / allocations) is meaningless in rss mode, so it's omitted
there. The ``max`` (worst peak across repeats) column appears only when some test
ran ``repeats > 1``; with a single repeat it equals ``peak`` and would just be
noise.

rich is a core dependency (it rides in for the CLI via typer anyway), so the
plugin can render unconditionally — no plain-text fallback to keep in sync.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, NamedTuple

from pytest_benchmem.snapshot import DEFAULT_MODE, MODE_KEY, human_bytes

if TYPE_CHECKING:
    from rich.table import Table


def _short(test_id: str) -> str:
    """The trailing node-id segment — ``module.py::test_x[1]`` → ``test_x[1]``."""
    return test_id.split("::")[-1]


def _bytes_cell(blob: Mapping[str, Any], field: str) -> str:
    """Auto-scaled bytes for ``field``, or ``—`` when the blob lacks it."""
    value = blob.get(field)
    return human_bytes(float(value)) if value is not None else "—"


def _count_cell(blob: Mapping[str, Any], field: str) -> str:
    """A thousands-separated count, or ``—`` when absent."""
    value = blob.get(field)
    return f"{int(value):,}" if value is not None else "—"


class _Column(NamedTuple):
    """A table column: a header, whether to right-align, and a blob → cell fn."""

    header: str
    right: bool
    cell: Callable[[Mapping[str, Any]], str]


#: Universal peak columns, then mode-specific ones. ``peak``/``max`` apply in any
#: mode; heap adds churn (allocated / allocations), rss adds the resident
#: high-water (``gross``). ``_MAX_COL`` is kept by identity so the builder can
#: drop it when no test used ``repeats > 1`` (see :func:`build_run_table`).
_PEAK_COL = _Column("peak", True, lambda b: _bytes_cell(b, "peak_bytes"))
_MAX_COL = _Column("max", True, lambda b: _bytes_cell(b, "peak_bytes_max"))
_MODE_COLUMNS: dict[str, list[_Column]] = {
    "heap": [
        _PEAK_COL,
        _MAX_COL,
        _Column("allocated", True, lambda b: _bytes_cell(b, "total_bytes")),
        _Column("allocs", True, lambda b: _count_cell(b, "allocations")),
    ],
    "rss": [_PEAK_COL, _MAX_COL, _Column("gross", True, lambda b: _bytes_cell(b, "gross_bytes"))],
}
_NAME_COL = _Column("name", False, lambda b: "")  # filled from the id, not the blob


def _has_spread(blobs: Mapping[str, Mapping[str, Any]]) -> bool:
    """True if any blob's worst peak differs from its reported peak (``repeats > 1``)."""
    return any(b.get("peak_bytes_max") != b.get("peak_bytes") for b in blobs.values())


def _columns_for(mode: str, blobs: Mapping[str, Mapping[str, Any]]) -> list[_Column]:
    """The column set for ``mode``: name, then the metric columns, minus an idle ``max``."""
    keep_max = _has_spread(blobs)
    metric_cols = _MODE_COLUMNS.get(mode, _MODE_COLUMNS["heap"])
    return [_NAME_COL] + [c for c in metric_cols if c is not _MAX_COL or keep_max]


def _row_style(rank: int, total: int) -> str | None:
    """Colour cue by peak rank: heaviest red, lightest green, the rest unstyled."""
    if total < 2:  # noqa: PLR2004 — a single row has no best/worst to contrast
        return None
    if rank == 0:
        return "red"
    if rank == total - 1:
        return "green"
    return None


def build_run_table(
    blobs: Mapping[str, Mapping[str, Any]], *, title: str = "Memory"
) -> Table | None:
    """A rich table of this run's memory — biggest peak first, or ``None`` if empty.

    ``blobs`` maps benchmark id → its ``extra_info["benchmem"]`` blob. The columns
    shown follow the blobs' ``mode`` (heap vs rss); the ``max`` column is dropped
    when no test used ``repeats > 1``. Rows sort by peak descending and the
    heaviest/lightest are tinted (see :func:`_row_style`).
    """
    if not blobs:
        return None
    from rich import box
    from rich.table import Table

    mode = str(next(iter(blobs.values())).get(MODE_KEY, DEFAULT_MODE))
    columns = _columns_for(mode, blobs)
    order = sorted(blobs, key=lambda i: float(blobs[i].get("peak_bytes", 0)), reverse=True)

    table = Table(
        title=f"{title} ({mode}) — {len(blobs)} benchmark(s)", box=box.SIMPLE, title_justify="left"
    )
    for col in columns:
        table.add_column(
            col.header, justify="right" if col.right else "left", no_wrap=not col.right
        )
    for rank, test_id in enumerate(order):
        blob = blobs[test_id]
        cells = [_short(test_id)] + [col.cell(blob) for col in columns[1:]]
        table.add_row(*cells, style=_row_style(rank, len(order)))
    return table


def build_compare_table(
    baseline: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
    *,
    baseline_label: str | None = None,
    field: str = "peak_bytes",
) -> Table | None:
    """A rich peak-delta table for the ids in *both* runs, or ``None`` if none overlap.

    One row per shared benchmark id: the baseline value, the current value, and the
    percent change (growth tinted red, a shrink green). Mirrors the inline
    ``--benchmark-memory-compare`` view; ``baseline_label`` names the prior run.
    """
    shared = sorted(baseline.keys() & current.keys())
    if not shared:
        return None
    from rich import box
    from rich.table import Table

    base_header = f"baseline ({baseline_label})" if baseline_label else "baseline"
    table = Table(title="Memory vs baseline (peak)", box=box.SIMPLE, title_justify="left")
    table.add_column("name", justify="left", no_wrap=True)
    table.add_column(base_header, justify="right")
    table.add_column("current", justify="right")
    table.add_column("change", justify="right")
    for test_id in shared:
        vb = float(baseline[test_id].get(field, "nan"))
        vh = float(current[test_id].get(field, "nan"))
        grew = vh > vb
        pct = f"{(vh - vb) / vb * 100:+.1f}%" if vb > 0 else "—"
        style = "red" if vb > 0 and grew else "green" if vb > 0 and vh < vb else None
        table.add_row(_short(test_id), human_bytes(vb), human_bytes(vh), pct, style=style)
    return table
