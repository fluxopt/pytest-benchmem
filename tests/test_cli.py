from __future__ import annotations

import contextlib
import importlib.util
import json
from pathlib import Path
from typing import Any

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


def _bm(name, *, t=1.0, peak=None):
    bm = {"fullname": name, "stats": {s: t for s in ("min", "max", "mean", "median", "stddev")}}
    if peak is not None:
        bm["extra_info"] = {
            "benchmem": {"peak_bytes": [peak], "allocations": [0], "total_bytes": [peak]}
        }
    return bm


class _FakeFig:
    def write_html(self, path):
        self.path = path


# --- compare ---------------------------------------------------------------------


def test_compare_prints_table(tmp_path):
    a = _run(tmp_path, "base.json", [_bm("test_x", t=1.0)])
    b = _run(tmp_path, "head.json", [_bm("test_x", t=2.0)])
    result = runner.invoke(app, ["compare", str(a), str(b)])
    assert result.exit_code == 0
    # the relative-multiplier table: head 2.0 is 2.00× the best run (1.0)
    assert "(2.00)" in result.output and "time (s)" in result.output


def test_compare_single_run_prints_table(tmp_path):
    # one run is allowed now: a plain table, no comparison multiplier
    a = _run(tmp_path, "run.json", [_bm("test_x", t=1.0, peak=10 * 1024**2)])
    result = runner.invoke(app, ["compare", str(a), "--columns", "time,peak"])
    assert result.exit_code == 0, _text(result)
    assert "time (s)" in result.output and "peak (MiB)" in result.output
    assert "(1.0)" not in result.output  # nothing to rank against


def test_compare_single_run_with_fail_on_exits_2(tmp_path):
    # --fail-on gates growth of one run vs another, so it needs two; refuse, don't silently pass
    a = _run(tmp_path, "run.json", [_bm("test_x", peak=100)])
    result = runner.invoke(app, ["compare", str(a), "--fail-on", "peak:10%"])
    assert result.exit_code == 2
    assert "at least two runs" in _text(result)


def test_compare_columns_selects_time_and_peak(tmp_path):
    a = _run(tmp_path, "base.json", [_bm("test_x", t=1.0, peak=10 * 1024**2)])
    b = _run(tmp_path, "head.json", [_bm("test_x", t=1.0, peak=20 * 1024**2)])
    result = runner.invoke(app, ["compare", str(a), str(b), "--columns", "time,peak"])
    assert result.exit_code == 0, _text(result)
    assert "time (s)" in result.output and "peak (MiB)" in result.output


def test_compare_missing_file_exits_2(tmp_path):
    a = _run(tmp_path, "base.json", [_bm("test_x")])
    result = runner.invoke(app, ["compare", str(a), str(tmp_path / "nope.json")])
    assert result.exit_code == 2
    assert "missing" in _text(result)


def test_compare_fail_on_regression_exits_1(tmp_path):
    a = _run(tmp_path, "base.json", [_bm("test_x", peak=100)])
    b = _run(tmp_path, "head.json", [_bm("test_x", peak=130)])  # +30%
    result = runner.invoke(app, ["compare", str(a), str(b), "--fail-on", "peak:10%"])
    assert result.exit_code == 1
    assert "regression" in _text(result)


def test_compare_fail_on_within_threshold_exits_0(tmp_path):
    a = _run(tmp_path, "base.json", [_bm("test_x", peak=100)])
    b = _run(tmp_path, "head.json", [_bm("test_x", peak=105)])  # +5%
    result = runner.invoke(app, ["compare", str(a), str(b), "--fail-on", "peak:10%"])
    assert result.exit_code == 0
    assert "no regressions" in _text(result)


def test_compare_bad_threshold_exits_2(tmp_path):
    a = _run(tmp_path, "base.json", [_bm("test_x", peak=100)])
    b = _run(tmp_path, "head.json", [_bm("test_x", peak=130)])
    result = runner.invoke(app, ["compare", str(a), str(b), "--fail-on", "bogus:5%"])
    assert result.exit_code == 2
    assert "unknown field" in _text(result)


