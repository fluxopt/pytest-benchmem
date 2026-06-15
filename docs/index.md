# pytest-benchmem

**The memory companion to [pytest-benchmark](https://pytest-benchmark.readthedocs.io).**
It times your code; pytest-benchmem adds a memray **peak-memory** pass to the *same
test, in the same run* — one node id, one JSON file, both metrics. Plus dims-aware
plots and cross-version sweeps.

```python
import pytest


@pytest.mark.parametrize("n", [10_000, 100_000, 1_000_000])
def test_sort(benchmark_memory, n):          # was: benchmark
    benchmark_memory(sorted, list(range(n, 0, -1)))
```

```bash
pytest --benchmark-only --benchmark-json=run.json   # timing + memory, one file
```

Both metrics land in **pytest-benchmark's own table** — its timing columns, with `peak` /
`allocated` / `allocs` appended on the right. Already have a `benchmark` suite? Don't swap
anything — add `--benchmark-memory` and every `benchmark(...)` call records memory too:

```bash
pytest --benchmark-only --benchmark-memory
```

Its reason to exist is the gap nothing else fills cleanly: **memray-precision memory
benchmarking** of your own code, right where you already benchmark. ASV's `peakmem`
is coarse RSS sampling; CodSpeed covers CI timing. pytest-benchmem is the thin memray
layer on top of pytest-benchmark. See the
[README](https://github.com/fluxopt/pytest-benchmem#where-it-sits) for where it sits
relative to those tools.

## Install

```bash
uv add pytest-benchmem            # the benchmark_memory fixture + memray engine
uv add "pytest-benchmem[plot]"    # + the plot/compare CLI (pandas, plotly, typer)
```

pytest-benchmark and memray are core deps; memray (the memory pass) is Linux/macOS
only — timing works everywhere.

## The docs

- **[Getting started](getting-started.ipynb)** — write a benchmark, run it, read both
  metrics back. Start here.
- **[Metrics: peak, allocated, allocations](metrics.ipynb)** — the three memory numbers
  every run records, and when to reach for each.
- **[Grouping by dims](dims.ipynb)** — give every plot and compare the right axes, with
  no id parsing.
- **[Compare & plot](compare-plot.ipynb)** — diff two runs as a table or an interactive
  view; gate CI on a regression.
- **[Cross-version sweeps](sweeps.md)** — run the same suite across installed versions
  of a package.
- **[Reference](reference.ipynb)** — every flag, the marker, the fixture, the CLI, and
  the public API.

## Status

Early. Extracted from the linopy internal benchmark suite, where it's the local
memory-profiling layer. API may move before 1.0.
