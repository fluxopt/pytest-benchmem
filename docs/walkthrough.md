---
jupytext:
  text_representation:
    extension: .md
    format_name: myst
    format_version: 0.13
    jupytext_version: 1.19.3
kernelspec:
  display_name: Python 3 (ipykernel)
  language: python
  name: python3
---

# benchkit — walkthrough

> ⚠️ **This `.md` is the source.** It renders as docs on GitHub *and*
> converts to a runnable notebook: `jupytext --to ipynb docs/walkthrough.md`,
> then open `walkthrough.ipynb` in JupyterLab / PyCharm / VSCode. The
> `.ipynb` is gitignored — edit the `.md`, re-convert.

benchkit is a thin, generic layer for **time and precise peak-memory**
benchmarking, built around one primitive — the [`Case`](../README.md). This
notebook runs the library and its CLI end-to-end: measure memory, time ad-hoc
callables, write snapshots, then `compare` / `plot` them from the shell.

Needs the extras: `uv add "benchkit[all]"` (memray + plotly/pandas + the typer
CLI). Memory measurement is Linux/macOS only.

## Setup

A scratch dir for the snapshot/plot files the cells below produce. `FORCE_COLOR`
makes typer's CLI panels render in colour even through the `!`-cell pipe.

```{code-cell} ipython3
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import plotly.io as pio

os.environ["FORCE_COLOR"] = "1"
pio.renderers.default = "notebook_connected"  # load plotly.js from CDN — light pages
_tmp = Path(tempfile.mkdtemp(prefix="benchkit-"))
print(f"tempdir: {_tmp}")
```

## The primitive — `Case` + `measure`

A `Case` is an `id`, structured `dims` for analysis, and a `run` factory: a
context manager that does **untimed setup**, yields the **measured action**, then
tears down. `measure` runs each case under `memray.Tracker` and returns a list of
`Sample(id, value, dims)` — the setup allocation is excluded, so the peak reflects
only the action, and each sample carries the case's `dims` for analysis.

```{code-cell} ipython3
from benchkit import Case, measure


@contextmanager
def double_case(n):
    seed = list(range(n))                  # setup — not tracked
    yield lambda: [x * 2 for x in seed]    # the measured action


cases = [
    Case(id=f"double[list-n={n}]", dims={"op": "double", "n": n},
         run=lambda n=n: double_case(n))
    for n in (10_000, 100_000, 1_000_000)
]

measure(cases)
```

How cases are *generated* is yours — a registry of subjects × operations × sizes
is something you build on top. benchkit imposes only `Case`.

## Ad-hoc — the `bench` API

When you just want to time or memory-profile *one callable* without wiring a
`Case`, reach for `bench`. `bench.time` uses a min-of-N convention over a
`timeit`-calibrated inner loop; `bench.memory` profiles peak RSS through the same
memray path `measure` uses. (These are *not* pytest-benchmark's calibrated timer
— compare `bench` numbers only to other `bench` numbers.)

```{code-cell} ipython3
from benchkit import bench

bench.time(sorted, list(range(10_000)), rounds=5)
```

```{code-cell} ipython3
bench.memory(lambda: [0] * 5_000_000)
```

## Snapshots — the on-disk seam

Every result writes to a snapshot the CLI reads. `bench.compare` runs several
callables and collects a `ResultSet`; `to_snapshot` writes them all into one
file. `load_long_df` reads any snapshot (timing *or* memory — the unit travels in
the file) into a tidy frame, one column per dim — the single seam every plot view
and `compare` sits on.

```{code-cell} ipython3
from benchkit import load_long_df

rs = bench.compare(
    {
        "listcomp": lambda: [i * i for i in range(50_000)],
        "map": lambda: list(map(lambda i: i * i, range(50_000))),
        "genexpr": lambda: list(i * i for i in range(50_000)),
    },
    rounds=20,
)
snap = _tmp / "idioms.json"
rs.to_snapshot(snap)

df, unit = load_long_df([snap])
print(f"unit: {unit}")
df
```

## Two snapshots to diff

On a real change you'd snapshot once on `main` and once on your branch. Here we
synthesize a baseline/candidate pair across a size sweep — each `Sample` tagged
with `op` / `n` dims, so the plots scale by `n` without ever parsing the id.

```{code-cell} ipython3
from benchkit import Sample, write_snapshot

SIZES = (1_000, 10_000, 100_000, 1_000_000)


def sweep_snapshot(path, label):
    samples = [
        Sample(f"sort[n={n}]", bench.time(sorted, list(range(n)), rounds=5).stats["min"],
               {"op": "sort", "n": n})
        for n in SIZES
    ]
    return write_snapshot(path, label, samples, "s")


baseline = sweep_snapshot(_tmp / "baseline.json", "baseline")
candidate = sweep_snapshot(_tmp / "candidate.json", "candidate")
print("wrote", baseline.name, "and", candidate.name)
```

## CLI — `benchkit compare`

A per-id delta table with percent change, timing or memory auto-detected. Ids
present in only one snapshot show `—`. (Two runs of the same code, so the deltas
here are just measurement noise — on a real change they'd move.)

```{code-cell} ipython3
!benchkit compare {baseline} {candidate}
```

## CLI — `benchkit plot`

`benchkit plot` writes an interactive plotly view to standalone HTML. The view
defaults by snapshot count (1 → `scaling`, 2 → `scatter`, 3+ → `sweep`); pass
`--view` to pick.

```{code-cell} ipython3
!benchkit plot --view scatter {baseline} {candidate} -o {_tmp / "scatter.html"}
```

Every view is a `plot_*` function over the same `load_long_df` seam — call them
directly to render the *same figures* inline here, no HTML round-trip. Each
returns `(figure, n_ids)`.

**Scatter** — x = baseline cost (log), y = candidate/baseline ratio, colour =
absolute Δ. Top-right is the "slow and got slower" zone.

```{code-cell} ipython3
from benchkit import plotting

plotting.plot_scatter([baseline, candidate])[0]
```

**Compare** — the "did anything regress, ranked by impact" bar chart, sorted by
absolute delta, diverging colour around zero.

```{code-cell} ipython3
plotting.plot_compare([baseline, candidate])[0]
```

**Scaling** — a single snapshot, cost vs. size. `plot_scaling` auto-infers the
x-axis from the numeric `n` dim, so the baseline sweep alone draws `sorted`'s
curve.

```{code-cell} ipython3
plotting.plot_scaling([baseline])[0]
```

## Cross-version sweeps — `benchkit.sweep`

To benchmark *across installed versions* of a package, `sweep` provisions one
fresh `uv` venv per version (with import isolation) and calls your `run` callback
in each. Everything package-specific — the install spec, what to run — is
injected, so it isn't tied to any one library:

```python
from benchkit.sweep import sweep

failed = sweep(
    ["1.2.0", "1.3.0", "git+https://github.com/me/pkg@main"],
    run=lambda venv: subprocess.run(
        [str(venv.python), "-m", "my_benchmarks", "--json", f"{venv.version}.json"],
        cwd=venv.cwd, env=venv.env,
    ),
    install_spec=lambda v: f"mypkg=={v}",
    copy_dir="my_benchmarks",     # copied in so it imports from here, pkg from the venv
    import_check="mypkg",         # preflight: assert pkg resolved to the venv
)
```

Point `benchkit plot` (default view: `sweep`, a log₂ fold-change heatmap) at the
per-version JSONs it produces and you get the cross-version picture.
