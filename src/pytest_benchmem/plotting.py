"""Interactive plotly views over pytest-benchmark runs — dims-driven.

Each view reads one ``metric`` (``time`` / ``peak`` / ``allocated`` /
``allocations``) out of the pytest-benchmark JSON files and returns
``(figure, n_rendered)``:

- :func:`plot_compare` (2 runs) — bar chart of per-id delta.
- :func:`plot_scatter` (2+) — baseline cost vs ratio; top-right = the regressed one.
- :func:`plot_sweep` (3+) — heatmap of per-id fold-change (log2 ratio) vs the first.
- :func:`plot_scaling` (1) — cost vs a numeric dim, faceted/coloured by others.

The sweep/scatter/compare views key on the opaque ``id``; only ``scaling`` reads
``dims`` — and which dim is x / colour / facet is auto-inferred from dtype
(numeric → x) but overridable. plotly is imported lazily.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np

from pytest_benchmem.snapshot import (
    NODE_DIM_PREFIX,
    RESERVED_COLUMNS,
    Metric,
    _as_paths,
    _canonical_metric,
    load_long_df,
)

if TYPE_CHECKING:
    import numpy.typing as npt
    import pandas as pd
    from plotly.graph_objects import Figure

SortMode = Literal["absolute", "relative"]

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


def plot_compare(
    snapshots: Snapshots,
    *,
    metric: Metric = "time",
    sort: SortMode = "absolute",
    facet: str | None = None,
    clip: float | None = None,
    labels: Sequence[str] | None = None,
) -> tuple[Figure, int]:
    """Bar chart of per-id delta, sorted by the chosen Δ (biggest regressions on top).

    ``sort`` picks the bar dimension: ``absolute`` plots ``b - a`` in the native
    unit, ``relative`` plots percent change. ``facet`` splits into subplots by any
    dim. ``clip`` clamps the colour scale (default symmetric p95). ``labels`` names
    the two series (defaults to the file stems).
    """
    import sys

    import plotly.express as px

    snapshots = _as_paths(snapshots)
    df_long, unit = load_long_df(snapshots[:2], metric=metric, labels=_labels_head(labels, 2))
    vlabel = _canonical_metric(metric)
    labels = df_long["snapshot"].drop_duplicates().tolist()
    if len(labels) < 2:
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

    x_label = f"{vlabel} delta ({unit})" if sort == "absolute" else f"{vlabel} delta %"
    text_fmt = (".2s" if unit in ("s", "B") else ".2f") if sort == "absolute" else ".1f"
    direction = "slower" if unit == "s" else "more memory"
    title = f"{vlabel} delta ({sort}): {a_label} → {b_label} (positive = {direction})"

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
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(height=max(500, len(df) * 22), showlegend=False)
    return fig, len(df)


def plot_scatter(
    snapshots: Snapshots,
    *,
    metric: Metric = "time",
    facet: str | None = None,
    clip: float | None = None,
    labels: Sequence[str] | None = None,
) -> tuple[Figure, int]:
    """Baseline cost (log-x) vs candidate/baseline ratio (log-y).

    Top-right = slow *and* slower (the regressed corner). The first snapshot is
    the baseline; with 3+, the rest animate. Colour encodes absolute Δ; ``clip``
    clamps it (default p95). ``facet`` splits by any dim. ``labels`` names the
    snapshots (defaults to the file stems).
    """
    import plotly.express as px

    snapshots = _as_paths(snapshots)
    if len(snapshots) < 2:
        raise ValueError("scatter needs at least 2 snapshots (baseline + 1)")

    df_long, unit = load_long_df(snapshots, metric=metric, labels=labels)
    vlabel = _canonical_metric(metric)
    labels = df_long["snapshot"].drop_duplicates().tolist()
    baseline_label = labels[0]

    base = df_long.loc[df_long["snapshot"] == baseline_label, ["id", "value"]].rename(
        columns={"value": "baseline"}
    )
    df = df_long.merge(base, on="id", how="inner")
    df = df[df["baseline"] > 0].copy()
    if df.empty:
        raise ValueError(f"no ids shared with baseline ({baseline_label})")

    df = df.rename(columns={"snapshot": "version", "value": "candidate"})
    df["ratio"] = df["candidate"] / df["baseline"]
    df["delta_abs"] = df["candidate"] - df["baseline"]
    df = df[df["ratio"] > 0]
    y_lo, y_hi = df["ratio"].min(), df["ratio"].max()
    bound = max(y_hi, 1.0 / y_lo, 1.1) ** 1.05
    color_clip = _symmetric_clip(df["delta_abs"].to_numpy(), clip)

    extra: dict[str, object] = {}
    if len(snapshots) >= 3:
        extra["animation_frame"] = "version"
        extra["category_orders"] = {"version": labels}
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
        title=f"{vlabel} scatter vs baseline ({baseline_label}) — top-right = regressed",
        labels={
            "baseline": f"baseline {vlabel} ({unit}, log)",
            "ratio": "ratio (candidate / baseline, log)",
        },
        **extra,
    )
    fig.add_hline(y=1.0, line_dash="dash", line_color="grey")
    fig.update_traces(marker={"size": 8, "line": {"width": 0.5, "color": "DarkSlateGrey"}})
    fig.update_layout(height=600)
    return fig, int(df["id"].nunique())


def plot_sweep(
    snapshots: Snapshots,
    *,
    metric: Metric = "time",
    clip: float | None = None,
    labels: Sequence[str] | None = None,
) -> tuple[Figure, int]:
    """Heatmap of per-id fold-change (log2 ratio) vs the first snapshot.

    ``labels`` names the version columns (defaults to the file stems).
    """
    import plotly.express as px

    df_long, unit = load_long_df(snapshots, metric=metric, labels=labels)
    vlabel = _canonical_metric(metric)
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
    df: pd.DataFrame, x: str | None, color: str | None, facet: str | None
) -> tuple[str, str | None, str | None]:
    """Pick (x, color, facet) dim columns, auto-filling unset ones.

    x defaults to the lone *numeric* dim; color/facet to leftover categoricals.
    """
    dims = _dim_columns(df)
    numeric = [d for d in dims if df[d].dropna().map(lambda v: isinstance(v, (int, float))).all()]
    if x is None:
        if len(numeric) != 1:
            raise ValueError(
                f"scaling needs exactly one numeric dim for x (found {numeric}); pass x= explicitly"
            )
        x = numeric[0]
    leftover = [d for d in dims if d != x]
    if color is None:
        color = leftover[0] if leftover else None
    if facet is None:
        facet = next((d for d in leftover if d != color), None)
    return x, color, facet


def plot_scaling(
    snapshots: Snapshots,
    *,
    metric: Metric = "time",
    x: str | None = None,
    color: str | None = None,
    facet: str | None = None,
    log: bool | Literal["auto"] = "auto",
    labels: Sequence[str] | None = None,
) -> tuple[Figure, int]:
    """Cost vs a numeric dim, coloured/faceted by other dims.

    ``x``/``color``/``facet`` default to inference from the dims (the lone numeric
    dim → x); pass them to override. ``log="auto"`` log-scales when x is numeric
    and strictly positive. ``labels`` names the snapshot in the title (defaults to
    the file stem).
    """
    import plotly.express as px

    snapshots = _as_paths(snapshots)
    head = _labels_head(labels, 1)
    snap_label = head[0] if head else snapshots[0].stem
    df_long, unit = load_long_df(snapshots[:1], metric=metric, labels=head)
    vlabel = _canonical_metric(metric)
    x, color, facet = _infer_roles(df_long, x, color, facet)
    df = df_long.dropna(subset=[x]).sort_values([c for c in (facet, color, x) if c])
    if df.empty:
        raise ValueError("no rows with the x dim set")

    use_log = bool((df[x] > 0).all()) if log == "auto" else bool(log)
    fig = px.line(
        df,
        x=x,
        y="value",
        color=color,
        facet_col=facet,
        facet_col_wrap=3 if facet else None,
        log_x=use_log,
        log_y=use_log,
        markers=True,
        labels={"value": f"{vlabel} ({unit})", x: x},
        title=f"Scaling: {vlabel} ({unit}) vs {x} ({snap_label})",
    )
    n_facets = df[facet].nunique() if facet else 1
    fig.update_layout(height=max(400, ((n_facets + 2) // 3) * 350))
    return fig, len(df)
