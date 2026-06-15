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

# Compare & gate CI

Two (or more) saved runs in, one comparison out — a table (`benchmem compare`) or an
interactive view (`benchmem plot`). Both take `--metric time` or any memory metric, and group
by the [dims](dims.md) your tests carry.

## A regression to catch

A benchmark builds a table of `(i, i²)` rows. On `main`, each row is a lightweight tuple:

```python
@pytest.mark.parametrize("n", [10_000, 50_000, 200_000, 500_000])
def test_build_rows(benchmark, n):
    benchmark(lambda: [(i, i * i) for i in range(n)])
```

A branch switches the rows to dicts for readability — a classic memory regression, since a
dict is several times heavier than a 2-tuple:

```python
@pytest.mark.parametrize("n", [10_000, 50_000, 200_000, 500_000])
def test_build_rows(benchmark, n):
    benchmark(lambda: [{"x": i, "sq": i * i} for i in range(n)])
```

Run each on its branch and save the `--benchmark-json` — here, `baseline.json` (main) and
`candidate.json` (the branch).

```{code-cell} ipython3
:tags: [hide-input]

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import plotly.io as pio

os.environ["FORCE_COLOR"] = "1"
os.environ["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"
pio.renderers.default = "notebook_connected"
_tmp = Path(tempfile.mkdtemp(prefix="pytest-benchmem-"))

suite = _tmp / "test_rows.py"
baseline, candidate = _tmp / "baseline.json", _tmp / "candidate.json"
_args = ["--benchmark-only", "--benchmark-memory", "--benchmark-columns=min",
         "-q", "-p", "no:cacheprovider"]
_suite = """
import pytest

@pytest.mark.parametrize("n", [10_000, 50_000, 200_000, 500_000])
def test_build_rows(benchmark, n):
    benchmark(lambda: %s)
"""
for _out, _row in [(baseline, "[(i, i * i) for i in range(n)]"),
                   (candidate, '[{"x": i, "sq": i * i} for i in range(n)]')]:
    suite.write_text(_suite % _row)
    subprocess.run([sys.executable, "-m", "pytest", str(suite), *_args,
                    f"--benchmark-json={_out}"], check=True, capture_output=True)
```

## `benchmem compare` — the delta table

A per-id delta table with percent change, for whichever `--metric` you ask for. Ids in only
one run show `—`:

```{code-cell} ipython3
!benchmem compare {baseline} {candidate} --metric peak
```

## Gate CI on a regression

`--fail-on` exits non-zero past a threshold — drop it into CI after the run. Thresholds are
percent (`peak:10%`) or absolute (`peak:5MiB`), on `peak`, `allocated`, or `allocations`
(repeatable):

```bash
# on the PR branch, against a baseline saved from main:
pytest --benchmark-only --benchmark-memory --benchmark-json=pr.json
benchmem compare main.json pr.json --fail-on peak:10% --fail-on allocations:5%
```

The dict rows blow past the threshold on every size, so the offending ids print and it exits
`1` — failing the CI job:

```{code-cell} ipython3
!benchmem compare {baseline} {candidate} --metric peak --fail-on peak:10% --fail-on allocations:5%; echo "exit: $?"
```

`allocations` is usually the steadiest tripwire — see [Choosing a metric](metrics.md).

## `benchmem plot` — interactive views

`benchmem plot` writes an interactive plotly view to standalone HTML, picking the view by run
count. **Scaling** (one run) draws cost vs. input size — the baseline's peak-memory curve:

```bash
benchmem plot baseline.json --metric peak -o scaling.html
```

```{code-cell} ipython3
:tags: [hide-input]

from pytest_benchmem import plotting

plotting.plot_scaling([baseline], metric="peak")[0]
```

**Scatter** (two runs) puts baseline cost on x (log) and the candidate/baseline ratio on y,
colour = absolute Δ. The top-right corner is "big *and* got bigger" — where a regression
actually costs you:

```bash
benchmem plot baseline.json candidate.json --metric peak -o scatter.html
```

```{code-cell} ipython3
:tags: [hide-input]

plotting.plot_scatter([baseline, candidate], metric="peak")[0]
```

## Where to go next

- Which metric to gate on → [Choosing a metric](metrics.md)
- Compare across *versions* of a package → [Cross-version sweeps](sweeps.md)
- Every CLI flag and option → [Reference](reference.md)

---

## Going further

> For *timing* comparisons you can also use pytest-benchmark's own tooling directly —
> `pytest-benchmark compare`, `--benchmark-histogram`. pytest-benchmem doesn't reimplement
> those; it adds the memory-aware, dims-aware views. Pass `--metric time` to any command here
> to put both on the same footing.

### More from `compare`

Order rows with `--sort` (`name` | `value` — largest last-run first — | `change`), and write
raw numbers for another tool with `--csv out.csv`:

```bash
benchmem compare baseline.json candidate.json --metric peak --sort value --csv peak.csv
```

### Gating without separate files

The approach above keeps two JSON files. Alternatively, gate **inline** against
pytest-benchmark's own storage — save a baseline once, then fail the next run against it.
`--benchmark-memory-compare-fail` implies `--benchmark-memory-compare`:

```bash
# on main — record the baseline into .benchmarks/ storage:
pytest --benchmark-only --benchmark-memory --benchmark-save=main

# on the PR branch — fail if peak grows >10% vs that baseline:
pytest --benchmark-only --benchmark-memory --benchmark-memory-compare-fail=peak:10%
```

> Without a prior saved run, the inline gate is a no-op — it prints *"no prior run with memory
> to compare against"* and passes. Save a baseline first.

A minimal GitHub Actions job using the two-file approach, caching the baseline across runs:

```yaml
- uses: actions/cache@v4
  with:
    path: main.json
    key: benchmem-baseline-${{ github.base_ref }}
- run: pytest --benchmark-only --benchmark-memory --benchmark-json=pr.json
- run: benchmem compare main.json pr.json --fail-on peak:10% --fail-on allocations:5%
```

### The other two views

`plot` auto-selects by run count; override with `--view`:

| Runs | Default view | Answers |
|---|---|---|
| 1 | `scaling` | how does cost grow with input size? |
| 2 | `scatter` | which ids moved, and were they already big? |
| 2 | `compare` (`--view compare`) | ranked — what moved *most*, in native units? |
| 3+ | `sweep` | fold-change across versions, one cell per (id, run) |

`--facet` splits any view into small multiples by a [dim](dims.md) (including `node.*`),
`--where` keeps only rows matching a `dim=value` filter (repeatable, AND-combined), and
`--label`/`-l` names the series per run (defaulting to the file stems):

```bash
benchmem plot run.json --metric peak --facet node.func        # one panel per operation
benchmem plot run.json --where axis=n                         # one sweep at a time
benchmem plot v1.json v2.json v3.json -l 0.6 -l 0.7 -l 0.8     # name series, not file stems
```

`--where` is the lever when a single run mixes two incommensurable sweeps (say sizes
`n` and a 0–100 `severity`) under one numeric dim: `scaling` would otherwise put both on
one x-axis and squish them. Filter to one (`--where axis=n`), or `--facet axis` to scale
each in its own panel.
