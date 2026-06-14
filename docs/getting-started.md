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

# Getting started

> ⚠️ **The `.md` is the source.** It renders as docs *and* converts to a runnable
> notebook (`jupytext --to ipynb docs/getting-started.md`). The `.ipynb` is
> gitignored — edit the `.md`, re-convert.

pytest-benchmem is the **memory companion to pytest-benchmark**: you write ordinary
pytest-benchmark tests, swap the `benchmark` fixture for `benchmark_memory`, and get
a memray **peak-memory** number recorded right next to the timing — same test, same
run, same JSON file. This page runs that end to end: write a benchmark, execute it,
and read both metrics back.

The fixture and memray ship with the core install; the plots and CLI need
`pytest-benchmem[plot]`. Memory measurement is Linux/macOS only (timing works
everywhere).

## Setup

A scratch dir for the suite and the JSON runs the cells below produce.

The `PATH` line makes the `!pytest` / `!benchmem` cells resolve to this kernel's
environment.

```{code-cell} ipython3
import os
import sys
import tempfile
from pathlib import Path

os.environ["FORCE_COLOR"] = "1"
os.environ["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"
_tmp = Path(tempfile.mkdtemp(prefix="pytest-benchmem-"))
print(f"tempdir: {_tmp}")
```

## A memory benchmark — the `benchmark_memory` fixture

`benchmark_memory` depends on pytest-benchmark's `benchmark` fixture, so timing
rides pytest-benchmark exactly as usual. On top, it runs the action once more under
`memray.Tracker` — a **separate, untimed pass**, so the allocator hooks never touch
the timing — and stashes the memory blob in `extra_info.benchmem`. One node id, one
JSON entry, both metrics. Parametrize `params` become the analysis `dims` the plots
scale by, for free.

Here's a tiny suite — `sorted` over a range of input sizes:

```{code-cell} ipython3
suite = _tmp / "test_sortbench.py"
suite.write_text("""
import pytest

@pytest.mark.parametrize("n", [10_000, 50_000, 200_000, 500_000])
def test_sort(benchmark_memory, n):
    data = list(range(n, 0, -1))
    benchmark_memory(sorted, data)
""")
print(suite.read_text())
```

> **Your benchmark must be safe to re-run.** Memory rides a *separate* invocation,
> after pytest-benchmark has already called your function many times for timing — so
> a side-effectful call (mutates a fixture, fills a cache, drains an iterator)
> records its already-warmed state, not a cold one, silently. Benchmark a pure call,
> or use the [`pedantic` form](reference.md#the-benchmark_memory-fixture) with a
> `setup` that rebuilds fresh state each round.

## Run it — one command, both metrics

A normal pytest invocation. `--benchmark-json` writes the same file pytest-benchmark
always writes; the only difference is each entry now also carries
`extra_info.benchmem`.

```{code-cell} ipython3
baseline = _tmp / "baseline.json"
!pytest {suite} --benchmark-only --benchmark-json={baseline} -q -p no:cacheprovider
```

## Read both metrics back

pytest-benchmem reads that one file *per metric*: `from_pytest_benchmark` pulls
timing (seconds, from `stats`), `memory_from_pytest_benchmark` pulls peak memory
(bytes, from `extra_info.benchmem`). Dims default to the parametrize `params`, so
each sample knows its `n` without anyone parsing the id.

```{code-cell} ipython3
from pytest_benchmem import from_pytest_benchmark, memory_from_pytest_benchmark

_, time_samples, tunit = from_pytest_benchmark(baseline)
_, mem_samples, munit = memory_from_pytest_benchmark(baseline)

print(f"timing ({tunit}):")
for s in time_samples:
    print(f"  {s.id.split('::')[-1]:<18} {s.value:.3e}  dims={dict(s.dims)}")
print(f"\nmemory ({munit}):")
for s in mem_samples:
    print(f"  {s.id.split('::')[-1]:<18} {s.value:>10.0f}  dims={dict(s.dims)}")
```

`load_long_df` stacks one or more runs into the tidy frame every plot pivots — one
row per `(run, id)` for the chosen metric, one column per dim:

```{code-cell} ipython3
from pytest_benchmem import load_long_df

df, unit = load_long_df([baseline], metric="peak")
print(f"unit: {unit}")
df
```

## Quick one-off — `measure_peak`

Outside pytest — in a REPL or notebook — `measure_peak` is the bare engine: hand it
a zero-arg callable, get the peak in bytes. (`repeats > 1` takes the min, since peak
memory is noisy; `measure_memory` returns the full `MemoryResult` — peak, spread,
allocation count.)

```{code-cell} ipython3
from pytest_benchmem import human_bytes, measure_peak

human_bytes(measure_peak(lambda: [0] * 5_000_000))
```

## Next

- **[Metrics: peak, allocated, allocations](metrics.ipynb)** — the three memory numbers
  every run records, and when to reach for each.
- **[Grouping by dims](dims.ipynb)** — give every plot the right axes.
- **[Compare & plot](compare-plot.ipynb)** — diff two runs, render the views.
- **[Reference](reference.md)** — every flag, the marker, the CLI, the public API.
