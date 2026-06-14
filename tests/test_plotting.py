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
                "benchmem": {
                    "peak_bytes": peak,
                    "peak_bytes_max": peak,
                    "allocations": 0,
                    "total_bytes": peak,
                    "repeats": 1,
                }
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


def test_node_dims_carried_but_not_auto_inferred(tmp_path):
    df, _u = load_long_df(_run_two_funcs(tmp_path / "a.json"))
    assert "node.func" in plotting._carry_dims(df)  # available for explicit use
    assert "node.func" not in plotting._dim_columns(df)  # never auto-picked
    assert "n" in plotting._dim_columns(df)  # the real param still auto-inferable


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


def test_memory_is_alias_for_peak(tmp_path):
    a = _run(tmp_path / "a.json", ROWS_A, memory=True)
    fig, _n = plotting.plot_scaling([a], metric="memory")
    assert "peak" in fig.layout.title.text.lower()  # normalized to the canonical name


def test_scatter_needs_two_runs(tmp_path):
    with pytest.raises(ValueError, match="at least 2"):
        plotting.plot_scatter([_run(tmp_path / "a.json", ROWS_A)])


def test_compare_no_common_ids_raises(tmp_path):
    a = _run(tmp_path / "a.json", [(10, 1.0)])
    b = _run(tmp_path / "b.json", [(99, 1.0)])  # disjoint id
    with pytest.raises(ValueError, match="no ids in common"):
        plotting.plot_compare([a, b])


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
