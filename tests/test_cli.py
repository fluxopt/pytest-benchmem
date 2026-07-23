from __future__ import annotations

import contextlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("typer")
pytest.importorskip("pandas")
pytest.importorskip("plotly")

from typer.testing import CliRunner

from pytest_benchmem import plotting
from pytest_benchmem.cli import app
from tests._builders import bm, write_run

runner = CliRunner()


def _text(result):
    """All captured text — output, plus stderr when click keeps it separate."""
    text = result.output or ""
    with contextlib.suppress(ValueError, AttributeError):
        text += result.stderr
    return text


class _FakeFig:
    def write_html(self, path):
        self.path = path
        self.kind = "html"

    def write_image(self, path):
        self.path = path
        self.kind = "image"


@pytest.fixture
def capture_view(monkeypatch):
    """Stub one plot_* view; ``install(view)`` returns the kwargs dict the CLI threads into it.

    The dict is populated when the command runs, so read it after ``runner.invoke``.
    """

    def install(view="plot_scaling"):
        captured: dict[str, Any] = {}

        def _stub(*a, **k):
            captured.update(k)
            return _FakeFig(), 3

        monkeypatch.setattr(plotting, view, _stub)
        return captured

    return install


@pytest.fixture
def view_calls(monkeypatch):
    """Stub every plot_* view; return the list each records its name in when the CLI picks it."""
    calls: list[str] = []
    for name in ("plot_compare", "plot_scatter", "plot_sweep", "plot_scaling"):

        def _stub(*a, _name=name, **k):
            calls.append(_name)
            return _FakeFig(), 3

        monkeypatch.setattr(plotting, name, _stub)
    return calls


# --- compare ---------------------------------------------------------------------


def test_compare_prints_table(tmp_path):
    a = write_run(tmp_path / "base.json", [bm("test_x", t=1.0)])
    b = write_run(tmp_path / "head.json", [bm("test_x", t=2.0)])
    result = runner.invoke(app, ["compare", str(a), str(b)])
    assert result.exit_code == 0
    # the relative-multiplier table: head 2.0 is 2.00× the best run (1.0)
    assert "(2.00)" in result.output and "time (s)" in result.output


def test_compare_single_run_prints_table(tmp_path):
    # one run is allowed now: a plain table, no comparison multiplier
    a = write_run(tmp_path / "run.json", [bm("test_x", t=1.0, peak=10 * 1024**2)])
    result = runner.invoke(app, ["compare", str(a), "--columns", "time,peak"])
    assert result.exit_code == 0, _text(result)
    assert "time (s)" in result.output and "peak (MiB)" in result.output
    assert "(1.0)" not in result.output  # nothing to rank against


@pytest.mark.parametrize(
    "peaks, extra, code, needle",
    [
        ([100], ["--fail-on", "peak:10%"], 2, "at least two runs"),  # one run can't be gated
        ([100, 130], ["--fail-on", "bogus:5%"], 2, "unknown field"),  # bad threshold field
        ([100, 130], ["--fail-on", "peak:10%"], 1, "regression"),  # +30% trips the gate
        ([100, 105], ["--fail-on", "peak:10%"], 0, "no regressions"),  # +5% is under it
    ],
)
def test_compare_fail_on_gate(tmp_path, peaks, extra, code, needle):
    runs = [
        str(write_run(tmp_path / f"r{i}.json", [bm("test_x", peak=p)])) for i, p in enumerate(peaks)
    ]
    result = runner.invoke(app, ["compare", *runs, *extra])
    assert result.exit_code == code
    assert needle in _text(result)


def test_compare_columns_selects_time_and_peak(tmp_path):
    a = write_run(tmp_path / "base.json", [bm("test_x", t=1.0, peak=10 * 1024**2)])
    b = write_run(tmp_path / "head.json", [bm("test_x", t=1.0, peak=20 * 1024**2)])
    result = runner.invoke(app, ["compare", str(a), str(b), "--columns", "time,peak"])
    assert result.exit_code == 0, _text(result)
    assert "time (s)" in result.output and "peak (MiB)" in result.output