def test_compare_pivot_folds_run_along_dim(tmp_path):
    # --pivot makes a param the comparison series within one run (the A/B a file-pair gives)
    def _b(sem, peak):
        b = _bm(f"m.py::test_build[{sem}]", peak=peak)
        b["params"] = {"semantics": sem}
        return b

    run = _run(tmp_path, "build.json", [_b("legacy", 10 * 1024**2), _b("v1", 12 * 1024**2)])
    args = ["compare", str(run), "--columns", "peak", "--pivot", "param:semantics"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, _text(result)
    assert "(legacy)" in result.output and "(v1)" in result.output
    assert "(1.20)" in result.output  # v1 is 1.20× the best (legacy)


def test_compare_pivot_with_multiple_runs_exits_1(tmp_path):
    a = _run(tmp_path, "a.json", [_bm("test_x", peak=1024)])
    b = _run(tmp_path, "b.json", [_bm("test_x", peak=2048)])
    result = runner.invoke(app, ["compare", str(a), str(b), "--pivot", "param:x"])
    assert result.exit_code == 1
    assert "folds a single run" in _text(result)


def test_plot_pivot_rejected_for_scaling_view(tmp_path):
    # --pivot re-points the comparison series; scaling/sweep have no series axis to re-point
    run = _run(tmp_path, "a.json", [_bm("test_x", peak=1024)])
    result = runner.invoke(app, ["plot", str(run), "--view", "scaling", "--pivot", "param:n"])
    assert result.exit_code == 2
    assert "compare or scatter" in _text(result)


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


def test_plot_label_option_threads_through(tmp_path, monkeypatch):
    captured = {}

    def _stub(*a, **k):
        captured.update(k)
        return _FakeFig(), 3

    monkeypatch.setattr(plotting, "plot_sweep", _stub)
    runs = [_run(tmp_path, f"r{i}.json", [_bm("x")]) for i in range(3)]
    result = runner.invoke(
        app,
        [
            "plot",
            *map(str, runs),
            "-l",
            "0.6",
            "-l",
            "0.7",
            "-l",
            "0.8",
            "-o",
            str(tmp_path / "o.html"),
        ],
    )
    assert result.exit_code == 0, _text(result)
    assert captured["labels"] == ["0.6", "0.7", "0.8"]


def test_plot_columns_selects_metric(tmp_path, monkeypatch):
    """plot selects the metric via --columns — the same flag as compare."""
    captured = {}

    def _stub(*a, **k):
        captured.update(k)
        return _FakeFig(), 1

    monkeypatch.setattr(plotting, "plot_scaling", _stub)
    r = _run(tmp_path, "r.json", [_bm("x")])
    result = runner.invoke(
        app, ["plot", str(r), "--columns", "peak", "-o", str(tmp_path / "o.html")]
    )
    assert result.exit_code == 0, _text(result)
    assert captured["metric"] == "peak"


def test_plot_metric_flag_removed(tmp_path):
    """--metric is gone (pre-1.0 rename to --columns, matching compare)."""
    r = _run(tmp_path, "r.json", [_bm("x")])
    result = runner.invoke(
        app, ["plot", str(r), "--metric", "peak", "-o", str(tmp_path / "o.html")]
    )
    assert result.exit_code == 2
    assert "No such option" in _text(result)


def test_plot_columns_rejects_multiple_metrics(tmp_path):
    """A plot has one value axis — multiple metrics is a clean usage error, not a crash."""
    r = _run(tmp_path, "r.json", [_bm("x")])
    result = runner.invoke(
        app, ["plot", str(r), "--columns", "time,peak", "-o", str(tmp_path / "o.html")]
    )
    assert result.exit_code == 2
    assert "not one of" in _text(result) or "Invalid value" in _text(result)


def test_plot_where_parses_into_dict(tmp_path, monkeypatch):
    captured = {}

    def _stub(*a, **k):
        captured.update(k)
        return _FakeFig(), 3

    monkeypatch.setattr(plotting, "plot_scaling", _stub)
    r = _run(tmp_path, "r.json", [_bm("x")])
    out = str(tmp_path / "o.html")
    result = runner.invoke(
        app,
        ["plot", str(r), "--where", "axis=n", "--where", "solver=glpk", "-o", out],
    )
    assert result.exit_code == 0, _text(result)
    assert captured["where"] == {"axis": "n", "solver": "glpk"}


def test_plot_free_axes_threads_through(tmp_path, monkeypatch):
    captured = {}

    def _stub(*a, **k):
        captured.update(k)
        return _FakeFig(), 3

    monkeypatch.setattr(plotting, "plot_scaling", _stub)
    r = _run(tmp_path, "r.json", [_bm("x")])
    out = str(tmp_path / "o.html")
    result = runner.invoke(app, ["plot", str(r), "--free-axes", "y", "-o", out])
    assert result.exit_code == 0, _text(result)
    assert captured["free_axes"] == "y"  # str-enum value, matches the Literal


def test_plot_free_axes_rejects_bad_choice(tmp_path):
    r = _run(tmp_path, "r.json", [_bm("x")])
    out = str(tmp_path / "o.html")
    result = runner.invoke(app, ["plot", str(r), "--free-axes", "diagonal", "-o", out])
    assert result.exit_code == 2  # typer rejects an out-of-choice value


def test_plot_where_malformed_exits_2(tmp_path):
    r = _run(tmp_path, "r.json", [_bm("x")])
    out = str(tmp_path / "o.html")
    result = runner.invoke(app, ["plot", str(r), "--where", "noequals", "-o", out])
    assert result.exit_code == 2
    assert "KEY=VALUE" in _text(result)


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


# --- sweep -----------------------------------------------------------------------


def _patch_sweep(monkeypatch, tmp_path, *, failed=()):
    """Stub the sweep engine + subprocess so no uv/network is touched.

    Records the call into the returned dict; the fake engine runs the CLI's ``run``
    callback against one fake Venv per version, and the fake subprocess writes the
    JSON the callback expects (so ``produced`` is populated).
    """
    import pytest_benchmem.sweep as sweepmod

    captured: dict[str, Any] = {"cmds": []}

    def fake_sweep(versions, run, **kw):
        captured["versions"] = list(versions)
        captured.update(kw)
        for v in versions:
            run(sweepmod.Venv(v, tmp_path / "py", {}, tmp_path, None))
        return list(failed)

    def fake_subprocess_run(cmd, **kw):
        captured["cmds"].append(cmd)
        for arg in cmd:
            if isinstance(arg, str) and arg.startswith("--benchmark-json="):
                path = Path(arg.split("=", 1)[1])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}")

        class _Completed:
            returncode = 0

        return _Completed()

    monkeypatch.setattr(sweepmod, "sweep", fake_sweep)
    monkeypatch.setattr("pytest_benchmem.cli.subprocess.run", fake_subprocess_run)
    return captured


