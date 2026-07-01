"""Interactive plotly views over pytest-benchmark runs — dims-driven.

Each view reads one ``metric`` (``time`` / ``peak`` / ``allocated`` /
``allocations``) out of the pytest-benchmark JSON files and returns
``(figure, n_rendered)``:

- :func:`plot_compare` (2 runs) — bar chart of per-id delta.
- :func:`plot_scatter` (2+) — baseline cost vs ratio; top-right = the regressed one.
- :func:`plot_sweep` (3+) — heatmap of per-id fold-change (log2 ratio) vs the first.
- :func:`plot_scaling` (1+) — cost vs a numeric dim, faceted/coloured by others;
  multiple runs overlay as series.

The sweep/scatter/compare views key on the opaque ``id``; only ``scaling`` reads
``dims`` — and which dim is x / colour / facet is auto-inferred from dtype
(numeric → x) but overridable. plotly is imported lazily.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np

from pytest_benchmem.snapshot import (
    NODE_DIM_PREFIX,
    RESERVED_COLUMNS,
    Metric,
    _as_paths,
    load_long_df,
)

if TYPE_CHECKING:
    import numpy.typing as npt
    import pandas as pd
    from plotly.graph_objects import Figure

SortMode = Literal["absolute", "relative"]
FreeAxes = Literal["x", "y", "both"]

#: A plot input: one path or a sequence of them (str or Path).
Snapshots = str | Path | Sequence[str | Path]


def _labels_head(labels: Sequence[str] | None, n: int) -> list[str] | None:
    """The first ``n`` labels, aligned to a ``snapshots[:n]`` slice (or ``None``)."""
    return None if labels is None else list(labels)[:n]


def _diverging_kwargs(midpoint: float = 0.0) -> dict[str, object]:
    """green→white→red continuous colour scale centred on ``midpoint``."""
    return {
        "color_continuous_scale": ["green", "white", "red"],
        "color_continuous_midpoint": midpoint,
    }


def _symmetric_clip(
    magnitudes: npt.NDArray[np.float64], override: float | None, pct: float = 95.0
) -> float:
    """Symmetric colour bound: ``override`` if given, else the ``pct`` percentile
    of ``|magnitudes|`` so outliers don't wash the rest to the midpoint.
    """
    if override is not None:
        return float(override)
    mags = np.abs(np.asarray(magnitudes, dtype=float))
    mags = mags[np.isfinite(mags)]
    if mags.size == 0:
        return 1.0
    bound = float(np.percentile(mags, pct))
    return bound if bound > 0 else (float(mags.max()) or 1e-9)


def _fold_label(fold: float) -> str:
    """Format a fold-change for a colourbar tick: ``2×``, ``1/4×``, ``1.5×``."""
    if abs(fold - 1.0) < 1e-9:
        return "1×"
    return f"{fold:.3g}×" if fold > 1.0 else f"1/{1.0 / fold:.3g}×"


def _fold_ticks(bound: float) -> tuple[list[float], list[str]]:
    """Colourbar ticks (log2 positions, fold labels) spanning ±bound — clean
    powers of two for a wide range, round sub-2× folds for a tight one.
    """
    if bound >= 1.0:
        pos = [2.0**t for t in range(1, int(bound) + 1)]
    else:
        pos = [f for f in (1.1, 1.25, 1.5) if float(np.log2(f)) <= bound + 1e-9]
        if len(pos) < 2:
            pos = [2.0 ** (bound / 2), 2.0**bound]
    vals, text = [0.0], ["1×"]
    for f in sorted(pos):
        lv = float(np.log2(f))
        vals = [-lv, *vals, lv]
        text = [_fold_label(1.0 / f), *text, _fold_label(f)]
    return vals, text


def _axis_kwargs(unit: str) -> dict[str, object]:
    if unit in ("s", "B"):  # SI-scale time and bytes (1.2M, 3.4k…)
        return {"tickformat": ".2s", "ticksuffix": unit}
    return {"ticksuffix": f" {unit}"}


#: Human-friendly metric names for titles/axes — the raw metric is terse (``peak``, ``rss``).
_METRIC_LABEL = {
    "time": "time",
    "peak": "peak memory",
    "allocated": "memory allocated",
    "allocations": "allocations",
    "rss": "RSS (peak)",
}

#: Spelled-out unit for a title/axis note; the tick suffix keeps the short symbol (``B`` / ``s``).
_UNIT_NOTE = {"B": "bytes", "s": "seconds"}


def _metric_label(metric: str) -> str:
    """Human-friendly metric name for a title or axis (``peak`` → ``peak memory``)."""
    return _METRIC_LABEL.get(metric, metric)


def _unit_note(unit: str) -> str:
    """Parenthetical unit note for a title/axis: " (bytes)", " (seconds)", or "" for counts."""
    return f" ({_UNIT_NOTE[unit]})" if unit in _UNIT_NOTE else ""


def _carry_dims(df: pd.DataFrame) -> list[str]:
    """Every analysis dim in the frame (params/extra_info + ``node.*``), minus fixed axes.

    Used to *preserve* dims through a pivot so any is still selectable by name.
    """
    return [c for c in df.columns if c not in RESERVED_COLUMNS]


def _dim_columns(df: pd.DataFrame) -> list[str]:
    """Auto-inferable dims: :func:`_carry_dims` minus the ``node.*`` structural dims —
    those are selectable by name (``facet="node.func"``) but never auto-picked.
    """
    return [c for c in _carry_dims(df) if not c.startswith(NODE_DIM_PREFIX)]


def _apply_where(df: pd.DataFrame, where: Mapping[str, str] | None) -> pd.DataFrame:
    """Keep rows matching every ``key=value`` in ``where`` (AND-combined).

    Applied to the long frame *before* any view-specific logic, so it behaves
    identically across all plot types. Each value matches by string form, with a
    numeric fallback so ``size=1000`` matches a ``1000`` / ``1000.0`` dim. Keys must
    name a real dim; an empty result is an error (the filter selected nothing).
    """
    if not where:
        return df
    import pandas as pd

    dims = _carry_dims(df)
    for key, val in where.items():
        if key not in dims:
            raise ValueError(f"--where key {key!r} is not a dim; available dims: {sorted(dims)}")
        mask = df[key].astype(str) == str(val)
        try:
            numeric_val = float(val)
        except ValueError:
            pass  # non-numeric value → string match only
        else:
            mask = mask | (pd.to_numeric(df[key], errors="coerce") == numeric_val)
        df = df[mask]
    if df.empty:
        raise ValueError(f"no rows match --where {dict(where)}")
    return df


def _free_facet_axes(fig: Figure, *, faceted: bool, free_axes: FreeAxes | None) -> None:
    """Give chosen facet axes their own auto-range + ticks (vs plotly's shared default).

    No-op unless the view is faceted and ``free_axes`` is set. Matched axes are the
    default — good when facets are commensurable. The two cases where matching hurts
    want *different* axes freed: incommensurable sweeps (``"x"`` — the x dims differ)
    and facets whose *cost* scales differ (``"y"`` — e.g. one panel per function,
    where a shared y flattens the cheap panels). ``"both"`` frees each independently.
    """
    if not (faceted and free_axes):
        return
    if free_axes in ("x", "both"):
        fig.update_xaxes(matches=None, showticklabels=True)
    if free_axes in ("y", "both"):
        fig.update_yaxes(matches=None, showticklabels=True)


def plot_compare(
    snapshots: Snapshots,
    *,
    metric: Metric = "time",
    sort: SortMode = "absolute",
    facet: str | None = None,
    clip: float | None = None,
    where: Mapping[str, str] | None = None,
    free_axes: FreeAxes | None = None,
    labels: Sequence[str] | None = None,
    pivot: str | None = None,
) -> tuple[Figure, int]:
    """Bar chart of per-id delta, sorted by the chosen Δ (biggest regressions on top).

    The first two series are compared; the first is the baseline. The series axis is the
    run-file by default (the first two files); ``pivot`` re-points it at a data dim, folding a
    single run so its first two dim-values become the A and B series instead (see
    :func:`load_long_df`).

    Args:
        snapshots: Run JSON path(s); only the first two are used (one run when ``pivot`` is set).
        metric: Which metric to plot (``time`` / ``peak`` / ``allocated`` / ``allocations``).
        sort: ``absolute`` plots ``b - a`` in the native unit; ``relative`` plots percent change.
        facet: Dim to split into subplots.
        clip: Clamp the colour scale (default symmetric p95).
        where: Keep only rows matching these ``dim=value`` pairs.
        free_axes: Give each facet its own axes instead of sharing.
        labels: Series names for the two runs (default: file stems). Ignored when ``pivot`` is set
            (the series are the dim's values).
        pivot: Use this dim as the series axis instead of the run-file (``param:NAME`` or a bare
            ``extra_info`` name); requires a single run.

    Returns:
        ``(figure, n_ids)`` — the plotly figure and the number of ids plotted.
    """
    import sys

    import plotly.express as px

    snapshots = _as_paths(snapshots)
    df_long, unit = load_long_df(
        snapshots[:2], metric=metric, labels=_labels_head(labels, 2), pivot=pivot
    )
    df_long = _apply_where(df_long, where)
    vlabel = _metric_label(metric)
    labels = df_long["snapshot"].drop_duplicates().tolist()
    if len(labels) < 2:
        if pivot:
            raise ValueError(
                f"compare --pivot needs two distinct values of {pivot!r} to pair; got only "
                f"{labels[0]!r}. Does the run vary {pivot!r}?"
            )
        raise ValueError(
            f"compare needs two distinct snapshots; both resolve to {labels[0]!r} "
            f"(the same file given twice?). Pass two different files, or labels=."
        )
    a_label, b_label = labels[0], labels[1]

    dims = _carry_dims(df_long)  # carry node.* too, so an explicit node facet survives
    wide = (
        df_long.pivot(index=["id", *dims], columns="snapshot", values="value")
        .reset_index()
        .rename_axis(columns=None)
    )
    only_a = wide[wide[a_label].notna() & wide[b_label].isna()]
    only_b = wide[wide[a_label].isna() & wide[b_label].notna()]
    df = wide.dropna(subset=[a_label, b_label]).copy()
    if df.empty:
        raise ValueError("no ids in common between the two snapshots")
    if len(only_a) or len(only_b):
        print(
            f"compare: {len(only_a)} only in {a_label}, {len(only_b)} only in "
            f"{b_label} (intersection: {len(df)}).",
            file=sys.stderr,
        )

    df["delta_abs"] = df[b_label] - df[a_label]
    df["delta_pct"] = (df["delta_abs"] / df[a_label]) * 100.0
    x_col = "delta_abs" if sort == "absolute" else "delta_pct"
    df = df.sort_values(x_col).reset_index(drop=True)

    x_label = f"Δ {vlabel}{_unit_note(unit)}" if sort == "absolute" else f"Δ {vlabel} (%)"
    text_fmt = (".2s" if unit in ("s", "B") else ".2f") if sort == "absolute" else ".1f"
    direction = "slower" if unit == "s" else "more memory"
    title = f"{vlabel} change ({sort}): {a_label} → {b_label} — positive = {direction}"

    facet_kwargs: dict[str, object] = {}
    if facet is not None and facet in df.columns:
        facet_kwargs = {"facet_col": facet, "facet_col_wrap": 3}

    color_clip = _symmetric_clip(df[x_col].to_numpy(), clip)
    fig = px.bar(
        df,
        x=x_col,
        y="id",
        orientation="h",
        color=x_col,
        **_diverging_kwargs(),
        range_color=[-color_clip, color_clip],
        title=title,
        labels={x_col: x_label, "id": ""},
        text_auto=text_fmt,
        **facet_kwargs,
    )
    if sort == "absolute":
        fig.update_xaxes(**_axis_kwargs(unit))
    _free_facet_axes(fig, faceted=bool(facet_kwargs), free_axes=free_axes)
    fig.update_traces(textposition="outside", cliponaxis=False)
    # The bar's x-position already encodes the delta, so the colour scale is redundant — hide the
    # colourbar (the green→red fill still reads as improvement→regression) to declutter.
    fig.update_layout(height=max(500, len(df) * 22), showlegend=False, coloraxis_showscale=False)
    return fig, len(df)


def _drop_baseline_series(df: pd.DataFrame, baseline_label: str) -> pd.DataFrame:
    """Drop the baseline series' own rows from a *static* candidate-vs-baseline scatter.

    The baseline compared against itself is ``ratio == 1.0`` — a redundant dot per id overplotting
    the dashed ``y=1.0`` reference line (the "two dots per id" in a 2-series A/B); the hline
    already conveys it. Only for the non-animated view: in the animated 3+ sweep the baseline is
    its own frame, not overplotted, and is kept as the t0 "all at parity" anchor the eye starts
    from. Keys on the canonical ``snapshot`` series column; returns only the candidate rows.
    """
    return df[df["snapshot"] != baseline_label]


def plot_scatter(
    snapshots: Snapshots,
    *,
    metric: Metric = "time",
    facet: str | None = None,
    clip: float | None = None,
    where: Mapping[str, str] | None = None,
    free_axes: FreeAxes | None = None,
    labels: Sequence[str] | None = None,
    pivot: str | None = None,
) -> tuple[Figure, int]:
    """Baseline cost (log-x) vs candidate/baseline ratio (log-y).

    Top-right = slow *and* slower (the regressed corner). The first series is the baseline;
    with 3+, the rest animate. Colour encodes the absolute Δ. The series axis is the run-file
    by default; ``pivot`` re-points it at a data dim, folding a single run so its dim-values are
    the series (the first being the baseline) instead of the files (see :func:`load_long_df`).

    Args:
        snapshots: Run JSON path(s); the first is the baseline, extras animate (one run when
            ``pivot`` is set — the dim's values play that role).
        metric: Which metric to plot (``time`` / ``peak`` / ``allocated`` / ``allocations``).
        facet: Dim to split into subplots.
        clip: Clamp the colour scale (default p95).
        where: Keep only rows matching these ``dim=value`` pairs.
        free_axes: Give each facet its own axes instead of sharing.
        labels: Series names per run (default: file stems). Ignored when ``pivot`` is set.
        pivot: Use this dim as the series axis instead of the run-file (``param:NAME`` or a bare
            ``extra_info`` name); requires a single run.

    Returns:
        ``(figure, n_ids)`` — the plotly figure and the number of ids plotted.
    """
    import plotly.express as px

    snapshots = _as_paths(snapshots)
    if pivot is None and len(snapshots) < 2:
        raise ValueError("scatter needs at least 2 snapshots (baseline + 1), or --pivot a dim")

    df_long, unit = load_long_df(snapshots, metric=metric, labels=labels, pivot=pivot)
    df_long = _apply_where(df_long, where)
    vlabel = _metric_label(metric)
    labels = df_long["snapshot"].drop_duplicates().tolist()
    baseline_label = labels[0]

    base = df_long.loc[df_long["snapshot"] == baseline_label, ["id", "value"]].rename(
        columns={"value": "baseline"}
    )
    df = df_long.merge(base, on="id", how="inner")
    df = df[df["baseline"] > 0].copy()
    if df.empty:
        raise ValueError(f"no ids shared with baseline ({baseline_label})")
    animate = len(snapshots) >= 3  # noqa: PLR2004 — 3+ series animate; the baseline is the t0 frame
    if not animate:
        df = _drop_baseline_series(df, baseline_label)
        if df.empty:
            raise ValueError(f"only the baseline series ({baseline_label}); nothing to compare to")

    df["ratio"] = df["value"] / df["baseline"]
    df["delta_abs"] = df["value"] - df["baseline"]
    df = df[df["ratio"] > 0]
    y_lo, y_hi = df["ratio"].min(), df["ratio"].max()
    bound = max(y_hi, 1.0 / y_lo, 1.1) ** 1.05
    color_clip = _symmetric_clip(df["delta_abs"].to_numpy(), clip)

    extra: dict[str, object] = {}
    if animate:
        extra["animation_frame"] = "snapshot"
        extra["category_orders"] = {"snapshot": labels}
    if facet is not None and facet in df.columns:
        extra["facet_col"] = facet
        extra["facet_col_wrap"] = 3

    fig = px.scatter(
        df,
        x="baseline",
        y="ratio",
        color="delta_abs",
        **_diverging_kwargs(),
        range_color=[-color_clip, color_clip],
        log_x=True,
        log_y=True,
        range_y=[1.0 / bound, bound],
        hover_name="id",
        title=f"{vlabel}: candidate vs baseline ({baseline_label}) — top-right = regressed",
        labels={
            "baseline": f"baseline {vlabel}{_unit_note(unit)}, log",
            "ratio": "ratio: candidate / baseline (log)",
            "delta_abs": f"Δ {vlabel}{_unit_note(unit)}",  # colourbar (else the raw column name)
        },
        **extra,
    )
    fig.add_hline(y=1.0, line_dash="dash", line_color="grey")
    _free_facet_axes(fig, faceted="facet_col" in extra, free_axes=free_axes)
    fig.update_traces(marker={"size": 8, "line": {"width": 0.5, "color": "DarkSlateGrey"}})
    fig.update_layout(height=600)
    return fig, int(df["id"].nunique())


def plot_sweep(
    snapshots: Snapshots,
    *,
    metric: Metric = "time",
    clip: float | None = None,
    where: Mapping[str, str] | None = None,
    labels: Sequence[str] | None = None,
) -> tuple[Figure, int]:
    """Heatmap of per-id fold-change (log2 ratio) vs the first snapshot.

    Args:
        snapshots: Run JSON paths; columns in order, the first is the reference.
        metric: Which metric to plot (``time`` / ``peak`` / ``allocated`` / ``allocations``).
        clip: Clamp the colour scale.
        where: Keep only rows matching these ``dim=value`` pairs.
        labels: Column (version) names (default: file stems).

    Returns:
        ``(figure, n_ids)`` — the plotly figure and the number of ids plotted.
    """
    import plotly.express as px

    df_long, unit = load_long_df(snapshots, metric=metric, labels=labels)
    df_long = _apply_where(df_long, where)
    vlabel = _metric_label(metric)
    versions = df_long["snapshot"].drop_duplicates().tolist()
    baseline = versions[0]

    abs_df = df_long.pivot(index="id", columns="snapshot", values="value").reindex(columns=versions)
    abs_df = abs_df.dropna(subset=[baseline])
    if abs_df.empty:
        raise ValueError(f"no overlap with baseline snapshot {baseline}")
    ratio = abs_df.div(abs_df[baseline], axis=0)
    logr = np.log2(ratio.where(ratio > 0))
    abs_df.index.name = ratio.index.name = logr.index.name = "id"

    bound = _symmetric_clip(logr.values, float(np.log2(clip)) if clip else None)
    fig = px.imshow(
        logr,
        color_continuous_scale=["green", "white", "red"],
        color_continuous_midpoint=0.0,
        zmin=-bound,
        zmax=bound,
        aspect="auto",
        title=f"{vlabel} fold-change vs baseline ({baseline})",
        labels={"x": "snapshot", "y": "id", "color": "fold"},
    )
    tickvals, ticktext = _fold_ticks(bound)
    fig.update_coloraxes(colorbar={"tickvals": tickvals, "ticktext": ticktext, "title": "fold"})
    fig.update_traces(
        text=ratio.round(2).values,
        texttemplate="%{text}×",
        customdata=abs_df.values,
        hovertemplate=(
            "id: %{y}<br>snapshot: %{x}<br>fold: %{text}×<br>"
            f"{vlabel}: %{{customdata:.4g}}{unit}<extra></extra>"
        ),
    )
    fig.update_layout(height=max(500, len(logr) * 22))
    return fig, len(logr)


def _infer_roles(
    df: pd.DataFrame,
    x: str | None,
    color: str | None,
    facet: str | None,
    *,
    series: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Pick (x, color, facet) dim columns, auto-filling unset ones.

    x defaults to the lone *numeric* dim; color/facet to leftover categoricals. When
    ``series`` is set (the run-file axis, for multi-run overlays), an unset ``color``
    defaults to it so the runs separate into their own lines — matching ``compare``.
    """
    dims = _dim_columns(df)
    numeric = [d for d in dims if df[d].dropna().map(lambda v: isinstance(v, (int, float))).all()]
    if x is None:
        if len(numeric) != 1:
            raise ValueError(
                "scaling needs exactly one numeric dim for the x-axis "
                f"(found {numeric or 'none'}); pass --x DIM to pick one. To A/B a "
                "categorical dim instead, use --pivot DIM (one run) or pass two runs."
            )
        x = numeric[0]
    leftover = [d for d in dims if d != x]
    if color is None:
        color = series if series is not None else (leftover[0] if leftover else None)
    if facet is None:
        facet = next((d for d in leftover if d != color), None)
    return x, color, facet


def _envelope_by_id(
    snapshots: Sequence[Path], metric: Metric, labels: Sequence[str] | None
) -> tuple[pd.Series, pd.Series]:
    """Per-(run, id) ``(min, max)`` of the metric's per-pass series — the spread envelope.

    Reads the runs twice through the ``min`` / ``max`` stat reducers; benchmarks
    measured once collapse to ``min == max`` (no spread, so no band). Keyed by
    ``(snapshot, id)`` so overlaid runs sharing an id keep their own envelopes.
    """

    def keyed(df: pd.DataFrame) -> pd.Series:
        """Value series indexed by the ``(snapshot, id)`` pair for reindex-based lookup."""
        return df.set_index(["snapshot", "id"])["value"]

    lo_df, _ = load_long_df(snapshots, metric=metric, stat="min", labels=labels)
    hi_df, _ = load_long_df(snapshots, metric=metric, stat="max", labels=labels)
    return keyed(lo_df), keyed(hi_df)


def _positive_numeric(values: pd.Series) -> bool:
    """True when every value is numeric and strictly positive — safe to log-scale."""
    import pandas as pd

    nums = pd.to_numeric(values, errors="coerce")
    return bool(nums.notna().all() and (nums > 0).all())


def plot_scaling(
    snapshots: Snapshots,
    *,
    metric: Metric = "time",
    x: str | None = None,
    color: str | None = None,
    facet: str | None = None,
    log_log: bool | None = None,
    log_x: bool | Literal["auto"] = "auto",
    log_y: bool | Literal["auto"] = "auto",
    y_zero: bool | Literal["auto"] = "auto",
    band: Literal["auto", "minmax", "none"] = "auto",
    where: Mapping[str, str] | None = None,
    free_axes: FreeAxes | None = None,
    labels: Sequence[str] | None = None,
    log: bool | Literal["auto"] | None = None,
) -> tuple[Figure, int]:
    """Cost vs a numeric dim, coloured/faceted by other dims.

    ``x``/``color``/``facet`` default to inference from the dims (the lone numeric
    dim → x); pass them to override. Passing more than one run overlays them as
    series — the run-file becomes the default ``color`` (like :func:`plot_compare`),
    so two builds' scaling curves sit on the same axes per facet.

    Axis scaling resolves per axis as ``log_x``/``log_y`` (if set) → ``log_log`` (the
    shared shortcut, if set) → ``"auto"`` (log when that axis's data is strictly positive,
    i.e. log-log by default).

    Args:
        snapshots: Run JSON path(s). Multiple runs overlay as series (default
            ``color`` = run label).
        metric: Which metric to plot (``time`` / ``peak`` / ``allocated`` / ``allocations``).
        x: Dim for the x-axis (default: the lone numeric dim).
        color: Dim to colour by (default: inferred).
        facet: Dim to split into subplots (default: inferred).
        log_log: Shared shortcut — ``True`` log-scales both axes, ``False`` forces both
            linear, ``None`` (default) leaves each axis on its own ``"auto"``. Overridden
            per axis by ``log_x``/``log_y``.
        log_x: ``"auto"`` log-scales x when it's numeric and strictly positive (the sweep
            decades); or force with a bool. Wins over ``log_log``.
        log_y: ``"auto"`` log-scales y when the metric is strictly positive (log-log is the
            default); pass ``False`` for a linear cost axis where bar heights read truthfully.
            Wins over ``log_log``; independent of ``log_x``.
        y_zero: Anchor the linear y-axis at 0 so the between-run gap and the scaling slope
            aren't visually exaggerated. ``"auto"`` does this whenever the y-axis is linear
            (the only case where it applies); force with a bool.
        band: Spread whiskers (``min``…``max`` of each point's per-pass series) on memory
            metrics — ``"auto"`` shows them where there's spread, ``"minmax"`` forces them on,
            ``"none"`` off. The line stays the headline (the min floor); whiskers reach up to
            the worst pass. Ignored for ``time``.
        where: Keep only rows matching these ``dim=value`` pairs.
        free_axes: ``"x"`` / ``"y"`` / ``"both"`` — unmatch a faceted axis from the shared
            default (``"x"`` for incommensurable sweeps, ``"y"`` when facets have different
            cost scales, e.g. per function).
        labels: Names the snapshot in the title (default: file stem).
        log: Deprecated alias for ``log_log`` (tied both axes together). Pass ``log_log`` or
            the per-axis ``log_x``/``log_y`` instead.

    Returns:
        ``(figure, n_ids)`` — the plotly figure and the number of ids plotted.
    """
    import pandas as pd
    import plotly.express as px

    if log is not None:
        import warnings

        warnings.warn(
            "plot_scaling(log=...) is deprecated; use log_log= (both axes) or "
            "log_x=/log_y= (per axis).",
            FutureWarning,
            stacklevel=2,
        )
        if log_log is None:
            log_log = None if log == "auto" else bool(log)

    snapshots = _as_paths(snapshots)
    df_long, unit = load_long_df(snapshots, metric=metric, labels=labels)
    df_long = _apply_where(df_long, where)
    vlabel = _metric_label(metric)
    snap_label = ", ".join(dict.fromkeys(df_long["snapshot"]))
    series = "snapshot" if len(snapshots) > 1 else None
    x, color, facet = _infer_roles(df_long, x, color, facet, series=series)
    df = df_long.dropna(subset=[x]).sort_values([c for c in ("snapshot", facet, color, x) if c])
    if df.empty:
        raise ValueError("no rows with the x dim set")

    err: dict[str, str] = {}
    if band != "none" and metric != "time":
        lo_by_key, hi_by_key = _envelope_by_id(snapshots, metric, labels)
        idx = pd.MultiIndex.from_frame(df[["snapshot", "id"]])
        hi = hi_by_key.reindex(idx).to_numpy()
        lo = lo_by_key.reindex(idx).to_numpy()
        df = df.assign(
            _err_hi=(hi - df["value"]).clip(lower=0).fillna(0.0),
            _err_lo=(df["value"] - lo).clip(lower=0).fillna(0.0),
        )
        if band == "minmax" or bool(((df["_err_hi"] + df["_err_lo"]) > 0).any()):
            err = {"error_y": "_err_hi", "error_y_minus": "_err_lo"}

    # Keep overlaid runs as distinct lines even when colour is spent on a dim: dash by run
    # so px.line doesn't chain one run's points into the next under a shared colour.
    line_dash = series if series is not None and series not in (color, facet) else None

    # Per-axis (if set) wins over the shared log_log, which wins over per-axis-data auto.
    def _resolve_log(axis: bool | Literal["auto"], data: pd.Series) -> bool:
        if axis != "auto":
            return bool(axis)
        return log_log if log_log is not None else _positive_numeric(data)

    use_log_x = _resolve_log(log_x, df[x])
    use_log_y = _resolve_log(log_y, df["value"])
    fig = px.line(
        df,
        x=x,
        y="value",
        color=color,
        line_dash=line_dash,
        facet_col=facet,
        facet_col_wrap=3 if facet else None,
        log_x=use_log_x,
        log_y=use_log_y,
        markers=True,
        labels={"value": f"{vlabel}{_unit_note(unit)}", x: x},
        title=f"Scaling: {vlabel} vs {x} ({snap_label})",
        **err,
    )
    # A linear y that floats above 0 exaggerates both the between-run gap and the slope; anchor
    # it at 0. Meaningless on a log axis (no zero), so auto only fires when the y-axis is linear.
    anchor_zero = (not use_log_y) if y_zero == "auto" else bool(y_zero)
    if anchor_zero and not use_log_y:
        fig.update_yaxes(rangemode="tozero")
    _free_facet_axes(fig, faceted=facet is not None, free_axes=free_axes)
    n_facets = df[facet].nunique() if facet else 1
    fig.update_layout(height=max(400, ((n_facets + 2) // 3) * 350))
    return fig, len(df)