def test_compare_missing_file_exits_2(tmp_path):
    a = write_run(tmp_path / "base.json", [bm("test_x")])
    result = runner.invoke(app, ["compare", str(a), str(tmp_path / "nope.json")])
    assert result.exit_code == 2
    assert "missing" in _text(result)


def test_compare_format_md_emits_markdown(tmp_path):
    a = write_run(tmp_path / "base.json", [bm("test_x", peak=10 * 1024**2)])
    b = write_run(tmp_path / "head.json", [bm("test_x", peak=12 * 1024**2)])
    result = runner.invoke(app, ["compare", str(a), str(b), "--columns", "peak", "--format", "md"])
    assert result.exit_code == 0, _text(result)
    assert "#### test_x" in result.output and "| name |" in result.output
    assert "(1.20)" in result.output  # multiplier carried; no colour needed


def test_compare_diff_shows_base_head_delta(tmp_path):
    a = write_run(tmp_path / "base.json", [bm("test_x", peak=10 * 1024**2)])
    b = write_run(tmp_path / "head.json", [bm("test_x", peak=12 * 1024**2)])
    result = runner.invoke(app, ["compare", str(a), str(b), "--columns", "peak", "--diff"])
    assert result.exit_code == 0, _text(result)
    assert "peak base" in result.output and "head" in result.output  # baseline value + Δ column
    assert "+20.0%" in result.output  # 10 -> 12 MiB, shown as a signed Δ


def test_compare_diff_needs_a_pair_errors(tmp_path):
    a = write_run(tmp_path / "solo.json", [bm("test_x", peak=10 * 1024**2)])
    result = runner.invoke(app, ["compare", str(a), "--diff"])
    assert result.exit_code == 1  # same wrapper as compare's other validation errors
    assert "at least two series" in _text(result)


