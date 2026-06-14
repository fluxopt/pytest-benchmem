"""Render a per-run memory table for the terminal summary.

pytest-benchmark prints a timing table at the end of every run; this is its
memory counterpart. Given the ``{id: benchmem-blob}`` map the plugin collects
from ``extra_info``, :func:`build_run_table` returns a :class:`rich.table.Table`
to print — one row per benchmark that recorded memory, biggest peak first.

Memory-first, not a slavish copy of pytest-benchmark's table: rows sort by peak
*descending* (the heaviest consumer is what you came to find), each byte column
hoists one unit into its header (``peak (MiB)``, bare cells) the way pytest-benchmark
labels its timing unit, and the heaviest peak is tinted red, the lightest green. The
``max`` (worst peak across repeats) column appears only when some test ran
``repeats > 1``; with a single repeat it equals ``peak`` and would just be noise.

rich is a core dependency (it rides in for the CLI via typer anyway), so the
plugin can render unconditionally — no plain-text fallback to keep in sync.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from rich.table import Table


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


def _fmt_bytes(value: float | None, factor: float) -> str:
    """A byte value rendered bare in the column's unit (``—`` when missing)."""
    if value is None:
        return "—"
    return f"{float(value):,.0f}" if factor == 1.0 else f"{float(value) / factor:,.2f}"


def _count_cell(value: float | None) -> str:
    """A thousands-separated count, or ``—`` when absent."""
    return f"{int(value):,}" if value is not None else "—"


class _Column(NamedTuple):
    """A table column: a header, whether to right-align, and a blob → cell fn."""

    header: str
    right: bool
    cell: Callable[[Mapping[str, Any]], str]


#: Byte columns, in display order (``max`` dropped when no test used ``repeats > 1``).
_BYTE_FIELDS = (("peak", "peak_bytes"), ("max", "peak_bytes_max"), ("allocated", "total_bytes"))
_NAME_COL = _Column("name", False, lambda b: "")  # filled from the id, not the blob


def _has_spread(blobs: Mapping[str, Mapping[str, Any]]) -> bool:
    """True if any blob's worst peak differs from its reported peak (``repeats > 1``)."""
    return any(b.get("peak_bytes_max") != b.get("peak_bytes") for b in blobs.values())


def _byte_column(
    label: str, field: str, blobs: Mapping[str, Mapping[str, Any]]
) -> tuple[_Column, float]:
    """A byte column with its unit hoisted into the header, plus the chosen divisor."""
    values = [float(b[field]) for b in blobs.values() if b.get(field) is not None]
    unit, factor = _byte_unit(max(values)) if values else ("B", 1.0)
    return _Column(f"{label} ({unit})", True, lambda b: _fmt_bytes(b.get(field), factor)), factor


def _columns_for(blobs: Mapping[str, Mapping[str, Any]]) -> tuple[list[_Column], float]:
    """Name + metric columns with byte units hoisted into the headers, and the peak
    column's divisor (for the baseline column). ``max`` is dropped without a spread.
    """
    keep_max = _has_spread(blobs)
    cols = [_NAME_COL]
    peak_factor = 1.0
    for label, field in _BYTE_FIELDS:
        if label == "max" and not keep_max:
            continue
        col, factor = _byte_column(label, field, blobs)
        if label == "peak":
            peak_factor = factor
        cols.append(col)
    cols.append(_Column("allocs", True, lambda b: _count_cell(b.get("allocations"))))
    return cols, peak_factor


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
    base_blob: Mapping[str, Any] | None,
    blob: Mapping[str, Any],
    factor: float,
    *,
    field: str = "peak_bytes",
) -> tuple[str, str, str | None]:
    """``(baseline-cell, change-cell, row-style)`` comparing ``blob`` to its baseline.

    The baseline value renders bare in the peak column's unit (``factor``). A missing
    baseline id (new benchmark) or a zero baseline yields ``—`` and no tint; otherwise
    the row is tinted red on growth, green on a shrink.
    """
    if base_blob is None or base_blob.get(field) is None:
        return "—", "—", None
    vb, vh = float(base_blob[field]), float(blob.get(field, "nan"))
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

    columns, peak_factor = _columns_for(blobs)
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
        # base column shares the peak column's unit: "peak (MiB)" → "base (MiB)".
        table.add_column(columns[1].header.replace("peak", "base", 1), justify="right")
        table.add_column("change", justify="right")

    for rank, test_id in enumerate(order):
        blob = blobs[test_id]
        cells = [_short(test_id)] + [col.cell(blob) for col in columns[1:]]
        if comparing:
            assert baseline is not None  # narrowed by `comparing`; for the type-checker
            base_cell, change_cell, style = _baseline_delta(
                baseline.get(test_id), blob, peak_factor
            )
            cells += [base_cell, change_cell]
        else:
            style = _row_style(rank, len(order))
        table.add_row(*cells, style=style)
    return table
