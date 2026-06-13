from __future__ import annotations

import contextlib
import importlib.util
import json

import pytest

pytest.importorskip("typer")
pytest.importorskip("pandas")
pytest.importorskip("plotly")

from typer.testing import CliRunner

from pytest_benchmem import plotting
from pytest_benchmem.cli import app

runner = CliRunner()


def _text(result):
    """All captured text — output, plus stderr when click keeps it separate."""
    text = result.output or ""
    with contextlib.suppress(ValueError, AttributeError):
        text += result.stderr
    return text


def _run(tmp_path, name, benchmarks):
    p = tmp_path / name
    p.write_text(json.dumps({"benchmarks": benchmarks}))
    return p


def _bm(name, *, t=1.0):
    return {"fullname": name, "stats": {"min": t}}


class _FakeFig:
    def write_html(self, path):
        self.path = path


# --- compare ---------------------------------------------------------------------


def test_compare_prints_table(tmp_path):
    a = _run(tmp_path, "base.json", [_bm("test_x", t=1.0)])
    b = _run(tmp_path, "head.json", [_bm("test_x", t=2.0)])
    result = runner.invoke(app, ["compare", str(a), str(b)])
    assert result.exit_code == 0
    assert "+100.0%" in result.output  # compare_runs writes the table to stdout


def test_compare_missing_file_exits_2(tmp_path):
    a = _run(tmp_path, "base.json", [_bm("test_x")])
    result = runner.invoke(app, ["compare", str(a), str(tmp_path / "nope.json")])
    assert result.exit_code == 2
    assert "missing" in _text(result)


# --- plot view auto-selection ----------------------------------------------------


@pytest.mark.parametrize(
    "n_runs, expected",
    [(1, "plot_scaling"), (2, "plot_scatter"), (3, "plot_sweep")],
)
def test_plot_view_defaults_by_run_count(tmp_path, monkeypatch, n_runs, expected):
    calls = []

    def _stub(name):
        def _fn(*a, **k):
            calls.append(name)
            return _FakeFig(), 7

        return _fn

    for name in ("plot_compare", "plot_scatter", "plot_sweep", "plot_scaling"):
        monkeypatch.setattr(plotting, name, _stub(name))
    runs = [_run(tmp_path, f"r{i}.json", [_bm("x")]) for i in range(n_runs)]
    result = runner.invoke(app, ["plot", *map(str, runs), "-o", str(tmp_path / "out.html")])
    assert result.exit_code == 0, _text(result)
    assert calls == [expected]


def test_plot_unknown_view_exits_2(tmp_path):
    r = _run(tmp_path, "r.json", [_bm("x")])
    result = runner.invoke(app, ["plot", str(r), "--view", "bogus", "-o", str(tmp_path / "o.html")])
    assert result.exit_code == 2
    assert "unknown view" in _text(result)


def test_plot_missing_file_exits_2(tmp_path):
    result = runner.invoke(app, ["plot", str(tmp_path / "nope.json")])
    assert result.exit_code == 2
    assert "missing" in _text(result)


def test_plot_value_error_exits_1(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise ValueError("no ids in common")

    monkeypatch.setattr(plotting, "plot_scaling", boom)
    r = _run(tmp_path, "r.json", [_bm("x")])
    result = runner.invoke(app, ["plot", str(r), "-o", str(tmp_path / "o.html")])
    assert result.exit_code == 1
    assert "no ids in common" in _text(result)


def test_plot_without_plotly_exits_2(tmp_path, monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **k: None if name == "plotly" else real(name, *a, **k),
    )
    r = _run(tmp_path, "r.json", [_bm("x")])
    result = runner.invoke(app, ["plot", str(r), "-o", str(tmp_path / "o.html")])
    assert result.exit_code == 2
    assert "pytest-benchmem[plot]" in _text(result)
