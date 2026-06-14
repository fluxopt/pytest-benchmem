"""pytest-benchmem CLI — ``plot`` and ``compare`` over pytest-benchmark JSON runs.

Both commands read the JSON pytest-benchmark writes (``.benchmarks/…``) and pick
a ``--metric``: ``time`` from ``stats``; the rest from ``extra_info.benchmem`` —
``peak``, ``allocated``, ``allocations``, and ``memory`` as an alias for ``peak``.
``--stat`` reports a distribution over a metric's per-repeat series (e.g. ``peak
--stat max`` is the worst peak). Timing comparison/histograms are pytest-benchmark's
own job; these commands are the memory-aware, dims-aware views on top.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from pytest_benchmem.snapshot import Metric, discover_runs

app = typer.Typer(help="pytest-benchmem — plot and compare benchmark runs.", no_args_is_help=True)

MetricOpt = Annotated[
    Metric,
    typer.Option(
        help="Metric: time | peak | allocated | allocations | memory "
        "(memory is an alias of peak; pair with --stat for a distribution)."
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
    with _exit_on_value_error():
        if chosen == "compare":
            fig, n = plotting.plot_compare(
                runs, metric=metric, facet=facet, clip=clip, labels=labels
            )
        elif chosen == "scatter":
            fig, n = plotting.plot_scatter(
                runs, metric=metric, facet=facet, clip=clip, labels=labels
            )
        elif chosen == "sweep":
            fig, n = plotting.plot_sweep(runs, metric=metric, clip=clip, labels=labels)
        elif chosen == "scaling":
            fig, n = plotting.plot_scaling(runs, metric=metric, x=x, facet=facet, labels=labels)
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
    metric: MetricOpt = "time",
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
        compare_runs(runs, metric=metric, stat=stat, sort=sort, csv=csv)

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
