"""Render a per-run memory table for the terminal summary.

pytest-benchmark prints a timing table at the end of every run; this is its
memory counterpart. Given the ``{id: benchmem-blob}`` map the plugin collects
from ``extra_info``, :func:`build_run_table` returns a :class:`rich.table.Table`
to print — one row per benchmark that recorded memory, biggest peak first.

Memory-first, not a slavish copy of pytest-benchmark's table: rows sort by peak
*descending* (the heaviest consumer is what you came to find), bytes auto-scale
via :func:`~pytest_benchmem.snapshot.human_bytes`, and the heaviest peak is tinted
red, the lightest green. The ``max`` (worst peak across repeats) column appears
only when some test ran ``repeats > 1``; with a single repeat it equals ``peak``
and would just be noise.

rich is a core dependency (it rides in for the CLI via typer anyway), so the
plugin can render unconditionally — no plain-text fallback to keep in sync.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, NamedTuple

from pytest_benchmem.snapshot import human_bytes

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


#: The memory metric columns, in display order. ``_MAX_COL`` is kept by identity so
#: the builder can drop it when no test used ``repeats > 1`` (see :func:`_columns_for`).
_MAX_COL = _Column("max", True, lambda b: _bytes_cell(b, "peak_bytes_max"))
_METRIC_COLUMNS: list[_Column] = [
    _Column("peak", True, lambda b: _bytes_cell(b, "peak_bytes")),
    _MAX_COL,
    _Column("allocated", True, lambda b: _bytes_cell(b, "total_bytes")),
    _Column("allocs", True, lambda b: _count_cell(b, "allocations")),
]
_NAME_COL = _Column("name", False, lambda b: "")  # filled from the id, not the blob


def _has_spread(blobs: Mapping[str, Mapping[str, Any]]) -> bool:
    """True if any blob's worst peak differs from its reported peak (``repeats > 1``)."""
    return any(b.get("peak_bytes_max") != b.get("peak_bytes") for b in blobs.values())


def _columns_for(blobs: Mapping[str, Mapping[str, Any]]) -> list[_Column]:
    """Name, then the metric columns — minus ``max`` when no test used ``repeats > 1``."""
    keep_max = _has_spread(blobs)
    return [_NAME_COL] + [c for c in _METRIC_COLUMNS if c is not _MAX_COL or keep_max]


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
    base_blob: Mapping[str, Any] | None, blob: Mapping[str, Any], *, field: str = "peak_bytes"
) -> tuple[str, str, str | None]:
    """``(baseline-cell, change-cell, row-style)`` comparing ``blob`` to its baseline.

    A missing baseline id (new benchmark) or a zero baseline yields ``—`` and no
    tint; otherwise the row is tinted red on growth, green on a shrink.
    """
    if base_blob is None or base_blob.get(field) is None:
        return "—", "—", None
    vb, vh = float(base_blob[field]), float(blob.get(field, "nan"))
    if vb <= 0:
        return human_bytes(vb), "—", None
    pct = f"{(vh - vb) / vb * 100:+.1f}%"
    return human_bytes(vb), pct, "red" if vh > vb else "green" if vh < vb else None


def build_run_table(
    blobs: Mapping[str, Mapping[str, Any]],
    *,
    baseline: Mapping[str, Mapping[str, Any]] | None = None,
    baseline_label: str | None = None,
    title: str = "Memory",
) -> Table | None:
    """A rich table of this run's memory — biggest peak first, or ``None`` if empty.

    ``blobs`` maps benchmark id → its ``extra_info["benchmem"]`` blob. The ``max``
    column is dropped when no test used ``repeats > 1``. Rows sort by peak descending.

    Pass ``baseline`` (an ``{id: blob}`` map for a prior run) to fold the comparison
    into the *same* table: two extra columns — the baseline peak and the percent
    change — with rows tinted by regression (growth red, a shrink green) rather than
    by absolute weight. Ids absent from the baseline (new benchmarks) show ``—``.
    Without a baseline, rows are tinted heaviest-red / lightest-green.
    """
    if not blobs:
        return None
    from rich import box
    from rich.table import Table

    columns = _columns_for(blobs)
    order = sorted(blobs, key=lambda i: float(blobs[i].get("peak_bytes", 0)), reverse=True)
    comparing = baseline is not None

    if comparing:
        heading = f"{title} vs {baseline_label or 'baseline'}"
    else:
        heading = f"{title} — {len(blobs)} benchmark(s)"
    table = Table(title=heading, box=box.SIMPLE, title_justify="left")
    for col in columns:
        table.add_column(
            col.header, justify="right" if col.right else "left", no_wrap=not col.right
        )
    if comparing:
        table.add_column("baseline", justify="right")
        table.add_column("change", justify="right")

    for rank, test_id in enumerate(order):
        blob = blobs[test_id]
        cells = [_short(test_id)] + [col.cell(blob) for col in columns[1:]]
        if comparing:
            assert baseline is not None  # narrowed by `comparing`; for the type-checker
            base_cell, change_cell, style = _baseline_delta(baseline.get(test_id), blob)
            cells += [base_cell, change_cell]
        else:
            style = _row_style(rank, len(order))
        table.add_row(*cells, style=style)
    return table
