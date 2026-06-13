"""pytest-benchmem CLI — ``plot`` and ``compare`` over pytest-benchmark JSON runs.

Both commands read the JSON pytest-benchmark writes (``.benchmarks/…``) and pick
a ``--metric`` (``time`` from ``stats``, ``memory`` from ``extra_info.peak_mib``).
Timing comparison/histograms are pytest-benchmark's own job; these commands are
the memory-aware, dims-aware views on top.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Annotated

import typer

from pytest_benchmem.snapshot import Metric, discover_runs

app = typer.Typer(help="pytest-benchmem — plot and compare benchmark runs.", no_args_is_help=True)

MetricOpt = Annotated[Metric, typer.Option(help="Which metric to read: time | memory.")]


def _need_plotly() -> None:
    if importlib.util.find_spec("plotly") is None:
        typer.secho(
            "plotting needs extras: pip install 'pytest-benchmem[plot]'",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)


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
    output: Annotated[Path | None, typer.Option("--output", "-o", help="HTML out.")] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = False,
) -> None:
    """Render an interactive plotly view from one or more pytest-benchmark runs."""
    missing = [p for p in runs if not p.exists()]
    if missing:
        typer.secho(f"missing: {[str(p) for p in missing]}", fg=typer.colors.RED, err=True)
        found = discover_runs()
        if found:
            typer.echo("available:\n  " + "\n  ".join(str(p) for p in found), err=True)
        raise typer.Exit(code=2)

    chosen = view or ("scaling" if len(runs) == 1 else "scatter" if len(runs) == 2 else "sweep")
    _need_plotly()
    from pytest_benchmem import plotting

    try:
        if chosen == "compare":
            fig, n = plotting.plot_compare(runs, metric=metric, facet=facet, clip=clip)
        elif chosen == "scatter":
            fig, n = plotting.plot_scatter(runs, metric=metric, facet=facet, clip=clip)
        elif chosen == "sweep":
            fig, n = plotting.plot_sweep(runs, metric=metric, clip=clip)
        elif chosen == "scaling":
            fig, n = plotting.plot_scaling(runs, metric=metric, x=x, facet=facet)
        else:
            typer.secho(f"unknown view {chosen!r}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    output = output or Path(".benchmarks") / "plots" / f"{chosen}-{metric}.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(output)
    typer.secho(f"{chosen} ({metric}): {n} ids → {output}", fg=typer.colors.GREEN)
    if open_browser:
        import webbrowser

        webbrowser.open(output.resolve().as_uri())


@app.command()
def compare(
    a: Annotated[Path, typer.Argument(help="Baseline run.")],
    b: Annotated[Path, typer.Argument(help="Candidate run.")],
    metric: MetricOpt = "time",
    fail_on: Annotated[
        list[str] | None,
        typer.Option(
            "--fail-on",
            help="Exit non-zero on a regression. FIELD:THRESHOLD, repeatable — "
            "e.g. --fail-on peak:10% --fail-on allocations:5% --fail-on peak:5MiB.",
        ),
    ] = None,
) -> None:
    """Print a per-id delta table for two pytest-benchmark runs (and optionally gate CI)."""
    for p in (a, b):
        if not p.exists():
            typer.secho(f"missing: {p}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
    from pytest_benchmem.compare import compare_runs, find_regressions, parse_threshold

    try:
        compare_runs(a, b, metric=metric)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if not fail_on:
        return
    try:
        thresholds = [parse_threshold(expr) for expr in fail_on]
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    regressions = find_regressions(a, b, thresholds)
    if regressions:
        typer.secho(f"{len(regressions)} regression(s) over threshold:", fg=typer.colors.RED)
        for reg in regressions:
            typer.secho(reg.format(), fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho("no regressions over thresholds", fg=typer.colors.GREEN)


@app.command()
def scaling(
    runs: Annotated[
        list[Path], typer.Argument(help="pytest-benchmark JSON file (uses the first).")
    ],
    metric: MetricOpt = "time",
    x: Annotated[
        str | None, typer.Option(help="Numeric dim to fit against (default: the lone one).")
    ] = None,
) -> None:
    """Report the empirical scaling exponent (value ≈ c·nˣ) per benchmark family."""
    missing = [p for p in runs if not p.exists()]
    if missing:
        typer.secho(f"missing: {[str(p) for p in missing]}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    from pytest_benchmem.scaling import fit_power_law
    from pytest_benchmem.snapshot import load_long_df

    try:
        df, _unit = load_long_df(runs[:1], metric=metric)
        fits = fit_power_law(df, x=x)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if not fits:
        typer.secho("no families with ≥2 points to fit", fg=typer.colors.YELLOW)
        return

    typer.echo(f"\n{'family':<46} {'n':>3} {'fit':>11} {'R²':>7}   ({metric})")
    typer.echo("-" * 78)
    for f in fits:
        flag = "" if f.n >= 3 and f.r2 >= 0.95 else "  ⚠ thin/noisy"
        typer.echo(f"{f.family:<46} {f.n:>3}  O(n^{f.exponent:>4.2f}) {f.r2:>7.3f}{flag}")
