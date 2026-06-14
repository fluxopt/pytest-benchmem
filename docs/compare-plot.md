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

# Compare & plot

Two (or more) saved runs in, one comparison out — as a table (`benchmem compare`) or an
interactive view (`benchmem plot`). Both work over `--metric time` or any memory metric, and both
group by the [dims](dims.ipynb) your tests carry.

## Setup

A scratch dir, and a baseline run to diff against. `plotly` renders inline from the
CDN.

```{code-cell} ipython3
import os
import sys
import tempfile
from pathlib import Path

import plotly.io as pio

os.environ["FORCE_COLOR"] = "1"
os.environ["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"
pio.renderers.default = "notebook_connected"
_tmp = Path(tempfile.mkdtemp(prefix="pytest-benchmem-"))

suite = _tmp / "test_sortbench.py"
suite.write_text("""
import pytest

@pytest.mark.parametrize("n", [10_000, 50_000, 200_000, 500_000])
def test_sort(benchmark_memory, n):
    benchmark_memory(sorted, list(range(n, 0, -1)))
""")
baseline, candidate = _tmp / "baseline.json", _tmp / "candidate.json"
!pytest {suite} --benchmark-only --benchmark-json={baseline}  --benchmark-columns=min,median -q -p no:cacheprovider
```

On a real change you'd run the suite on `main`, then on your branch. Here we just run
it twice — same code, so the deltas below are measurement noise; on a real change
they'd move.

```{code-cell} ipython3
!pytest {suite} --benchmark-only --benchmark-json={candidate} --benchmark-columns=min,median -q -p no:cacheprovider
```

## `benchmem compare` — the delta table

A per-id delta table with percent change, for whichever `--metric` you ask for. Ids
in only one run show `—`.

```{code-cell} ipython3
!benchmem compare {baseline} {candidate} --metric peak
```

```{code-cell} ipython3
!benchmem compare {baseline} {candidate} --metric time
```

> For *timing* comparisons you can also use pytest-benchmark's own tooling directly —
> `pytest-benchmark compare`, `--benchmark-histogram`. pytest-benchmem doesn't
> reimplement those; it adds the memory-aware, dims-aware views.

Order the rows with `--sort` (`name` | `value` — largest in the last run first — |
`change`), and write the raw numbers for another tool with `--csv out.csv`:

```bash
benchmem compare {baseline} {candidate} --metric peak --sort value --csv peak.csv
```

**Gate on a regression** with `--fail-on` — it exits non-zero past a threshold.
Here baseline and candidate are the same code, so nothing trips it (exit `0`); on a
real regression the offending ids print and the command exits `1`:

```{code-cell} ipython3
!benchmem compare {baseline} {candidate} --metric peak --fail-on peak:10% --fail-on allocations:5%; echo "exit: $?"
```

Thresholds are percent (`peak:10%`) or absolute (`peak:5MiB`), on `peak`, `allocated`,
or `allocations`. The next section wires this into CI; the
[reference](reference.ipynb#benchmem-compare) has the full grammar.

## Gate CI on regressions

Two ways to fail a PR when memory regresses.

**A) Two saved JSON files** — save a baseline (e.g. on `main`), then compare the PR
run against it with `benchmem compare --fail-on`. The baseline file is just the
`--benchmark-json` from an earlier run, restored from cache or a base-branch build:

```bash
# on the PR branch:
pytest --benchmark-only --benchmark-json=pr.json
benchmem compare main.json pr.json --fail-on peak:10% --fail-on allocations:5%
```

**B) Inline, via pytest-benchmark storage** — no separate files. Save a baseline into
storage once with pytest-benchmark's own `--benchmark-save` (or `--benchmark-autosave`
every run), then gate the next run against it. `--benchmark-memory-compare-fail`
implies `--benchmark-memory-compare`, so the PR run compares against the latest saved
run automatically:

```bash
# on main — record the baseline into .benchmarks/ storage:
pytest --benchmark-only --benchmark-memory --benchmark-save=main

# on the PR branch — fail if peak grows >10% vs that baseline:
pytest --benchmark-only --benchmark-memory --benchmark-memory-compare-fail=peak:10%
```

