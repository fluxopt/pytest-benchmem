from __future__ import annotations

import json

import pytest

pytest.importorskip("pandas")
pytest.importorskip("numpy")

import pandas as pd

from pytest_benchmem.scaling import fit_power_law


def _df(rows, *, extra_dims=None):
    """rows: [(id, n, value)]; extra_dims: optional list of per-row dim dicts."""
    extra_dims = extra_dims or [{}] * len(rows)
    return pd.DataFrame(
        [
            {"snapshot": "a", "id": i, "value": v, "n": n, **d}
            for (i, n, v), d in zip(rows, extra_dims, strict=True)
        ]
    )


def test_quadratic_exponent():
    fits = fit_power_law(_df([("t[n=10]", 10, 100), ("t[n=20]", 20, 400), ("t[n=40]", 40, 1600)]))
    assert len(fits) == 1
    f = fits[0]
    assert f.family == "t"
    assert abs(f.exponent - 2.0) < 1e-9  # value = n^2
    assert f.r2 > 0.999
    assert f.n == 3


def test_linear_exponent():
    f = fit_power_law(
        _df([("t[n=10]", 10, 30), ("t[n=100]", 100, 300), ("t[n=1000]", 1000, 3000)])
    )[0]
    assert abs(f.exponent - 1.0) < 1e-9  # value = 3n


def test_two_families_split_by_id_base():
    rows = [
        ("sort[n=10]", 10, 100),
        ("sort[n=20]", 20, 400),
        ("sort[n=40]", 40, 1600),
        ("scan[n=10]", 10, 10),
        ("scan[n=20]", 20, 20),
        ("scan[n=40]", 40, 40),
    ]
    fits = {f.family: f for f in fit_power_law(_df(rows))}
    assert set(fits) == {"sort", "scan"}
    assert abs(fits["sort"].exponent - 2.0) < 1e-9
    assert abs(fits["scan"].exponent - 1.0) < 1e-9


def test_families_split_by_dim():
    rows = [
        ("t[a]", 10, 100),
        ("t[b]", 20, 400),
        ("t[c]", 40, 1600),
        ("t[d]", 10, 10),
        ("t[e]", 20, 20),
        ("t[f]", 40, 40),
    ]
    dims = [{"op": "build"}] * 3 + [{"op": "solve"}] * 3
    fits = {f.family: f for f in fit_power_law(_df(rows, extra_dims=dims), x="n")}
    assert set(fits) == {"t[op=build]", "t[op=solve]"}
    assert abs(fits["t[op=build]"].exponent - 2.0) < 1e-9
    assert abs(fits["t[op=solve]"].exponent - 1.0) < 1e-9


def test_under_two_points_dropped():
    assert fit_power_law(_df([("t[n=10]", 10, 100)])) == []


def test_non_positive_values_dropped():
    # a 0 value can't go log-log; only the two positive points remain → still fit
    f = fit_power_law(_df([("t[n=10]", 10, 0), ("t[n=20]", 20, 400), ("t[n=40]", 40, 1600)]))[0]
    assert f.n == 2


def test_infer_x_requires_one_numeric_dim():
    df = pd.DataFrame([{"snapshot": "a", "id": "t", "value": 1.0}])  # no dims
    with pytest.raises(ValueError, match="numeric dim"):
        fit_power_law(df)


def test_cli_scaling_reports_exponent(tmp_path):
    pytest.importorskip("typer")
    from typer.testing import CliRunner

    from pytest_benchmem.cli import app

    benchmarks = [
        {"fullname": f"test_op[n={n}]", "stats": {"min": float(n * n)}, "params": {"n": n}}
        for n in (10, 20, 40, 80)
    ]
    run = tmp_path / "r.json"
    run.write_text(json.dumps({"benchmarks": benchmarks}))
    result = CliRunner().invoke(app, ["scaling", str(run)])
    assert result.exit_code == 0, result.output
    assert "O(n^2.0" in result.output  # time ~ n^2
