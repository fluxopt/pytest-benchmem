# pytest-benchmem

The memory companion to [pytest-benchmark](https://pytest-benchmark.readthedocs.io):
swap `benchmark` for `benchmark_memory` to record a memray peak-memory number next to
the timing — same test, same run, one JSON file.

```python
import pytest


@pytest.mark.parametrize("n", [10_000, 100_000, 1_000_000])
def test_sort(benchmark_memory, n):          # was: benchmark
    benchmark_memory(sorted, list(range(n, 0, -1)))
```

```bash
pytest --benchmark-only --benchmark-json=run.json   # timing + memory, one file
```

Peak lands in pytest-benchmark's own table, appended after its timing columns. Already
have a `benchmark` suite? Don't swap anything — add `--benchmark-memory` and every
`benchmark(...)` call records memory too:

```bash
pytest --benchmark-only --benchmark-memory
```

For where it sits relative to ASV, CodSpeed, and plain memray, see the
[README](https://github.com/fluxopt/pytest-benchmem#where-it-sits).

## Install

```bash
uv add pytest-benchmem            # the benchmark_memory fixture + memray engine
uv add "pytest-benchmem[plot]"    # + the plot/compare CLI (pandas, plotly, typer)
```

pytest-benchmark and memray are core deps; memray (the memory pass) is Linux/macOS
only — timing works everywhere.

## The docs

- **[Getting started](getting-started.ipynb)** — write a benchmark, run it, read both metrics back. Start here.
- **[Metrics](metrics.ipynb)** — peak, allocated, allocations, and when to reach for each.
- **[Grouping by dims](dims.ipynb)** — the right axes for every plot and compare, no id parsing.
- **[Compare & plot](compare-plot.ipynb)** — diff runs as a table or an interactive view; gate CI.
- **[Cross-version sweeps](sweeps.md)** — run the same suite across installed versions of a package.
- **[Reference](reference.ipynb)** — every flag, marker, fixture, CLI command, and public function.

## Status

Early. Extracted from the linopy internal benchmark suite, where it's the local
memory-profiling layer. API may move before 1.0.