> Without a prior saved run, the inline gate is a no-op — it prints *"no prior run
> with memory to compare against"* and passes. Save a baseline first.

A minimal GitHub Actions job using approach **A**, caching the baseline across runs:

```yaml
- uses: actions/cache@v4
  with:
    path: main.json
    key: benchmem-baseline-${{ github.base_ref }}
- run: pytest --benchmark-only --benchmark-json=pr.json
- run: benchmem compare main.json pr.json --fail-on peak:10% --fail-on allocations:5%
```

`allocations` is the steadiest tripwire — near-deterministic, so a move there is
almost always a real behaviour change rather than measurement noise.

## `benchmem plot` — the interactive views

`benchmem plot` writes an interactive plotly view to standalone HTML. It picks the
view by run count — but each view answers a different question, so override with
`--view` when you want a specific one:

| Runs | Default view | Answers |
|---|---|---|
| 1 | `scaling` | how does cost grow with input size? |
| 2 | `scatter` | which ids moved, and were they already big? |
| 2 | `compare` (`--view compare`) | ranked — what moved *most*, in native units? |
| 3+ | `sweep` | fold-change across versions, one cell per (id, run) |

```{code-cell} ipython3
!benchmem plot --metric peak {baseline} {candidate} -o {_tmp / "scatter.html"}
```

Every view is a `plot_*` function over the same `load_long_df` seam — call it directly
to render the *same figure* inline, no HTML round-trip. Each takes a `metric`, returns
`(figure, n_ids)`, and shares three options: **`facet`** (small-multiple by a dim),
**`labels`** (name the series, defaulting to file stems), and **`clip`** (clamp the
colour scale so one outlier doesn't wash the rest out).

**Scaling** — a single run, cost vs. size. `plot_scaling` auto-infers the x-axis from
the numeric `n` dim (override with `x=`), and auto-picks log/linear (force with
`log=`). The baseline alone draws `sorted`'s peak-memory curve:

```{code-cell} ipython3
from pytest_benchmem import plotting

plotting.plot_scaling([baseline], metric="peak")[0]
```

**Scatter** — two runs. x = baseline cost (log), y = candidate/baseline ratio, colour
= absolute Δ. The top-right is the "big *and* got bigger" corner — where a regression
actually costs you. Here on memory:

```{code-cell} ipython3
plotting.plot_scatter([baseline, candidate], metric="peak")[0]
```

**Compare** — two runs, ranked. A bar per id sorted by absolute delta, diverging
colour around zero — the "did anything regress, biggest first" view. Pass
`sort="relative"` to rank by percent instead. On timing this time:

```{code-cell} ipython3
plotting.plot_compare([baseline, candidate], metric="time")[0]
```

**Sweep** — three or more runs. A heatmap of log₂ fold-change vs the first run, one
column per run, one row per id — the natural picture for a
[version sweep](sweeps.md). A third run to make one:

```{code-cell} ipython3
third = _tmp / "third.json"
!pytest {suite} --benchmark-only --benchmark-json={third} --benchmark-columns=min,median -q -p no:cacheprovider
plotting.plot_sweep([baseline, candidate, third], metric="peak")[0]
```

### Naming the series

By default each run is labelled by its file stem (`baseline`, `candidate`, …). Pass
`labels=` to name them yourself — the API behind `plot`'s `-l/--label` — which is what
you want when the filenames are version numbers or commit shas:

```{code-cell} ipython3
plotting.plot_sweep([baseline, candidate, third], metric="peak",
                    labels=["v0.6", "v0.7", "v0.8"])[0]
```

### Faceting by a dim

`facet=` (CLI `--facet`) splits any view into small multiples by a [dim](dims.ipynb) —
including the `node.*` structural dims. With one test function per operation, for
instance, `--facet node.func` gives one panel per operation:

```bash
benchmem plot run.json --metric peak --facet node.func
```

## Next

- **[Cross-version sweeps](sweeps.md)** — the same suite across installed versions.
- **[Reference](reference.ipynb)** — every CLI flag and `plot_*` signature.