def test_sweep_runs_each_version_and_hints_next_step(tmp_path, monkeypatch):
    captured = _patch_sweep(monkeypatch, tmp_path)
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "sweep",
            "mypkg",
            "1.2.0",
            "1.3.0",
            "--suite",
            "benchmarks/",
            "--out",
            str(out),
            "--memory",  # adds --benchmark-memory
            "--pytest-arg=-k",
            "--pytest-arg=build",  # forwarded verbatim
        ],
    )
    assert result.exit_code == 0, _text(result)
    assert captured["versions"] == ["1.2.0", "1.3.0"]
    # a plain version maps to pkg==version
    assert captured["install_spec"]("1.2.0") == "mypkg==1.2.0"
    # the always-on --benchmark-only, the --memory pass, and the forwarded args all reach pytest
    assert all("--benchmark-only" in cmd for cmd in captured["cmds"])
    assert all("--benchmark-memory" in cmd for cmd in captured["cmds"])
    assert all(cmd[-2:] == ["-k", "build"] for cmd in captured["cmds"])
    # one json per version, under --out, and the next-step hint is printed
    assert (out / "1.2.0.json").exists() and (out / "1.3.0.json").exists()
    assert "benchmem compare" in result.output


def test_sweep_exits_1_on_provision_failure(tmp_path, monkeypatch):
    _patch_sweep(monkeypatch, tmp_path, failed=["1.3.0"])
    result = runner.invoke(
        app,
        ["sweep", "mypkg", "1.2.0", "1.3.0", "--suite", "b/", "--out", str(tmp_path / "o")],
    )
    assert result.exit_code == 1
    assert "failed to provision: 1.3.0" in _text(result)


