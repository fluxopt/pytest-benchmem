"""Figure-structure assertions for the plot_* views — no pixels, just shape."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("pandas")
pytest.importorskip("plotly")

from pytest_benchmem import plotting


def _run(path, rows, *, memory=False):
    """Write a pytest-benchmark run; rows is [(n, value)] with n a numeric dim."""
    benchmarks = []
    for n, v in rows:
        bm = {"fullname": f"test_op[n={n}]", "stats": {"min": v}, "params": {"n": n}}
        if memory:
            bm["extra_info"] = {"peak_mib": v}
        benchmarks.append(bm)
    path.write_text(json.dumps({"benchmarks": benchmarks}))
    return path


ROWS_A = [(10, 1.0), (100, 2.0), (1000, 4.0)]
ROWS_B = [(10, 1.1), (100, 1.8), (1000, 5.0)]


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


def test_metric_memory_unit_in_title(tmp_path):
    a = _run(tmp_path / "a.json", ROWS_A, memory=True)
    fig, _n = plotting.plot_scaling([a], metric="memory")
    assert "peak" in fig.layout.title.text.lower()  # vlabel for MiB is "peak"


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
