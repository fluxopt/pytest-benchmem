"""pytest-benchmem CLI — ``plot`` and ``compare`` over pytest-benchmark JSON runs.

Both commands read the JSON pytest-benchmark writes (``.benchmarks/…``) and pick
a ``--metric``: ``time`` from ``stats``; the rest from ``extra_info.benchmem`` —
``peak``, ``allocated``, and ``allocations``.
``--stat`` reports a distribution over a metric's per-repeat series (e.g. ``peak
--stat max`` is the worst peak). Timing comparison/histograms are pytest-benchmark's
own job; these commands are the memory-aware, dims-aware views on top.
"""

from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal

import typer

from pytest_benchmem.snapshot import Metric, discover_runs

#: Which facet axes to unmatch from the shared default (see ``benchmem plot``).
FreeAxes = Literal["x", "y", "both"]

#: Scaling-plot spread whiskers (min…max of each point's per-pass series).
Band = Literal["auto", "minmax", "none"]

app = typer.Typer(help="pytest-benchmem — plot and compare benchmark runs.", no_args_is_help=True)

MetricOpt = Annotated[
    Metric,
    typer.Option(
        help="Metric: time | peak | allocated | allocations (pair with --stat for a distribution)."
    ),
]

#: ``compare``'s ``--metric`` also accepts ``both`` (shorthand for ``--columns time,peak``).
CompareMetric = Literal["time", "peak", "allocated", "allocations", "both"]


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
    output: Annotated[Path | None, typer.Option("--output", "-o", help="HTML out.")] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = False,
) -> None:
    """Render an interactive plotly view from one or more pytest-benchmark runs."""
    _require_runs_exist(runs, suggest=True)

    chosen = view or ("scaling" if len(runs) == 1 else "scatter" if len(runs) == 2 else "sweep")
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
    fig.write_html(output)
    typer.secho(f"{chosen} ({metric}): {n} ids → {output}", fg=typer.colors.GREEN)
    if open_browser:
        import webbrowser

        webbrowser.open(output.resolve().as_uri())


@app.command()
def compare(
    runs: Annotated[
        list[Path],
        typer.Argument(help="Two or more pytest-benchmark runs, oldest → newest (a sweep is N)."),
    ],
    metric: Annotated[
        CompareMetric,
        typer.Option(
            help="Metric column(s): time | peak | allocated | allocations | both "
            "(both = time,peak). Overridden by --columns."
        ),
    ] = "time",
    columns: Annotated[
        str | None,
        typer.Option(
            "--columns", help="Comma list of metric columns (e.g. time,peak); overrides --metric."
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
            help="Distribution stat over each benchmark's per-repeat series "
            "(min | max | mean | median | stddev) for peak/allocated/allocations. "
            "Default: the headline value.",
        ),
    ] = None,
    sort: Annotated[
        str,
        typer.Option(help="Row order: name (id) | value (largest in the last run) | change."),
    ] = "name",
    csv: Annotated[
        Path | None,
        typer.Option(help="Also write the raw (unscaled) comparison to this CSV file."),
    ] = None,
    fail_on: Annotated[
        list[str] | None,
        typer.Option(
            "--fail-on",
            help="Exit non-zero on a regression of the first run vs the last. "
            "FIELD:THRESHOLD, repeatable — e.g. --fail-on peak:10% --fail-on peak:5MiB.",
        ),
    ] = None,
) -> None:
    """Print a per-id comparison table across two or more runs (and optionally gate CI)."""
    if len(runs) < 2:  # noqa: PLR2004 — a comparison needs two sides
        raise _fail("compare needs at least two runs", 2)
    _require_runs_exist(runs, suggest=False)
    from pytest_benchmem.compare import compare_runs, find_regressions, parse_threshold

    with _exit_on_value_error():
        compare_runs(
            runs, metric=metric, columns=columns, group_by=group_by, stat=stat, sort=sort, csv=csv
        )

    if not fail_on:
        return
    with _exit_on_value_error(code=2):
        thresholds = [parse_threshold(expr) for expr in fail_on]

    # Gate the first run (base) against the last (head) — oldest vs newest in a sweep.
    regressions = find_regressions(runs[0], runs[-1], thresholds)
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
        typer.echo(f"  compare: benchmem compare {files} --metric peak")
        typer.echo(f"  plot:    benchmem plot {files} --metric peak")
    if failed:
        raise _fail(f"failed to provision: {', '.join(failed)}", 1)
