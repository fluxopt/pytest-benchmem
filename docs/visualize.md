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

# Visualize memory

> **Newer feature** — less battle-tested than the [find & fix](profiling.md) core. It works, but
> feedback is welcome.

A number tells you *whether* memory grew; a chart tells you the **shape** — how cost scales with
input size, which ids moved and were already big, how a metric drifts across versions. `benchmem
plot` writes an interactive plotly view to standalone HTML, picking the view by run count. It reads
the same saved runs as [Compare two runs](compare-runs.md) and takes one metric (`--columns`).

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

## The numbers behind the charts

Before the shapes, the raw table — `benchmem compare --diff`, baseline (list of tuples) vs the
heavier candidate (list of dicts). Every `Δ%` is red because the candidate carries more per row.
A chart makes the *trend* obvious where the table only lists points:

```{code-cell} ipython3
:tags: [hide-input]

result = subprocess.run(
    ["benchmem", "compare", str(baseline), str(candidate),
     "--columns", "peak", "--diff", "--sort", "value"],
    env={**os.environ, "FORCE_COLOR": "1", "COLUMNS": "84"},
    capture_output=True, text=True, check=True,
)
print(result.stdout)
```

## Scaling — how cost grows with input size

**Scaling** (one run) draws cost vs. input size — here the baseline's peak-memory curve:

```bash
benchmem plot baseline.json --columns peak -o scaling.html
```

```{code-cell} ipython3
:tags: [hide-input]

from pytest_benchmem import plotting

plotting.plot_scaling([baseline], metric="peak")[0]
```

## Scatter — which ids moved, and were they already big

**Scatter** (two runs) puts baseline cost on x (log) and the candidate/baseline ratio on y,
colour = absolute Δ. The top-right corner is "big *and* got bigger" — where a regression actually
costs you:

```bash
benchmem plot baseline.json candidate.json --columns peak -o scatter.html
```

```{code-cell} ipython3
:tags: [hide-input]

plotting.plot_scatter([baseline, candidate], metric="peak")[0]
```

## The other views

`plot` auto-selects by run count; override with `--view`:

| Runs | Default view | Answers |
|---|---|---|
| 1 | `scaling` | how does cost grow with input size? |
| 2 | `scatter` | which ids moved, and were they already big? |
| 2 | `compare` (`--view compare`) | ranked — what moved *most*, in native units? |
| 3+ | `sweep` | fold-change across versions, one cell per (id, run) |

`--pivot` re-points the series axis of the paired views (`compare`/`scatter`) from the run-file onto
a dim, folding a single run along it (see
[Compare two runs → `--pivot`](compare-runs.md#one-run-two-configs-pivot)). `--facet` splits any
view into small multiples by a [dim](dims.md) (including `node.*`), `--where` keeps only rows
matching a `dim=value` filter (repeatable, AND-combined), `--free-axes` unmatches a faceted axis
from the shared default, and `--label`/`-l` names the series per run:

```bash
benchmem plot run.json --columns peak --facet node.func             # one panel per operation
benchmem plot run.json --facet node.func --free-axes y             # ...each on its own cost scale
benchmem plot run.json --where axis=n                              # one sweep at a time
benchmem plot v1.json v2.json v3.json -l 0.6 -l 0.7 -l 0.8         # name series, not file stems
```

Faceted panels **share axes by default** — right when they're commensurable (the same `n` grid
across functions). Two cases want them unmatched:

- **Different cost scales** — `--facet node.func` where one function is far costlier flattens the
  cheap panels on a shared y. `--free-axes y` gives each its own cost range.
- **Incommensurable sweeps** — a run mixing sizes `n` (10–10⁴) and a 0–100 `severity` under one
  numeric dim squishes both onto one x. `--free-axes x` (or filter to one with `--where axis=n`).

`--free-axes both` frees each panel entirely. `--where` is the cleaner reach when you only care
about one slice — it drops the rest rather than just rescaling.

## Where to go next

- The numbers behind the charts, as a table → [Compare two runs](compare-runs.md)
- Fold across *versions* of a package → [Compare across versions](sweeps.md)
- Every CLI flag → [Reference](reference.md)
