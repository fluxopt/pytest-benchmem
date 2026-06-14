# pytest-benchmem

[![CI](https://github.com/fluxopt/pytest-benchmem/actions/workflows/ci.yaml/badge.svg)](https://github.com/fluxopt/pytest-benchmem/actions/workflows/ci.yaml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**The memory companion to [pytest-benchmark].** It times your code; pytest-benchmem
adds a memray **peak-memory** pass to the *same test, in the same run* — one node
id, one JSON file, both metrics. Plus dims-aware plots and cross-version sweeps.

📖 **[Full documentation](https://fluxopt.github.io/pytest-benchmem/)** — getting
started, metrics, dims, compare & plot, sweeps, and the reference.

## Quickstart

Write a normal pytest-benchmark test; swap `benchmark` for `benchmark_memory`:

```python
import pytest


@pytest.mark.parametrize("n", [10_000, 100_000, 1_000_000])
def test_sort(benchmark_memory, n):
    data = list(range(n, 0, -1))
    benchmark_memory(sorted, data)
```

```bash
pytest --benchmark-only --benchmark-json=run.json
```

One run, one `run.json`, for each benchmark id — both metrics, one node id:

- `stats: {min, mean, median, …}` — **timing**, from pytest-benchmark.
- `extra_info.benchmem: {peak_bytes, peak_bytes_max, allocations, total_bytes, repeats, mode}`
  — **memory**, from pytest-benchmem. The `peak` / `allocated` / `allocations`
  metrics mirror what `memray stats` reports (bytes stored raw, so the display
  layer auto-scales). `mode` records which metric produced the blob (`heap` today);
  the readers refuse to compare or co-plot different modes.

The two passes never overlap: pytest-benchmark times the action untracked, then
memray measures peak on a *separate, untimed* call — so the allocator hooks cost
the timing nothing. The parametrize `params` become the analysis dims the plots
scale by; for an axis `params` can't carry (a per-operation `phase`, or a clean
label for an object you parametrize over), set a scalar on `extra_info` — see
[Grouping by dims](https://fluxopt.github.io/pytest-benchmem/dims/).

## Already have a pytest-benchmark suite?

Don't rewrite a thing — add `--benchmark-memory` and every `benchmark(...)` call
also records peak memory:

```python
def test_sort(benchmark):            # unchanged
    benchmark(sorted, list(range(1_000_000, 0, -1)))
```

```bash
pytest --benchmark-only --benchmark-memory   # timing + memory for the whole suite
```

It's opt-in at the run level: without the flag, plain `benchmark` tests are
untouched. (Reach for the `benchmark_memory` fixture when you want memory on
specific tests only, or `pedantic` control.) Set `@pytest.mark.benchmem(repeats=N)`
on a test to measure it `N` times and keep the min (peak memory is noisy — GC
timing, lazy imports, page cache — so min-of-N is the cleanest floor).

> **Your benchmark must be safe to re-run.** Memory is measured on an *extra,
> separate* invocation, after pytest-benchmark has already called your function
> many times for timing — the memray pass is effectively the next call, not the
> first. So if the benchmarked code has side effects (mutates a shared fixture,
> fills a cache, drains an iterator, writes a file), the recorded peak reflects
> that already-warmed state, not a cold run — silently. Benchmark a pure call,
> or use the `benchmark_memory` fixture's `pedantic` form with a `setup` that
> rebuilds fresh state before each measured call.

## Reading it back

Timing rides pytest-benchmark's own tooling (`pytest-benchmark compare`,
`--benchmark-histogram`) — pytest-benchmem doesn't reimplement it. For **memory**,
and dims-aware views over either metric:

```bash
benchmem compare base.json head.json --metric peak   # per-id delta table
benchmem plot    base.json head.json --metric peak   # interactive plotly view

# name the series/columns independently of the filenames (else the file stem):
benchmem plot v067.json v070.json v080.json -l 0.6.7 -l 0.7.0 -l 0.8.0
```

```
id                          base.json    head.json     change  (B)
--------------------------------------------------------------------
test_sort[10000]              824 KiB      848 KiB       +2.9%
test_sort[100000]             7.6 MiB      7.4 MiB       -2.6%
test_sort[1000000]            76 MiB       91 MiB       +20.0%
```

**Gate CI on a memory regression** — exit non-zero past a threshold, mirroring
pytest-benchmark's `--benchmark-compare-fail=min:5%` grammar for memory:

```bash
# standalone, over two saved JSON files:
benchmem compare base.json head.json --fail-on peak:10% --fail-on allocated:10% --fail-on allocations:5%

# or inline in the pytest run, against a prior saved run (pytest-benchmark storage):
pytest --benchmark-only --benchmark-memory \
       --benchmark-memory-compare --benchmark-memory-compare-fail=peak:10%
```

Thresholds are percent (`peak:10%`) or absolute (`peak:5MiB`), on `peak`,
`allocated` (total bytes — catches churn peak hides), or `allocations` (count,
near-deterministic — often a better tripwire than peak bytes).

Or pull the numbers into your own analysis:

```python
from pytest_benchmem import from_pytest_benchmark, memory_from_pytest_benchmark

_, timing, _ = from_pytest_benchmark("run.json")         # seconds, from stats
_, memory, _ = memory_from_pytest_benchmark("run.json")  # bytes, from extra_info.benchmem
```

Outside pytest, `measure_peak(lambda: build_model(1000))` returns the bare peak in
bytes; `measure_memory(...)` returns the full `MemoryResult` (peak, spread,
allocation count) — a one-liner for a REPL or notebook.

## Where it sits

Its reason to exist is the gap nothing else fills cleanly: **memray-precision
memory benchmarking** of your own code, right where you already benchmark. ASV's
`peakmem` is coarse RSS sampling that misses numpy/C-allocation detail; CodSpeed
covers CI timing.

| Need | Reach for | pytest-benchmem |
|---|---|---|
| CI regression, per-PR dashboard | **CodSpeed** | — (don't rebuild it) |
| Local timing + A/B compare | **pytest-benchmark** | rides it (timing is its job) |
| Rigorous perf history across commits | **ASV** | — (heavier, RSS memory) |
| **Precise local peak memory (numpy/C allocs)** | **memray** | ⭐ the core |
| Memory *in your pytest-benchmark tests* | — | ⭐ fixture **or** `--benchmark-memory` |
| Same runs across installed versions | — | ⭐ `sweep` |

> **Not** a CI dashboard (use [CodSpeed]) and **not** a rigorous perf-history
> system (use [ASV]). If your core need is *precise local memory* over the
> benchmarks you already write — timing/sweeps/plots in one vocabulary — that's
> pytest-benchmem.

## Install

```bash
uv add pytest-benchmem            # the fixture + flag + memray engine
uv add "pytest-benchmem[plot]"    # + the plot/compare CLI (pandas, plotly, typer)
```

pytest-benchmark and memray are core deps; memray is Linux/macOS only, so Windows
installs cleanly with timing-only (the memory pass raises a clear error there).

## Status

Early. Extracted from the linopy internal benchmark suite, where it's the local
memory-profiling layer. API may move before 1.0.

[pytest-benchmark]: https://pytest-benchmark.readthedocs.io
[CodSpeed]: https://codspeed.io
[ASV]: https://asv.readthedocs.io