def test_compare_pivot_folds_run_along_dim(tmp_path):
    # --pivot makes a param the comparison series within one run (the A/B a file-pair gives)
    def _b(sem, peak):
        return bm(f"m.py::test_build[{sem}]", peak=peak, params={"semantics": sem})

    run = write_run(tmp_path / "build.json", [_b("legacy", 10 * 1024**2), _b("v1", 12 * 1024**2)])
    args = ["compare", str(run), "--columns", "peak", "--pivot", "param:semantics"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, _text(result)
    assert "(legacy)" in result.output and "(v1)" in result.output
    assert "(1.20)" in result.output  # v1 is 1.20× the best (legacy)


def test_compare_pivot_with_multiple_runs_exits_1(tmp_path):
    a = write_run(tmp_path / "a.json", [bm("test_x", peak=1024)])
    b = write_run(tmp_path / "b.json", [bm("test_x", peak=2048)])
    result = runner.invoke(app, ["compare", str(a), str(b), "--pivot", "param:x"])
    assert result.exit_code == 1
    assert "folds a single run" in _text(result)


def test_compare_pivot_fail_on_gates_along_dim(tmp_path):
    # --fail-on generalizes along the pivot axis: gate the first dim value (legacy) vs the last
    # (v1) from one combined run — no second file needed.
    def _b(sem, peak):
        return bm(f"t[{sem}]", peak=peak, params={"semantics": sem})

    run = write_run(tmp_path / "build.json", [_b("legacy", 100), _b("v1", 130)])  # +30%
    args = ["compare", str(run), "--columns", "peak", "--pivot", "param:semantics"]
    over = runner.invoke(app, [*args, "--fail-on", "peak:10%"])
    assert over.exit_code == 1 and "regression" in _text(over)
    under = runner.invoke(app, [*args, "--fail-on", "peak:50%"])
    assert under.exit_code == 0 and "no regressions" in _text(under)


def test_plot_pivot_rejected_for_scaling_view(tmp_path):
    # --pivot re-points the comparison series; scaling/sweep have no series axis to re-point
    run = write_run(tmp_path / "a.json", [bm("test_x", peak=1024)])
    result = runner.invoke(app, ["plot", str(run), "--view", "scaling", "--pivot", "param:n"])
    assert result.exit_code == 2
    assert "compare or scatter" in _text(result)


def test_plot_pivot_defaults_to_compare_view(tmp_path, view_calls):
    # one run + --pivot with no --view must default to compare, not scaling (which rejects --pivot)
    run = write_run(tmp_path / "build.json", [bm("t[legacy]", peak=1024), bm("t[v1]", peak=2048)])
    args = ["plot", str(run), "--pivot", "param:semantics", "-o", str(tmp_path / "o.html")]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, _text(result)
    assert view_calls == ["plot_compare"]  # not plot_scaling


# --- plot view auto-selection ----------------------------------------------------


@pytest.mark.parametrize(
    "n_runs, expected",
    [(1, "plot_scaling"), (2, "plot_scatter"), (3, "plot_sweep")],
)
def test_plot_view_defaults_by_run_count(tmp_path, view_calls, n_runs, expected):
    runs = [write_run(tmp_path / f"r{i}.json", [bm("x")]) for i in range(n_runs)]
    result = runner.invoke(app, ["plot", *map(str, runs), "-o", str(tmp_path / "out.html")])
    assert result.exit_code == 0, _text(result)
    assert view_calls == [expected]


def test_plot_label_option_threads_through(tmp_path, capture_view):
    captured = capture_view("plot_sweep")
    runs = [write_run(tmp_path / f"r{i}.json", [bm("x")]) for i in range(3)]
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


def test_plot_columns_selects_metric(tmp_path, capture_view):
    """plot selects the metric via --columns — the same flag as compare."""
    captured = capture_view()
    r = write_run(tmp_path / "r.json", [bm("x")])
    result = runner.invoke(
        app, ["plot", str(r), "--columns", "peak", "-o", str(tmp_path / "o.html")]
    )
    assert result.exit_code == 0, _text(result)
    assert captured["metric"] == "peak"


def test_plot_metric_flag_removed(tmp_path):
    """--metric is gone (pre-1.0 rename to --columns, matching compare)."""
    r = write_run(tmp_path / "r.json", [bm("x")])
    result = runner.invoke(
        app, ["plot", str(r), "--metric", "peak", "-o", str(tmp_path / "o.html")]
    )
    assert result.exit_code == 2
    assert "No such option" in _text(result)


def test_plot_columns_rejects_multiple_metrics(tmp_path):
    """A plot has one value axis — multiple metrics is a clean usage error, not a crash."""
    r = write_run(tmp_path / "r.json", [bm("x")])
    result = runner.invoke(
        app, ["plot", str(r), "--columns", "time,peak", "-o", str(tmp_path / "o.html")]
    )
    assert result.exit_code == 2
    assert "not one of" in _text(result) or "Invalid value" in _text(result)


def test_plot_free_axes_rejects_bad_choice(tmp_path):
    r = write_run(tmp_path / "r.json", [bm("x")])
    result = runner.invoke(
        app, ["plot", str(r), "--free-axes", "diagonal", "-o", str(tmp_path / "o.html")]
    )
    assert result.exit_code == 2  # typer rejects an out-of-choice value


def test_plot_where_malformed_exits_2(tmp_path):
    r = write_run(tmp_path / "r.json", [bm("x")])
    result = runner.invoke(
        app, ["plot", str(r), "--where", "noequals", "-o", str(tmp_path / "o.html")]
    )
    assert result.exit_code == 2
    assert "KEY=VALUE" in _text(result)


def test_plot_unknown_view_exits_2(tmp_path):
    r = write_run(tmp_path / "r.json", [bm("x")])
    result = runner.invoke(app, ["plot", str(r), "--view", "bogus", "-o", str(tmp_path / "o.html")])
    assert result.exit_code == 2
    assert "unknown view" in _text(result)


def test_plot_where_parses_into_dict(tmp_path, capture_view):
    captured = capture_view()
    r = write_run(tmp_path / "r.json", [bm("x")])
    out = str(tmp_path / "o.html")
    result = runner.invoke(
        app,
        ["plot", str(r), "--where", "axis=n", "--where", "solver=glpk", "-o", out],
    )
    assert result.exit_code == 0, _text(result)
    assert captured["where"] == {"axis": "n", "solver": "glpk"}


def test_plot_free_axes_threads_through(tmp_path, capture_view):
    captured = capture_view()
    r = write_run(tmp_path / "r.json", [bm("x")])
    out = str(tmp_path / "o.html")
    result = runner.invoke(app, ["plot", str(r), "--free-axes", "y", "-o", out])
    assert result.exit_code == 0, _text(result)
    assert captured["free_axes"] == "y"  # str-enum value, matches the Literal


def test_plot_color_threads_through(tmp_path, capture_view):
    captured = capture_view()
    r = write_run(tmp_path / "r.json", [bm("x")])
    out = str(tmp_path / "o.html")
    result = runner.invoke(app, ["plot", str(r), "--color", "variant", "-o", out])
    assert result.exit_code == 0, _text(result)
    assert captured["color"] == "variant"


def test_plot_log_flags_thread_through(tmp_path, capture_view):
    captured = capture_view()
    r = write_run(tmp_path / "r.json", [bm("x")])
    out = str(tmp_path / "o.html")
    # the shared flag threads as log_log; per-axis flags thread separately and the API
    # resolves precedence (log_y=False wins over log_log=True for the y-axis)
    result = runner.invoke(
        app, ["plot", str(r), "--log-log", "--linear-y", "--no-y-zero", "-o", out]
    )
    assert result.exit_code == 0, _text(result)
    assert captured["log_log"] is True  # from --log-log
    assert captured["log_x"] == "auto"  # unset per-axis
    assert captured["log_y"] is False  # from --linear-y
    assert captured["y_zero"] is False


def test_plot_axis_flags_default_to_auto(tmp_path, capture_view):
    captured = capture_view()
    r = write_run(tmp_path / "r.json", [bm("x")])
    out = str(tmp_path / "o.html")
    result = runner.invoke(app, ["plot", str(r), "-o", out])
    assert result.exit_code == 0, _text(result)
    assert captured["log_x"] == captured["log_y"] == captured["y_zero"] == "auto"


def test_plot_missing_file_exits_2(tmp_path):
    result = runner.invoke(app, ["plot", str(tmp_path / "nope.json")])
    assert result.exit_code == 2
    assert "missing" in _text(result)


def _stub_view(plotting_mod, monkeypatch, fig):
    """Point every plot_* view at a stub returning ``fig``, so -o export is what's exercised."""
    for name in ("plot_compare", "plot_scatter", "plot_sweep", "plot_scaling"):
        monkeypatch.setattr(plotting_mod, name, lambda *a, _f=fig, **k: (_f, 1))


def test_plot_image_suffix_calls_write_image(tmp_path, monkeypatch):
    """An image suffix routes through write_image (kaleido) instead of write_html."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    fig = _FakeFig()
    _stub_view(plotting, monkeypatch, fig)
    r = write_run(tmp_path / "r.json", [bm("x")])
    out = tmp_path / "out.png"
    result = runner.invoke(app, ["plot", str(r), "-o", str(out)])
    assert result.exit_code == 0, _text(result)
    assert fig.kind == "image" and fig.path == out


def test_plot_image_suffix_without_kaleido_exits_2(tmp_path, monkeypatch):
    """A static suffix without kaleido is a clean error naming the extra, not a crash."""
    # plotly present (plot gate passes), kaleido absent (image gate fails).
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: None if name == "kaleido" else object(),
    )
    _stub_view(plotting, monkeypatch, _FakeFig())
    r = write_run(tmp_path / "r.json", [bm("x")])
    result = runner.invoke(app, ["plot", str(r), "-o", str(tmp_path / "out.png")])
    assert result.exit_code == 2
    assert "kaleido" in _text(result) and "plot-static" in _text(result)


def test_plot_unsupported_suffix_exits_2(tmp_path, monkeypatch):
    """A typo'd suffix is rejected rather than silently written as HTML."""
    _stub_view(plotting, monkeypatch, _FakeFig())
    r = write_run(tmp_path / "r.json", [bm("x")])
    result = runner.invoke(app, ["plot", str(r), "-o", str(tmp_path / "out.pong")])
    assert result.exit_code == 2
    assert "unsupported output suffix" in _text(result)


def test_plot_html_suffix_calls_write_html(tmp_path, monkeypatch):
    fig = _FakeFig()
    _stub_view(plotting, monkeypatch, fig)
    r = write_run(tmp_path / "r.json", [bm("x")])
    result = runner.invoke(app, ["plot", str(r), "-o", str(tmp_path / "out.html")])
    assert result.exit_code == 0, _text(result)
    assert fig.kind == "html"


def test_plot_value_error_exits_1(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise ValueError("no ids in common")

    monkeypatch.setattr(plotting, "plot_scaling", boom)
    r = write_run(tmp_path / "r.json", [bm("x")])
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
    r = write_run(tmp_path / "r.json", [bm("x")])
    result = runner.invoke(app, ["plot", str(r), "-o", str(tmp_path / "o.html")])
    assert result.exit_code == 2
    assert "pytest-benchmem[plot]" in _text(result)


# --- sweep -----------------------------------------------------------------------


def _patch_sweep(monkeypatch, tmp_path, *, failed=(), returncode=0, json_content=None):
    """Stub the sweep engine + subprocess so no uv/network is touched.

    Records the call into the returned dict; the fake engine runs the CLI's ``run``
    callback against one fake Venv per version, and the fake subprocess exits with
    ``returncode`` after writing ``json_content`` (a one-benchmark run by default)
    to the JSON path the callback expects (so ``produced`` is populated).
    """
    import pytest_benchmem.sweep as sweepmod

    captured: dict[str, Any] = {"cmds": []}
    content = '{"benchmarks": [{"name": "t"}]}' if json_content is None else json_content

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
                path.write_text(content)

        return SimpleNamespace(returncode=returncode)

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


@pytest.mark.parametrize(
    ("flags", "expected_pin"),
    [
        (["--memory"], "pytest-benchmem"),  # memory pass needs the plugin in the venv
        ([], "pytest-benchmark"),  # plain run only needs the benchmark harness
    ],
)
def test_sweep_auto_pins_harness(tmp_path, monkeypatch, flags, expected_pin):
    captured = _patch_sweep(monkeypatch, tmp_path)
    result = runner.invoke(
        app,
        ["sweep", "mypkg", "1.2.0", "--suite", "b/", "--out", str(tmp_path / "o"), *flags],
    )
    assert result.exit_code == 0, _text(result)
    assert captured["pins"] == (expected_pin,)


def test_sweep_user_pin_overrides_auto_harness(tmp_path, monkeypatch):
    captured = _patch_sweep(monkeypatch, tmp_path)
    result = runner.invoke(
        app,
        [
            "sweep",
            "mypkg",
            "1.2.0",
            "--suite",
            "b/",
            "--out",
            str(tmp_path / "o"),
            "--memory",
            "--pin",
            "pytest_benchmem==0.4.0",  # normalized name matches → no duplicate auto-pin
        ],
    )
    assert result.exit_code == 0, _text(result)
    assert captured["pins"] == ("pytest_benchmem==0.4.0",)


def test_sweep_resolves_relative_out_against_invocation_cwd(tmp_path, monkeypatch):
    _patch_sweep(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["sweep", "mypkg", "1.2.0", "--suite", "b/", "--out", "o"])
    assert result.exit_code == 0, _text(result)
    assert (tmp_path / "o" / "1.2.0.json").exists()


def test_sweep_copies_suite_dir_and_repoints_the_pytest_arg(tmp_path, monkeypatch):
    captured = _patch_sweep(monkeypatch, tmp_path)
    suite = tmp_path / "bench"
    suite.mkdir()
    result = runner.invoke(
        app,
        ["sweep", "mypkg", "1.2.0", "--suite", str(suite), "--out", str(tmp_path / "o")],
    )
    assert result.exit_code == 0, _text(result)
    # the suite dir becomes the copy_dir; pytest gets the path of the copy (its basename)
    assert captured["copy_dir"] == suite
    assert captured["cmds"][0][3] == "bench"


def test_sweep_copies_a_suite_files_parent_dir(tmp_path, monkeypatch):
    captured = _patch_sweep(monkeypatch, tmp_path)
    suite = tmp_path / "bench" / "test_speed.py"
    suite.parent.mkdir()
    suite.write_text("")
    result = runner.invoke(
        app,
        ["sweep", "mypkg", "1.2.0", "--suite", str(suite), "--out", str(tmp_path / "o")],
    )
    assert result.exit_code == 0, _text(result)
    assert captured["copy_dir"] == suite.parent
    assert captured["cmds"][0][3] == str(Path("bench") / "test_speed.py")


def test_sweep_repoints_suite_inside_an_explicit_copy_dir(tmp_path, monkeypatch):
    captured = _patch_sweep(monkeypatch, tmp_path)
    (tmp_path / "proj" / "bench").mkdir(parents=True)
    result = runner.invoke(
        app,
        [
            "sweep",
            "mypkg",
            "1.2.0",
            "--suite",
            str(tmp_path / "proj" / "bench"),
            "--copy-dir",
            str(tmp_path / "proj"),
            "--out",
            str(tmp_path / "o"),
        ],
    )
    assert result.exit_code == 0, _text(result)
    assert captured["copy_dir"] == tmp_path / "proj"
    assert captured["cmds"][0][3] == str(Path("proj") / "bench")


def test_sweep_passes_a_nonlocal_suite_through_verbatim(tmp_path, monkeypatch):
    captured = _patch_sweep(monkeypatch, tmp_path)
    result = runner.invoke(
        app,
        ["sweep", "mypkg", "1.2.0", "--suite", "nonexistent/", "--out", str(tmp_path / "o")],
    )
    assert result.exit_code == 0, _text(result)
    assert captured["copy_dir"] is None
    assert captured["cmds"][0][3] == "nonexistent"


@pytest.mark.parametrize(
    "stub_kw",
    [
        {"returncode": 1},  # pytest failed
        {"json_content": "{}"},  # pytest "succeeded" but the run has no benchmarks
        {"json_content": ""},  # 0-byte file — pytest crashed before writing
    ],
)
def test_sweep_exits_1_when_a_run_yields_no_benchmark_data(tmp_path, monkeypatch, stub_kw):
    _patch_sweep(monkeypatch, tmp_path, **stub_kw)
    result = runner.invoke(
        app,
        ["sweep", "mypkg", "1.2.0", "--suite", "b/", "--out", str(tmp_path / "o")],
    )
    assert result.exit_code == 1, _text(result)
    assert "no benchmark data from 1.2.0" in _text(result)
    assert "benchmem compare" not in result.output  # no green next-step hint for a dead run


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


@pytest.mark.parametrize(
    "args, needles",
    [
        ([], ["test_big", "test_small"]),  # ambiguous: no id given → lists what's available
        (["nope"], ["no profile matches"]),  # id resolves to nothing
        (["test_big", "--worst", "peak"], ["not both"]),  # id and --worst are mutually exclusive
        (["test_big", "--report", "bogus"], ["unknown reporter"]),
    ],
)
def test_flamegraph_usage_errors(profiles, args, needles):
    result = runner.invoke(app, ["flamegraph", str(profiles), *args])
    assert result.exit_code == 2
    text = _text(result)
    assert all(nd in text for nd in needles)


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
