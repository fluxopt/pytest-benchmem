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

> ⚠️ The `.md` is the source; the `.ipynb` is generated (`jupytext --to ipynb
> docs/compare-plot.md`) and gitignored.

Two saved runs in, one delta out — as a table (`benchmem compare`) or an interactive
view (`benchmem plot`). Both work over `--metric time` or any memory metric, and both
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
!pytest {suite} --benchmark-only --benchmark-json={baseline}  -q -p no:cacheprovider
```

On a real change you'd run the suite on `main`, then on your branch. Here we just run
it twice — same code, so the deltas below are measurement noise; on a real change
they'd move.

```{code-cell} ipython3
!pytest {suite} --benchmark-only --benchmark-json={candidate} -q -p no:cacheprovider
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

**Gate CI on a regression** with `--fail-on` (exits non-zero past a threshold):

```{code-cell} ipython3
!benchmem compare {baseline} {candidate} --metric peak --fail-on peak:10% --fail-on allocations:5%; echo "exit: $?"
```

Thresholds are percent (`peak:10%`) or absolute (`peak:5MiB`). See the
[reference](reference.md#benchmem-compare) for the full grammar and the inline pytest
form.

## `benchmem plot` — the interactive views

`benchmem plot` writes an interactive plotly view to standalone HTML, picking a view
by run count (1 → `scaling`, 2 → `scatter`, 3+ → `sweep`) and the metric you pass.
Override the auto-pick with `--view`.

```{code-cell} ipython3
!benchmem plot --metric peak {baseline} {candidate} -o {_tmp / "scatter.html"}
```

Every view is a `plot_*` function over the same `load_long_df` seam — call them
directly to render the *same figures* inline, no HTML round-trip. Each takes a
`metric` and returns `(figure, n_ids)`.

**Scatter** — x = baseline cost (log), y = candidate/baseline ratio, colour =
absolute Δ. Top-right is the "big and got bigger" zone. Here on memory:

```{code-cell} ipython3
from pytest_benchmem import plotting

plotting.plot_scatter([baseline, candidate], metric="peak")[0]
```

**Compare** — the "did anything regress, ranked by impact" bar chart, sorted by
absolute delta, diverging colour around zero. On timing this time:

```{code-cell} ipython3
plotting.plot_compare([baseline, candidate], metric="time")[0]
```

**Scaling** — a single run, cost vs. size. `plot_scaling` auto-infers the x-axis from
the numeric `n` dim, so the baseline alone draws `sorted`'s peak-memory curve:

```{code-cell} ipython3
plotting.plot_scaling([baseline], metric="peak")[0]
```

For 3+ runs (e.g. a [version sweep](sweeps.md)) `plot_sweep` draws a log₂ fold-change
heatmap vs the baseline.

## Next

- **[Cross-version sweeps](sweeps.md)** — the same suite across installed versions.
- **[Reference](reference.md)** — every CLI flag and `plot_*` signature.