# --- flamegraph ------------------------------------------------------------------

memray = pytest.importorskip("memray")


def _make_bin(path: Path, *, n: int, native: bool = False) -> Path:
    """A real memray capture so the command's stats read + render exercise the actual file."""
    with memray.Tracker(str(path), native_traces=native):
        _hold = [bytearray(1024) for _ in range(n)]  # noqa: F841 — keep alive past peak
    return path


@pytest.fixture
def profiles(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    _make_bin(d / "test_small.bin", n=200)
    _make_bin(d / "test_big.bin", n=4000)
    return d


def test_flamegraph_worst_picks_heaviest(profiles):
    result = runner.invoke(app, ["flamegraph", str(profiles), "--worst", "peak"])
    assert result.exit_code == 0, _text(result)
    assert (profiles / "test_big.flamegraph.html").exists()  # heaviest rendered next to its .bin
    assert not (profiles / "test_small.flamegraph.html").exists()


def test_flamegraph_resolves_by_substring(profiles):
    result = runner.invoke(app, ["flamegraph", str(profiles), "small"])
    assert result.exit_code == 0, _text(result)
    assert (profiles / "test_small.flamegraph.html").exists()


def test_flamegraph_custom_output_and_force(profiles, tmp_path):
    out = tmp_path / "fg.html"
    runner.invoke(app, ["flamegraph", str(profiles), "test_big", "-o", str(out)])
    assert out.exists()
    # a second render refuses to clobber without --force, succeeds with it
    again = runner.invoke(app, ["flamegraph", str(profiles), "test_big", "-o", str(out)])
    assert again.exit_code != 0
    forced = runner.invoke(app, ["flamegraph", str(profiles), "test_big", "-o", str(out), "-f"])
    assert forced.exit_code == 0


def test_flamegraph_ambiguous_without_id_lists_available(profiles):
    result = runner.invoke(app, ["flamegraph", str(profiles)])
    assert result.exit_code == 2
    assert "test_big" in _text(result) and "test_small" in _text(result)


def test_flamegraph_unknown_id_errors(profiles):
    result = runner.invoke(app, ["flamegraph", str(profiles), "nope"])
    assert result.exit_code == 2
    assert "no profile matches" in _text(result)


def test_flamegraph_id_and_worst_are_mutually_exclusive(profiles):
    result = runner.invoke(app, ["flamegraph", str(profiles), "test_big", "--worst", "peak"])
    assert result.exit_code == 2
    assert "not both" in _text(result)


def test_flamegraph_bad_report_errors(profiles):
    result = runner.invoke(app, ["flamegraph", str(profiles), "test_big", "--report", "bogus"])
    assert result.exit_code == 2
    assert "unknown reporter" in _text(result)


def test_flamegraph_empty_dir_errors(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["flamegraph", str(empty)])
    assert result.exit_code == 2
    assert "no .bin profiles" in _text(result)


def test_flamegraph_native_guard(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    _make_bin(d / "test_plain.bin", n=200, native=False)
    _make_bin(d / "test_native.bin", n=200, native=True)
    # --native errors on a python-only capture, with the fix hint
    plain = runner.invoke(app, ["flamegraph", str(d), "test_plain", "--native"])
    assert plain.exit_code == 2 and "no native traces" in _text(plain)
    # and passes on a native capture
    nat = runner.invoke(app, ["flamegraph", str(d), "test_native", "--native"])
    assert nat.exit_code == 0, _text(nat)
