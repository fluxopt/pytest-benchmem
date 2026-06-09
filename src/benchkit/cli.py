"""benchkit CLI — ``plot`` and ``compare`` over snapshot files.

These are the registry-free commands (they read JSON only). A consumer that
wants ``run`` / ``sweep`` builds those on its own ``Case`` source.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Annotated

import typer

from benchkit.snapshot import discover_snapshots

app = typer.Typer(help="benchkit — plot and compare benchmark snapshots.", no_args_is_help=True)


def _need_plotly() -> None:
    if importlib.util.find_spec("plotly") is None:
        typer.secho(
            "plotting needs extras: pip install 'benchkit[plot]'",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)


@app.command()
def plot(
    snapshots: Annotated[list[Path], typer.Argument(help="Snapshot JSON file(s).")],
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
    """Render an interactive plotly view from one or more snapshots."""
    missing = [p for p in snapshots if not p.exists()]
    if missing:
        typer.secho(f"missing: {[str(p) for p in missing]}", fg=typer.colors.RED, err=True)
        found = discover_snapshots()
        if found:
            typer.echo("available:\n  " + "\n  ".join(str(p) for p in found), err=True)
        raise typer.Exit(code=2)

    chosen = view or (
        "scaling" if len(snapshots) == 1 else "scatter" if len(snapshots) == 2 else "sweep"
    )
    _need_plotly()
    from benchkit import plotting

    try:
        if chosen == "compare":
            fig, n = plotting.plot_compare(snapshots, facet=facet, clip=clip)
        elif chosen == "scatter":
            fig, n = plotting.plot_scatter(snapshots, facet=facet, clip=clip)
        elif chosen == "sweep":
            fig, n = plotting.plot_sweep(snapshots, clip=clip)
        elif chosen == "scaling":
            fig, n = plotting.plot_scaling(snapshots, x=x, facet=facet)
        else:
            typer.secho(f"unknown view {chosen!r}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    output = output or Path(".benchmarks") / "plots" / f"{chosen}.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(output)
    typer.secho(f"{chosen}: {n} ids → {output}", fg=typer.colors.GREEN)
    if open_browser:
        import webbrowser

        webbrowser.open(output.resolve().as_uri())


@app.command()
def compare(
    a: Annotated[Path, typer.Argument(help="Baseline snapshot.")],
    b: Annotated[Path, typer.Argument(help="Candidate snapshot.")],
) -> None:
    """Print a per-id delta table for two snapshots."""
    for p in (a, b):
        if not p.exists():
            typer.secho(f"missing: {p}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
    from benchkit.compare import compare_snapshots

    try:
        compare_snapshots(a, b)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
