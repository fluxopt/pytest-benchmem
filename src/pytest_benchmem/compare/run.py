"""``compare_runs`` — the dispatcher that loads the columns once and fans out to a view.

It resolves ``--columns`` / ``--stat`` / ``--group-by`` / ``--sort``, loads the shared
``(labels, values, units, dims)`` model, then renders it as the multiplier table (:mod:`.table`)
or, under ``diff=True``, the baseline diff (:mod:`.diff`) — in ``table`` or ``md`` form.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from pytest_benchmem.compare.diff import (
    _build_diff_views,
    _render_markdown_diff,
    _render_rich_diff,
)
from pytest_benchmem.compare.model import (
    _SORTS,
    _group_of,
    _load_columns,
    _resolve_columns,
    _resolve_stats,
    _write_csv,
)
from pytest_benchmem.compare.table import _build_views, _render_markdown, _render_rich


def compare_runs(
    runs: Sequence[str | Path],
    *,
    columns: Sequence[str] | str | None = None,
    stat: str | None = None,
    group_by: str | None = "fullname",
    sort: str = "name",
    pivot: str | None = None,
    out_format: str = "table",
    diff: bool = False,
    csv: Path | None = None,
    out: TextIO | None = None,
) -> None:
    """Print a per-(benchmark, series) table for one or more runs.

    Mirrors pytest-benchmark's table model: rows are one per ``(benchmark × series)``, where
    the **series axis** is the run-file by default (one column-group per run). With two or more
    series each cell carries a relative ``(N.NN)`` multiplier vs the group's best (best green,
    worst red); a single series is a plain readout with neither. ``columns`` selects which metric
    columns appear (``time`` / ``peak`` / ``allocated`` / ``allocations``). ``group_by`` splits
    the rows into sub-tables (``fullname`` / ``name`` / ``func`` / ``group`` / ``module`` /
    ``class`` / ``param:NAME``, comma-composable); with no ``group_by`` the whole comparison is
    one table.

    ``pivot`` re-points the series axis from the run-file onto a data dim (``param:NAME`` or a
    bare ``extra_info`` name), folding a *single* combined run along that dim: rows that differ
    only in it pair up and its values become the compared series — the A/B a run-file pair gives
    you today, without splitting the data into N files. Distinct from ``group_by`` (which only
    clusters rows into sub-tables, leaving the run-files as the compared series): ``pivot`` sets
    *what* is compared, ``group_by`` sets how rows cluster. It composes with ``columns`` /
    ``stat`` / ``sort`` / ``group_by`` unchanged and is mutually exclusive with multiple runs
    (one series axis per table).

    Every column is a ``metric × stat`` pair. ``columns`` is a comma list of metric names
    (default ``time,peak``); ``stat`` is one of ``min`` / ``max`` / ``mean`` / ``median`` /
    ``stddev`` or ``all`` (the default), which expands each metric into its full stat
    spread — so no single statistic is privileged. A metric absent from every run is
    dropped rather than shown all dashes (so timing-only runs collapse to just ``time``).
    ``sort`` orders rows within a group: ``name``, ``value`` (largest in the last series), or
    ``change`` (biggest growth first). ``out_format`` picks the rendering — ``table`` (the rich
    terminal default) or ``md`` (GitHub-flavored markdown to ``out``, for a PR comment or
    ``$GITHUB_STEP_SUMMARY``); both render the same model. ``csv`` also writes the raw (unscaled)
    comparison to a file.

    ``diff`` switches to the collapsed baseline view: metrics move onto the *row* axis (one row per
    benchmark × metric), and the columns stay flat — the first run's value, then one signed ``Δ%``
    per later run vs that baseline (coloured by direction, red on growth, green on shrink). The
    per-run absolute value is dropped as redundant (recoverable as ``base × (1 + Δ)``), so the table
    is tall rather than wide no matter how many runs or metrics. Δ is always measured against the
    first run (matching the ``--fail-on`` gate); a single metric drops the metric column. It needs
    at least two series — two or more runs, or one run folded with ``pivot`` over a multi-value
    dim — and defaults ``stat`` to ``min`` (pass ``--stat`` to override). Both ``table`` and ``md``
    render it.
    """
    if sort not in _SORTS:
        raise ValueError(f"unknown --sort {sort!r}; use one of {', '.join(_SORTS)}")
    if out_format not in ("table", "md"):
        raise ValueError(f"unknown --format {out_format!r}; use table or md")
    # The diff view is a base→head readout, so a full stat spread would triple every column; when
    # the user hasn't asked for a specific stat, show just the headline min.
    metrics = _resolve_columns(columns)
    stats = _resolve_stats("min" if diff and stat is None else stat)
    labels, values, units, dims = _load_columns(runs, metrics, stats, pivot)
    if not labels:
        raise ValueError("no benchmarks found in the given run(s)")
    if len(labels) < 2 and len(runs) > 1:  # noqa: PLR2004 — distinct paths collapsed to one series
        raise ValueError(
            f"compare needs at least two distinct runs; got {labels!r} "
            f"(the same file more than once?). Pass distinct files."
        )
    if diff and len(labels) < 2:  # noqa: PLR2004 — a diff needs a baseline and at least one head
        raise ValueError(
            f"compare --diff needs at least two series to diff; got {len(labels)} {labels!r}. "
            f"Pass two or more runs, or one run with --pivot over a multi-value dim."
        )
    # One run is a plain readout: with no other run to rank against, the (N.NN) multiplier and
    # the best/worst colour are meaningless (best == worst == the value), so they're dropped.
    single = len(labels) == 1
    with_data = {col_id for col_id, _i, _lab in values}
    all_cols = [(m, s) for m in metrics for s in stats]
    cols = [(m, s) for m, s in all_cols if f"{m}:{s}" in with_data] or all_cols  # drop empties
    ids = sorted({test_id for _c, test_id, _lab in values})
    if csv is not None:
        _write_csv(values, [f"{m}:{s}" for m, s in cols], ids, labels, csv)

    groups: dict[tuple[str, ...], list[str]] = {}
    for test_id in ids:
        groups.setdefault(_group_of(test_id, dims.get(test_id, {}), group_by), []).append(test_id)

    # rss asked for but no run carries it: note it rather than silently dropping the column (which
    # would conflate "timing-only file" with "forgot to mark the benchmark isolate").
    rss_missing = "rss" in metrics and not any(col.startswith("rss:") for col in with_data)
    if diff:
        one_stat = len(stats) == 1
        diff_views = _build_diff_views(groups, cols, values, labels, sort)
        diff_renderers = {"table": _render_rich_diff, "md": _render_markdown_diff}
        diff_renderers[out_format](
            out, diff_views, cols, values, labels, one_stat=one_stat, rss_missing=rss_missing
        )
        return
    views = _build_views(groups, cols, values, units, labels, sort)
    render = _render_markdown if out_format == "md" else _render_rich
    render(out, views, values, single=single, rss_missing=rss_missing)
