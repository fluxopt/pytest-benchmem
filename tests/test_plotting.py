"""Figure-structure assertions for the plot_* views — no pixels, just shape."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("pandas")
pytest.importorskip("plotly")

from pytest_benchmem import plotting
from pytest_benchmem.snapshot import load_long_df


def _run(path, rows, *, memory=False):
    """Write a pytest-benchmark run; rows is [(n, value)] with n a numeric dim."""
    benchmarks = []
    for n, v in rows:
        bm = {"fullname": f"test_op[n={n}]", "stats": {"min": v}, "params": {"n": n}}
        if memory:
            peak = int(v * 1024**2)
            bm["extra_info"] = {
                "benchmem": {"peak_bytes": [peak], "allocations": [int(n)], "total_bytes": [peak]}
            }
        benchmarks.append(bm)
    path.write_text(json.dumps({"benchmarks": benchmarks}))
    return path


ROWS_A = [(10, 1.0), (100, 2.0), (1000, 4.0)]
ROWS_B = [(10, 1.1), (100, 1.8), (1000, 5.0)]


def _run_two_funcs(path):
    """A run with two operations (``::``-qualified funcs) over a shared numeric dim n."""
    benchmarks = [
        {"fullname": f"bench/test_ops.py::{func}[n={n}]", "stats": {"min": v}, "params": {"n": n}}
        for func in ("build", "solve")
        for n, v in [(10, 1.0), (100, 2.0)]
    ]
    path.write_text(json.dumps({"benchmarks": benchmarks}))
    return path


def test_scaling_one_run(tmp_path):
    fig, n = plotting.plot_scaling([_run(tmp_path / "a.json", ROWS_A)])
    assert n == 3  # one point per id
    assert fig.layout.title.text  # titled
    assert len(fig.data) >= 1


def test_compare_two_runs_counts_common_ids(tmp_path):
    a = _run(tmp_path / "a.json", ROWS_A)
    b = _run(tmp_path / "b.json", ROWS_B)
    fig, n = plotting.plot_compare([a, b])
    assert n == 3  # all three ids shared
    assert fig.layout.title.text


def test_compare_same_file_twice_errors_cleanly(tmp_path):
    a = _run(tmp_path / "a.json", ROWS_A)
    with pytest.raises(ValueError, match="two distinct snapshots"):
        plotting.plot_compare([a, a])


def test_compare_labels_override_stem(tmp_path):
    a = _run(tmp_path / "aaa.json", ROWS_A)
    b = _run(tmp_path / "bbb.json", ROWS_B)
    fig, _n = plotting.plot_compare([a, b], labels=["base", "head"])
    assert "base → head" in fig.layout.title.text  # not "aaa → bbb"


def test_sweep_labels_override_stem(tmp_path):
    runs = [_run(tmp_path / f"{i}.json", ROWS_A) for i in range(3)]
    fig, _n = plotting.plot_sweep(runs, labels=["0.6.7", "0.7.0", "0.8.0"])
    assert "0.6.7" in fig.layout.title.text  # baseline = first label, not "0"


def test_scatter_two_runs(tmp_path):
    a = _run(tmp_path / "a.json", ROWS_A)
    b = _run(tmp_path / "b.json", ROWS_B)
    fig, n = plotting.plot_scatter([a, b])
    assert n == 3  # unique ids


def test_scatter_drops_redundant_baseline_points(tmp_path):
    # the baseline series compared against itself is ratio 1.0 — it must not be drawn (it would
    # double the dots per id and clutter the y=1.0 line); the hline conveys the baseline. (#139)
    a = _run(tmp_path / "a.json", ROWS_A)
    b = _run(tmp_path / "b.json", ROWS_B)
    fig, n = plotting.plot_scatter([a, b])
    plotted = sum(len(t.y) for t in fig.data if getattr(t, "y", None) is not None)
    assert plotted == n == 3  # one point per id (candidate only), not 6 (baseline dropped)


def test_scatter_animation_keeps_baseline_frame(tmp_path):
    # 3+ runs animate: the baseline is its own t0 frame (points at parity), not overplotted — it's
    # kept as the reference frame, unlike the static-A/B baseline points dropped above. (#139)
    runs = [_run(tmp_path / f"{i}.json", ROWS_A) for i in range(3)]
    fig, _n = plotting.plot_scatter(runs)
    assert "0" in {f.name for f in fig.frames}  # baseline ('0') is the first animation frame


def test_sweep_three_runs(tmp_path):
    runs = [_run(tmp_path / f"{i}.json", ROWS_A) for i in range(3)]
    fig, n = plotting.plot_sweep(runs)
    assert n == 3  # heatmap rows = ids
    assert fig.layout.title.text


def test_plot_accepts_str_and_single_path(tmp_path):
    p = _run(tmp_path / "a.json", ROWS_A)
    fig_single, n_single = plotting.plot_scaling(p)  # single Path, not a list
    fig_str, n_str = plotting.plot_scaling(str(p))  # str path (previously .stem crash)
    assert n_single == n_str == 3
    assert p.stem in fig_str.layout.title.text


def test_metric_memory_unit_in_title(tmp_path):
    a = _run(tmp_path / "a.json", ROWS_A, memory=True)
    fig, _n = plotting.plot_scaling([a], metric="peak")
    assert "peak" in fig.layout.title.text.lower()  # vlabel for MiB is "peak"


def test_scaling_axis_uses_friendly_label_and_spelled_unit(tmp_path):
    a = _run(tmp_path / "a.json", ROWS_A, memory=True)
    fig, _n = plotting.plot_scaling([a], metric="peak")
    assert fig.layout.yaxis.title.text == "peak memory (bytes)"  # not "peak (B)"


def test_scatter_colourbar_is_labelled_not_raw_column(tmp_path):
    # regression: the colourbar used to read the raw frame column "delta_abs"
    a = _run(tmp_path / "a.json", ROWS_A, memory=True)
    b = _run(tmp_path / "b.json", ROWS_B, memory=True)
    fig, _n = plotting.plot_scatter([a, b], metric="peak")
    cbar = fig.layout.coloraxis.colorbar.title.text
    assert cbar == "Δ peak memory (bytes)" and "delta_abs" not in cbar


def test_compare_hides_redundant_colourbar(tmp_path):
    # the bar x-position already encodes the delta, so the colour scale is hidden
    a = _run(tmp_path / "a.json", ROWS_A, memory=True)
    b = _run(tmp_path / "b.json", ROWS_B, memory=True)
    fig, _n = plotting.plot_compare([a, b], metric="peak")
    assert fig.layout.coloraxis.showscale is False


def test_count_metric_omits_unit_note(tmp_path):
    # allocations is a count — no "(bytes)"/"(seconds)" note on the baseline axis
    a, b = (
        _run(tmp_path / "a.json", ROWS_A, memory=True),
        _run(tmp_path / "b.json", ROWS_B, memory=True),
    )
    fig, _n = plotting.plot_scatter([a, b], metric="allocations")
    assert fig.layout.xaxis.title.text == "baseline allocations, log"


def test_node_dims_carried_but_not_auto_inferred(tmp_path):
    df, _u = load_long_df(_run_two_funcs(tmp_path / "a.json"))
    assert "node.func" in plotting._carry_dims(df)  # available for explicit use
    assert "node.func" not in plotting._dim_columns(df)  # never auto-picked
    assert "n" in plotting._dim_columns(df)  # the real param still auto-inferable


# --- --pivot: the series axis is a dim, not just the run-file ------------------------


def _combined_run(path):
    """One run where ``semantics`` is a param in the id (test_build[legacy-100]) and a dim —
    the combined-run shape ``--pivot`` targets (one pytest invocation, A/B encoded in the id).
    """
    cells = [("legacy", 100, 10.0), ("v1", 100, 12.0), ("legacy", 200, 20.0), ("v1", 200, 30.0)]

    def _blob(peak):
        return {"peak_bytes": [int(peak * 1024**2)], "allocations": [0], "total_bytes": [0]}

    benchmarks = [
        {
            "fullname": f"m.py::test_build[{sem}-{n}]",
            "params": {"semantics": sem, "n": n},
            "stats": {"min": 1.0},
            "extra_info": {"benchmem": _blob(peak)},
        }
        for sem, n, peak in cells
    ]
    path.write_text(json.dumps({"benchmarks": benchmarks}))
    return path


def test_compare_pivot_pairs_along_dim_within_one_run(tmp_path):
    # --view compare on a single run, folded along semantics: pairs legacy↔v1 per (id, n),
    # the A/B a two-file compare gives — without splitting into two runs.
    run = _combined_run(tmp_path / "build.json")
    fig, n = plotting.plot_compare([run], metric="peak", pivot="param:semantics")
    assert n == 2  # two folded rows: n=100 and n=200 (semantics lifted out of the id)
    assert "legacy → v1" in fig.layout.title.text  # series = the dim's values, not file stems


def test_scatter_pivot_accepts_single_run(tmp_path):
    # scatter's "needs 2 snapshots" rule is waived under --pivot: the series come from the dim.
    run = _combined_run(tmp_path / "build.json")
    fig, n = plotting.plot_scatter([run], metric="peak", pivot="param:semantics")
    assert n == 2  # ids paired against the legacy baseline


def test_one_run_drives_both_table_and_compare_plot(tmp_path):
    # the headline acceptance: a single combined run feeds the A/B table and the A/B plot,
    # both folded along the same dim — no file-splitting, no env-var reruns.
    from io import StringIO

    from pytest_benchmem.compare import compare_runs

    run = _combined_run(tmp_path / "build.json")
    out = StringIO()
    compare_runs([run], columns="peak", pivot="param:semantics", out=out)
    assert "(legacy)" in out.getvalue() and "(v1)" in out.getvalue()
    fig, n = plotting.plot_compare([run], metric="peak", pivot="param:semantics")
    assert n == 2


def test_compare_pivot_with_single_dim_value_errors(tmp_path):
    # a run that doesn't vary the pivot dim has nothing to pair → a clear error, not an empty plot.
    run = _run(tmp_path / "a.json", ROWS_A, memory=True)  # only the dim 'n', no 'semantics'
    with pytest.raises(ValueError, match="not a dim"):
        plotting.plot_compare([run], metric="peak", pivot="param:semantics")


def test_pivot_with_multiple_runs_errors_in_plot(tmp_path):
    a = _combined_run(tmp_path / "a.json")
    b = _combined_run(tmp_path / "b.json")
    with pytest.raises(ValueError, match="folds a single run"):
        plotting.plot_compare([a, b], metric="peak", pivot="param:semantics")


def test_scaling_no_numeric_dim_points_to_pivot(tmp_path):
    # a single run whose only dim is categorical (semantics) can't auto-scale — the error should
    # guide toward --pivot (the categorical-A/B path), not just "pass x=".
    blob = {"peak_bytes": [10], "allocations": [0], "total_bytes": [0]}
    bms = [
        {
            "fullname": f"t[{sem}]",
            "params": {"semantics": sem},
            "stats": {"min": 1.0},
            "extra_info": {"benchmem": blob},
        }
        for sem in ("legacy", "v1")
    ]
    run = tmp_path / "build.json"
    run.write_text(json.dumps({"benchmarks": bms}))
    with pytest.raises(ValueError, match="--pivot"):
        plotting.plot_scaling([run], metric="peak")


def test_plot_scaling_explicit_node_facet(tmp_path):
    p = _run_two_funcs(tmp_path / "a.json")
    fig, n = plotting.plot_scaling(p, facet="node.func")  # node.func selectable by name
    assert n == 4
    assert fig.layout.title.text


def test_allocated_metric_labels_allocated(tmp_path):
    a = _run(tmp_path / "a.json", ROWS_A, memory=True)
    fig, _n = plotting.plot_scaling([a], metric="allocated")
    assert "allocated" in fig.layout.title.text.lower()  # not "peak"
    assert "peak" not in fig.layout.title.text.lower()


def test_metric_memory_no_longer_accepted(tmp_path):
    a = _run(tmp_path / "a.json", ROWS_A, memory=True)
    with pytest.raises(ValueError, match="metric must be one of"):
        plotting.plot_scaling([a], metric="memory")  # type: ignore[arg-type]  # dropped alias


def test_scatter_needs_two_runs(tmp_path):
    with pytest.raises(ValueError, match="at least 2"):
        plotting.plot_scatter([_run(tmp_path / "a.json", ROWS_A)])


def test_compare_no_common_ids_raises(tmp_path):
    a = _run(tmp_path / "a.json", [(10, 1.0)])
    b = _run(tmp_path / "b.json", [(99, 1.0)])  # disjoint id
    with pytest.raises(ValueError, match="no ids in common"):
        plotting.plot_compare([a, b])


def _run_mixed_axes(path):
    """One run with two incommensurable sweeps sharing a numeric dim, split by ``axis``."""
    benchmarks = [
        {
            "fullname": f"t[axis={axis}-v={v}]",
            "stats": {"min": float(v)},
            "params": {"v": v, "axis": axis},
        }
        for axis, vals in (("n", [10, 100, 1000]), ("severity", [0, 50, 100]))
        for v in vals
    ]
    path.write_text(json.dumps({"benchmarks": benchmarks}))
    return path


def test_where_filters_rows_to_matching_dim(tmp_path):
    p = _run_mixed_axes(tmp_path / "a.json")
    fig, n = plotting.plot_scaling(p, x="v", where={"axis": "n"})
    assert n == 3  # only the three n-sweep points survive


def test_where_numeric_value_matches(tmp_path):
    fig, n = plotting.plot_scaling(_run(tmp_path / "a.json", ROWS_A), where={"n": "100"})
    assert n == 1  # "100" matches the numeric dim 100


def test_where_unknown_key_raises(tmp_path):
    with pytest.raises(ValueError, match="not a dim"):
        plotting.plot_scaling(_run(tmp_path / "a.json", ROWS_A), where={"nope": "1"})


def test_where_no_match_raises(tmp_path):
    with pytest.raises(ValueError, match="no rows match"):
        plotting.plot_scaling(_run(tmp_path / "a.json", ROWS_A), where={"n": "99999"})


def test_where_applies_to_all_views(tmp_path):
    runs = [_run(tmp_path / f"{i}.json", ROWS_A) for i in range(3)]
    # sweep (imshow) filters identically at the long-frame level
    _fig, n = plotting.plot_sweep(runs, where={"n": "1000"})
    assert n == 1


def test_scaling_mixed_axes_separable_by_facet(tmp_path):
    # mixed incommensurable sweeps (n vs severity) share dim 'v'; facet= is the way out
    p = _run_mixed_axes(tmp_path / "a.json")
    fig, n = plotting.plot_scaling(p, x="v", facet="axis")
    assert n == 6  # both sweeps rendered, each in its own facet


def test_scaling_mixed_axes_separable_by_where(tmp_path):
    # ...or filter to one sweep at a time
    p = _run_mixed_axes(tmp_path / "a.json")
    fig, n = plotting.plot_scaling(p, x="v", where={"axis": "severity"})
    assert n == 3


def _x_axes_matched(fig):
    """True if every facet x-axis is matched to the shared default (plotly's default)."""
    axes = [fig.layout[k] for k in fig.layout if k.startswith("xaxis")]
    secondary = [ax for ax in axes if ax.matches is not None]
    return bool(secondary) and all(ax.matches for ax in secondary)


def _y_axes_matched(fig):
    axes = [fig.layout[k] for k in fig.layout if k.startswith("yaxis")]
    secondary = [ax for ax in axes if ax.matches is not None]
    return bool(secondary) and all(ax.matches for ax in secondary)


def test_facet_axes_shared_by_default(tmp_path):
    p = _run_mixed_axes(tmp_path / "a.json")
    fig, _n = plotting.plot_scaling(p, x="v", facet="axis")  # no free_axes
    assert _x_axes_matched(fig)  # plotly's matched default — the squish #49 describes


def test_free_axes_x_unmatches_only_x(tmp_path):
    p = _run_mixed_axes(tmp_path / "a.json")
    fig, _n = plotting.plot_scaling(p, x="v", facet="axis", free_axes="x")
    assert not _x_axes_matched(fig)  # x freed → each sweep its own range
    assert _y_axes_matched(fig)  # y still shared


def test_free_axes_y_unmatches_only_y(tmp_path):
    p = _run_mixed_axes(tmp_path / "a.json")
    fig, _n = plotting.plot_scaling(p, x="v", facet="axis", free_axes="y")
    assert _x_axes_matched(fig)
    assert not _y_axes_matched(fig)  # y freed → per-facet cost scale (the function case)


def test_free_axes_both_unmatches_both(tmp_path):
    p = _run_mixed_axes(tmp_path / "a.json")
    fig, _n = plotting.plot_scaling(p, x="v", facet="axis", free_axes="both")
    assert not _x_axes_matched(fig)
    assert not _y_axes_matched(fig)


def test_free_axes_noop_without_facet(tmp_path):
    # free_axes only acts when faceted; a single-panel plot is unaffected
    fig, _n = plotting.plot_scaling(_run(tmp_path / "a.json", ROWS_A), free_axes="both")
    assert _n == 3


def test_scaling_without_numeric_dim_raises(tmp_path):
    # dim 'kind' is categorical, so x can't be inferred
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps(
            {
                "benchmarks": [
                    {"fullname": "t[a]", "stats": {"min": 1.0}, "params": {"kind": "a"}},
                    {"fullname": "t[b]", "stats": {"min": 2.0}, "params": {"kind": "b"}},
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="numeric dim"):
        plotting.plot_scaling([p])


def _run_series(path, rows):
    """Write a memory run where each id carries a multi-pass peak series.

    ``rows`` is ``[(n, [peak_pass1, peak_pass2, ...])]`` (bytes).
    """
    benchmarks = [
        {
            "fullname": f"test_op[n={n}]",
            "stats": {"min": float(min(peaks))},
            "params": {"n": n},
            "extra_info": {
                "benchmem": {
                    "peak_bytes": [int(p) for p in peaks],
                    "allocations": [0] * len(peaks),
                    "total_bytes": [int(p) for p in peaks],
                }
            },
        }
        for n, peaks in rows
    ]
    path.write_text(json.dumps({"benchmarks": benchmarks}))
    return path


def _has_whiskers(fig):
    return any(getattr(tr.error_y, "array", None) is not None for tr in fig.data)


def test_scaling_band_shows_spread_whiskers(tmp_path):
    # multi-pass series with spread (min != max) -> the band draws min..max whiskers
    p = _run_series(tmp_path / "a.json", [(10, [100, 400]), (100, [200, 900])])
    fig, _n = plotting.plot_scaling([p], metric="peak")  # band="auto" default
    assert _has_whiskers(fig)


def test_scaling_band_none_suppresses_whiskers(tmp_path):
    p = _run_series(tmp_path / "a.json", [(10, [100, 400]), (100, [200, 900])])
    fig, _n = plotting.plot_scaling([p], metric="peak", band="none")
    assert not _has_whiskers(fig)


def test_scaling_band_auto_skips_whiskers_when_no_spread(tmp_path):
    # deterministic series (every pass identical) -> auto shows nothing to spread
    p = _run_series(tmp_path / "a.json", [(10, [100, 100]), (100, [200, 200])])
    fig, _n = plotting.plot_scaling([p], metric="peak")
    assert not _has_whiskers(fig)


def test_scaling_band_minmax_forces_whiskers_even_when_flat(tmp_path):
    p = _run_series(tmp_path / "a.json", [(10, [100, 100]), (100, [200, 200])])
    fig, _n = plotting.plot_scaling([p], metric="peak", band="minmax")
    assert _has_whiskers(fig)  # present (zero-length) so the schema is stable


def test_scaling_band_ignored_for_time(tmp_path):
    # time isn't a memray series; band never applies
    p = _run(tmp_path / "a.json", ROWS_A)
    fig, _n = plotting.plot_scaling([p], metric="time", band="minmax")
    assert not _has_whiskers(fig)


def _run_series_grouped(path):
    """Multi-pass memory run with a colour dim (impl) and a facet dim (func)."""
    bms = [
        {
            "fullname": f"pkg/test_{func}.py::test_{func}[impl={impl}-n={n}]",
            "stats": {"min": float(min(peaks))},
            "params": {"n": n, "impl": impl},
            "extra_info": {
                "benchmem": {
                    "peak_bytes": [int(x) for x in peaks],
                    "allocations": [0] * len(peaks),
                    "total_bytes": [int(x) for x in peaks],
                }
            },
        }
        for impl in ("a", "b")
        for func in ("build", "solve")
        for n, peaks in [(10, [100, 400]), (100, [200, 900])]
    ]
    path.write_text(json.dumps({"benchmarks": bms}))
    return path


def test_scaling_band_whiskers_survive_color_and_facet(tmp_path):
    # the band must attach per-trace once px splits by colour/facet, not just on a lone series
    p = _run_series_grouped(tmp_path / "a.json")
    fig, _n = plotting.plot_scaling([p], metric="peak", color="impl", facet="node.func")
    assert len(fig.data) > 1  # split into colour × facet traces
    assert all(tr.error_y.array is not None for tr in fig.data)  # every trace keeps its whiskers
