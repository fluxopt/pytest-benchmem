"""pytest-benchmem CLI — ``plot`` / ``compare`` / ``sweep`` / ``flamegraph``.

``plot`` and ``compare`` read the JSON pytest-benchmark writes (``.benchmarks/…``) over the same
metrics: ``time`` from ``stats``; the rest from ``extra_info.benchmem`` — ``peak``,
``allocated``, ``allocations``, and ``rss`` (whole-process resident, isolated runs only).
Both select with ``--columns`` — ``plot`` takes one
(a single value axis); ``compare`` shows several side by side (default all).
``--stat`` reports a distribution over a metric's per-repeat series (e.g. ``peak
--stat max`` is the worst peak). Timing comparison/histograms are pytest-benchmark's
own job; these commands are the memory-aware, dims-aware views on top.

``flamegraph`` works on the kept ``.bin`` profiles from ``--benchmark-memory-profile`` instead:
it resolves the profile for a test (or ``--worst``) and renders it through memray in one step.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import typer

from pytest_benchmem.snapshot import Metric, discover_runs

if TYPE_CHECKING:
    from plotly.graph_objects import Figure

#: Which facet axes to unmatch from the shared default (see ``benchmem plot``).
FreeAxes = Literal["x", "y", "both"]

#: Scaling-plot spread whiskers (min…max of each point's per-pass series).
Band = Literal["auto", "minmax", "none"]

app = typer.Typer(help="pytest-benchmem — plot and compare benchmark runs.", no_args_is_help=True)

MetricOpt = Annotated[
    Metric,
    typer.Option(
        "--columns",
        help="Metric to plot: time | peak | allocated | allocations | rss (rss = isolated runs "
        "only). One per figure (a plot "
        "has a single value axis) — same flag as `compare`; the spread shows as whiskers via "
        "--band.",
    ),
]


def _fail(msg: str, code: int = 1) -> typer.Exit:
    """Print ``msg`` in red to stderr; return a :class:`typer.Exit` for the caller to raise."""
    typer.secho(msg, fg=typer.colors.RED, err=True)
    return typer.Exit(code=code)


def _require_runs_exist(runs: list[Path], *, suggest: bool) -> None:
    """Exit(2) if any run file is missing — ``suggest`` also lists the discoverable runs."""
    missing = [p for p in runs if not p.exists()]
    if not missing:
        return
    typer.secho(f"missing: {[str(p) for p in missing]}", fg=typer.colors.RED, err=True)
    if suggest and (found := discover_runs()):
        typer.echo("available:\n  " + "\n  ".join(str(p) for p in found), err=True)
    raise typer.Exit(code=2)


@contextmanager
def _exit_on_value_error(code: int = 1) -> Iterator[None]:
    """Turn a ``ValueError`` from the wrapped block into a red message + ``Exit(code)``."""
    try:
        yield
    except ValueError as exc:
        raise _fail(str(exc), code) from exc


def _need_plotly() -> None:
    if importlib.util.find_spec("plotly") is None:
        raise _fail("plotting needs extras: pip install 'pytest-benchmem[plot]'", 2)


# Static raster/vector suffixes go through kaleido's write_image; .html (or a bare name) stays
# interactive HTML. Anything else is a typo we refuse rather than silently writing HTML.
_IMAGE_SUFFIXES = frozenset({".png", ".svg", ".pdf", ".jpg", ".jpeg", ".webp"})
_HTML_SUFFIXES = frozenset({"", ".html", ".htm"})


def _write_figure(fig: Figure, output: Path) -> None:
    """Export ``fig`` to ``output``, choosing write_image vs write_html by the suffix.

    Image suffixes need kaleido (the ``[plot-static]`` extra); raise a clear Exit(2) naming
    the install when it is absent. An unrecognised suffix is rejected rather than silently
    written as HTML.
    """
    suffix = output.suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        if importlib.util.find_spec("kaleido") is None:
            raise _fail(
                f"{suffix} export needs kaleido: pip install 'pytest-benchmem[plot-static]' "
                f"(or use an .html output for the interactive plot)",
                2,
            )
        fig.write_image(output)
    elif suffix in _HTML_SUFFIXES:
        fig.write_html(output)
    else:
        supported = ", ".join(sorted(_IMAGE_SUFFIXES | {".html"}))
        raise _fail(f"unsupported output suffix {suffix!r}; use one of: {supported}", 2)


def _parse_where(items: list[str] | None) -> dict[str, str] | None:
    """Parse repeatable ``KEY=VALUE`` filters into a dict; Exit(2) on a malformed entry."""
    if not items:
        return None
    where: dict[str, str] = {}
    for item in items:
        key, sep, val = item.partition("=")
        if not sep or not key:
            raise _fail(f"--where expects KEY=VALUE, got {item!r}", 2)
        where[key] = val
    return where


@app.command()
def plot(
    runs: Annotated[list[Path], typer.Argument(help="pytest-benchmark JSON file(s).")],
    metric: MetricOpt = "time",
    view: Annotated[
        str | None,
        typer.Option(help="compare | scatter | sweep | scaling (default: by count)."),
    ] = None,
    facet: Annotated[str | None, typer.Option(help="Dim to facet by.")] = None,
    pivot: Annotated[
        str | None,
        typer.Option(
            "--pivot",
            help="Comparison axis for --view compare/scatter: fold a single run along this dim "
            "instead of across run-files (param:NAME or a bare extra_info name); its values "
            "become the compared series. Like --group-by but it sets what's *compared*, not how "
            "rows cluster. Mutually exclusive with multiple runs.",
        ),
    ] = None,
    x: Annotated[str | None, typer.Option(help="scaling: dim for the x-axis.")] = None,
    clip: Annotated[float | None, typer.Option(help="Clamp the colour scale.")] = None,
    where: Annotated[
        list[str] | None,
        typer.Option("--where", help="Filter rows by dim: KEY=VALUE (repeatable, AND-combined)."),
    ] = None,
    free_axes: Annotated[
        FreeAxes | None,
        typer.Option("--free-axes", help="Free facet axes: x | y | both (needs --facet)."),
    ] = None,
    band: Annotated[
        Band,
        typer.Option(
            "--band",
            help="scaling: spread whiskers on memory metrics — auto | minmax | none.",
        ),
    ] = "auto",
    label: Annotated[
        list[str] | None,
        typer.Option(
            "--label", "-l", help="Series label per run, in order (repeat). Default: stem."
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Out file; .html is interactive, .png/.svg/.pdf/.jpg/.webp export a static image.",
        ),
    ] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = False,
) -> None:
    """Render an interactive plotly view from one or more pytest-benchmark runs."""
    _require_runs_exist(runs, suggest=True)

    # --pivot's natural home is the A/B compare view, so when --view is unset it defaults there
    # (otherwise one run would default to scaling, which has no series axis to pivot). An explicit
    # --view still wins in both cases; the guard below rejects a non-paired view under --pivot.
    if pivot is not None:
        chosen = view or "compare"
    else:
        chosen = view or ("scaling" if len(runs) == 1 else "scatter" if len(runs) == 2 else "sweep")
    # --pivot re-points the series axis at a dim; only the paired views (compare/scatter) have a
    # series axis to re-point. For scaling/sweep the dim is a normal x/colour/facet axis.
    if pivot is not None and chosen not in ("compare", "scatter"):
        raise _fail(
            f"--pivot re-points the comparison series and applies to --view compare or scatter, "
            f"not {chosen!r}; for scaling/sweep use --x / --facet to place the dim.",
            2,
        )
    _need_plotly()
    from pytest_benchmem import plotting

    labels = label or None
    filters = _parse_where(where)
    with _exit_on_value_error():
        if chosen == "compare":
            fig, n = plotting.plot_compare(
                runs,
                metric=metric,
                facet=facet,
                clip=clip,
                where=filters,
                free_axes=free_axes,
                labels=labels,
                pivot=pivot,
            )
        elif chosen == "scatter":
            fig, n = plotting.plot_scatter(
                runs,
                metric=metric,
                facet=facet,
                clip=clip,
                where=filters,
                free_axes=free_axes,
                labels=labels,
                pivot=pivot,
            )
        elif chosen == "sweep":
            fig, n = plotting.plot_sweep(
                runs, metric=metric, clip=clip, where=filters, labels=labels
            )
        elif chosen == "scaling":
            fig, n = plotting.plot_scaling(
                runs,
                metric=metric,
                x=x,
                facet=facet,
                band=band,
                where=filters,
                free_axes=free_axes,
                labels=labels,
            )
        else:
            raise _fail(f"unknown view {chosen!r}", 2)

    output = output or Path(".benchmarks") / "plots" / f"{chosen}-{metric}.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_figure(fig, output)
    typer.secho(f"{chosen} ({metric}): {n} ids → {output}", fg=typer.colors.GREEN)
    if open_browser:
        import webbrowser

        webbrowser.open(output.resolve().as_uri())


@app.command()
def compare(
    runs: Annotated[
        list[Path],
        typer.Argument(
            help="One or more pytest-benchmark runs, oldest → newest. One prints a plain "
            "table; two or more compare (a sweep is N)."
        ),
    ],
    columns: Annotated[
        str | None,
        typer.Option(
            "--columns",
            help="Comma list of metrics: time | peak | allocated | allocations | rss "
            "(rss = isolated runs only; e.g. peak or time,peak,rss). Default: time,peak. "
            "Each is shown across "
            "every --stat; a metric absent from every run is dropped.",
        ),
    ] = None,
    group_by: Annotated[
        str,
        typer.Option(
            "--group-by",
            help="Group rows into sub-tables: fullname | name | func | group | module | class | "
            "param:NAME (comma-composable).",
        ),
    ] = "fullname",
    stat: Annotated[
        str | None,
        typer.Option(
            help="Which stat column(s) per metric: min | max | mean | median | stddev, or "
            "all (the default) for the full spread side by side.",
        ),
    ] = None,
    sort: Annotated[
        str,
        typer.Option(help="Row order: name (id) | value (largest in the last run) | change."),
    ] = "name",
    pivot: Annotated[
        str | None,
        typer.Option(
            "--pivot",
            help="Comparison axis: fold a single run along this dim instead of across run-files "
            "— param:NAME or a bare extra_info name. Rows differing only in it pair up and its "
            "values become the compared series. Like --group-by but it sets what's *compared*, "
            "not how rows cluster. Mutually exclusive with multiple runs.",
        ),
    ] = None,
    csv: Annotated[
        Path | None,
        typer.Option(help="Also write the raw (unscaled) comparison to this CSV file."),
    ] = None,
    fail_on: Annotated[
        list[str] | None,
        typer.Option(
            "--fail-on",
            help="Exit non-zero on a regression of the first run vs the last (or, with --pivot, "
            "the first dim value vs the last). FIELD:THRESHOLD, repeatable — e.g. --fail-on "
            "peak:10% --fail-on peak:5MiB --fail-on rss:10% (rss gates only isolated runs).",
        ),
    ] = None,
) -> None:
    """Print a per-id table for one run, or compare two or more (and optionally gate CI)."""
    if not runs:
        raise _fail("compare needs at least one run", 2)
    # A growth gate needs a base and a head: two runs, or one run folded along --pivot (which
    # supplies the two sides from one file). Without either, refuse rather than silently pass.
    if fail_on and len(runs) < 2 and pivot is None:  # noqa: PLR2004
        raise _fail(
            "compare --fail-on needs at least two runs — it gates growth of the first run vs "
            "the last. To gate one combined run, add --pivot DIM (first dim value vs last); for "
            "an absolute ceiling, use the @pytest.mark.benchmem(max_peak=...) marker instead.",
            2,
        )
    _require_runs_exist(runs, suggest=False)
    from pytest_benchmem.compare import (
        compare_runs,
        find_pivot_regressions,
        find_regressions,
        parse_threshold,
    )

    with _exit_on_value_error():
        compare_runs(
            runs, columns=columns, group_by=group_by, stat=stat, sort=sort, pivot=pivot, csv=csv
        )

    if not fail_on:
        return
    with _exit_on_value_error(code=2):
        thresholds = [parse_threshold(expr) for expr in fail_on]

    # Gate base vs head: the first run vs the last (oldest vs newest in a sweep), or — with
    # --pivot — the first value of the dim vs the last, folded out of the one run.
    with _exit_on_value_error(code=2):  # e.g. an rss gate against non-isolated runs
        regressions = (
            find_pivot_regressions(runs[0], pivot, thresholds)
            if pivot is not None
            else find_regressions(runs[0], runs[-1], thresholds)
        )
    if regressions:
        typer.secho(f"{len(regressions)} regression(s) over threshold:", fg=typer.colors.RED)
        for reg in regressions:
            typer.secho(reg.format(), fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho("no regressions over thresholds", fg=typer.colors.GREEN)


@app.command()
def sweep(
    package: Annotated[
        str,
        typer.Argument(help="Package under test; each plain version installs `<package>==<v>`."),
    ],
    versions: Annotated[
        list[str],
        typer.Argument(
            help="Versions or pip specs to sweep, e.g. 1.2.0 1.3.0 git+https://github.com/me/pkg@main."
        ),
    ],
    suite: Annotated[
        Path,
        typer.Option(help="Benchmark suite (dir or file) to run in each version's venv."),
    ],
    out: Annotated[
        Path,
        typer.Option(help="Directory for the per-version JSON runs."),
    ] = Path(".benchmarks/sweep"),
    memory: Annotated[
        bool,
        typer.Option("--memory/--no-memory", help="Add --benchmark-memory to each pytest run."),
    ] = False,
    pytest_arg: Annotated[
        list[str] | None,
        typer.Option(
            "--pytest-arg",
            help="Arg forwarded to pytest, one token each, repeatable (e.g. --pytest-arg=-k).",
        ),
    ] = None,
    pins: Annotated[
        list[str] | None,
        typer.Option("--pin", help="Extra pip spec installed alongside (repeatable)."),
    ] = None,
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="YYYY-MM-DD for uv --exclude-newer (reproducible resolve)."),
    ] = None,
    import_check: Annotated[
        str | None,
        typer.Option(help="Module asserted to resolve to the venv (isolation preflight)."),
    ] = None,
    copy_dir: Annotated[
        Path | None,
        typer.Option(help="Directory copied into each venv's cwd (the suite imports from here)."),
    ] = None,
) -> None:
    """Run a benchmark suite across several installed versions of a package.

    Provisions one fresh uv venv per version, runs 'pytest <suite> --benchmark-only'
    in each writing <out>/<version>.json, then prints the next step. --memory adds
    the memory pass; forward any other pytest flag with --pytest-arg, e.g.
    benchmem sweep mypkg 1.2.0 1.3.0 --suite benchmarks/ --memory --pytest-arg=-k.
    """
    if not versions:
        raise _fail("sweep needs at least one version", 2)
    from pytest_benchmem.sweep import sweep as run_sweep
    from pytest_benchmem.sweep import version_label

    out.mkdir(parents=True, exist_ok=True)
    extra = (["--benchmark-memory"] if memory else []) + list(pytest_arg or [])
    produced: list[Path] = []

    def run(venv: object) -> None:
        v = venv  # a sweep.Venv (python/env/cwd resolved)
        json_path = out / f"{version_label(v.version)}.json"  # type: ignore[attr-defined]
        cmd = [
            str(v.python),  # type: ignore[attr-defined]
            "-m",
            "pytest",
            str(suite),
            "--benchmark-only",
            f"--benchmark-json={json_path}",
            *extra,
        ]
        typer.secho(f"sweep[{v.version}]: {' '.join(cmd)}", fg=typer.colors.BLUE)  # type: ignore[attr-defined]
        subprocess.run(cmd, cwd=v.cwd, env=v.env, check=False)  # type: ignore[attr-defined]
        if json_path.exists():
            produced.append(json_path)

    failed = run_sweep(
        versions,
        run,
        install_spec=lambda v: f"{package}=={v}",
        pins=tuple(pins or ()),
        copy_dir=copy_dir,
        import_check=import_check,
        as_of=as_of,
    )

    if produced:
        files = " ".join(str(p) for p in produced)
        typer.secho(f"sweep: wrote {len(produced)} run(s) under {out}/", fg=typer.colors.GREEN)
        typer.echo(f"  compare: benchmem compare {files}")
        typer.echo(f"  plot:    benchmem plot {files} --columns peak")
    if failed:
        raise _fail(f"failed to provision: {', '.join(failed)}", 1)


# --- flamegraph: render a kept --benchmark-memory-profile .bin ----------------------

#: memray reporters that emit an HTML file (we pass ``-o`` and can ``--open`` the result);
#: the rest (``tree`` / ``summary`` / ``stats``) print to the terminal.
_HTML_REPORTS = frozenset({"flamegraph", "table"})
_REPORTS = (*sorted(_HTML_REPORTS), "tree", "summary", "stats")

#: ``--worst`` metrics readable straight from a ``.bin`` via memray's own stats — no run JSON
#: needed. (``rss`` is whole-process and isolated runs keep no ``.bin``, so it's not here.)
_BIN_METRICS = {
    "peak": "peak_memory_allocated",
    "allocated": "total_memory_allocated",
    "allocations": "total_num_allocations",
}


def _need_memray() -> None:
    if importlib.util.find_spec("memray") is None:
        raise _fail("flamegraph needs memray (Linux/macOS): pip install memray", 2)


def _bin_metric(binp: Path, metric: str) -> int:
    """One metric value read straight from a ``.bin`` (the same numbers ``memray stats`` shows)."""
    from memray._memray import compute_statistics

    s = compute_statistics(str(binp))
    return int(getattr(s, _BIN_METRICS[metric]))


def _has_native_traces(binp: Path) -> bool:
    import memray

    return bool(memray.FileReader(str(binp)).metadata.has_native_traces)


def _resolve_bin(profile_dir: Path, test_id: str | None, worst: str | None) -> Path:
    """Pick the one ``.bin`` to render: by ``test_id`` (exact sanitized stem, else unique
    substring), or the heaviest by ``--worst`` metric, or the sole profile if there's only one.
    Exits with the available ids listed when the choice is missing or ambiguous.
    """
    from pytest_benchmem.pytest_plugin import _sanitize_id

    bins = sorted(profile_dir.glob("*.bin"))
    if not bins:
        raise _fail(
            f"no .bin profiles in {profile_dir} — run pytest with "
            f"--benchmark-memory-profile={profile_dir} first.",
            2,
        )
    avail = "available:\n  " + "\n  ".join(b.stem for b in bins)

    if test_id is not None:
        want = _sanitize_id(test_id)
        exact = profile_dir / f"{want}.bin"
        if exact.exists():
            return exact
        matches = [b for b in bins if want in b.stem]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise _fail(f"no profile matches {test_id!r}.\n{avail}", 2)
        hit = "\n  ".join(b.stem for b in matches)
        raise _fail(f"{test_id!r} matches several profiles — be more specific:\n  {hit}", 2)

    if worst is not None:
        if worst not in _BIN_METRICS:
            raise _fail(f"--worst: unknown metric {worst!r} (use {', '.join(_BIN_METRICS)})", 2)
        return max(bins, key=lambda b: _bin_metric(b, worst))

    if len(bins) == 1:
        return bins[0]
    raise _fail(f"which profile? pass a TEST_ID or --worst <metric>.\n{avail}", 2)


@app.command()
def flamegraph(
    profile_dir: Annotated[
        Path, typer.Argument(help="Directory of kept .bin profiles (--benchmark-memory-profile).")
    ],
    test_id: Annotated[
        str | None,
        typer.Argument(help="Test id (exact, or a unique substring) to render; omit with --worst."),
    ] = None,
    worst: Annotated[
        str | None,
        typer.Option("--worst", help="Auto-pick the heaviest: peak | allocated | allocations"),
    ] = None,
    report: Annotated[
        str,
        typer.Option("--report", help=f"memray reporter: {' | '.join(_REPORTS)}"),
    ] = "flamegraph",
    native: Annotated[
        bool,
        typer.Option(
            "--native/--no-native",
            help="Require the profile to carry native traces (captured via "
            "--benchmark-memory-profile-native); error if it doesn't.",
        ),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="HTML out path (default: next to the .bin)."),
    ] = None,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the rendered HTML.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Overwrite an existing render.")
    ] = False,
) -> None:
    """Render a kept memory profile in one step — resolve the ``.bin`` for a test and run memray.

    Closes the "regressed → *where*?" loop after ``--benchmark-memory-profile``: instead of
    finding the right ``.bin`` and remembering the memray subcommand, point at the profile dir
    and name the test (or ``--worst peak`` to auto-pick the heaviest). Defaults to an HTML
    flamegraph written next to the ``.bin``; ``--report tree|summary|stats`` prints to the
    terminal instead.
    """
    _need_memray()
    if test_id is not None and worst is not None:
        raise _fail("pass a TEST_ID or --worst <metric>, not both.", 2)
    if report not in _REPORTS:
        raise _fail(f"--report: unknown reporter {report!r} (use {', '.join(_REPORTS)})", 2)
    if not profile_dir.is_dir():
        raise _fail(f"not a directory: {profile_dir}", 2)

    binp = _resolve_bin(profile_dir, test_id, worst)
    if native and not _has_native_traces(binp):
        raise _fail(
            f"{binp.name} has no native traces — re-run with "
            "--benchmark-memory-profile-native to attribute C/Rust frames.",
            2,
        )

    cmd = [sys.executable, "-m", "memray", report]
    is_html = report in _HTML_REPORTS
    out_path: Path | None = None
    if is_html:
        out_path = output or binp.with_name(f"{binp.stem}.{report}.html")
        cmd += ["-o", str(out_path)]
        if force:
            cmd.append("-f")
    elif output is not None or open_browser:
        typer.secho(
            f"--output/--open ignored for terminal report {report!r}", fg=typer.colors.YELLOW
        )
    cmd.append(str(binp))

    kind = "native" if _has_native_traces(binp) else "python-only"
    typer.secho(f"rendering {binp.name} ({kind}) → {report}", fg=typer.colors.BLUE)
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise _fail(f"memray {report} failed (exit {result.returncode})", result.returncode)

    if out_path is not None:
        typer.secho(f"wrote {out_path}", fg=typer.colors.GREEN)
        if open_browser:
            typer.launch(str(out_path))
