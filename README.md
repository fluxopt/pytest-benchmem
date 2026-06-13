# pytest-benchmem

[![CI](https://github.com/fluxopt/pytest-benchmem/actions/workflows/ci.yaml/badge.svg)](https://github.com/fluxopt/pytest-benchmem/actions/workflows/ci.yaml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**The memory companion to [pytest-benchmark].** It times your code; pytest-benchmem adds
a memray **peak-memory** pass to the *same test, in the same run* — one node id,
one JSON file, both metrics. Plus dims-aware plots and cross-version sweeps it has
no answer for.

Its reason to exist is the gap nothing else fills cleanly: **memray-precision
memory benchmarking** of your own code, right where you already benchmark. ASV's
`peakmem` is coarse RSS sampling that misses numpy/C-allocation detail; CodSpeed
covers CI timing. pytest-benchmem is the thin memray layer on top of pytest-benchmark.

> **Not** a CI dashboard (use [CodSpeed]) and **not** a rigorous perf-history
> system (use [ASV]). If your core need is *precise local memory* numbers over
> the benchmarks you already write — and timing/sweeps/plots in the same
> vocabulary — that's pytest-benchmem.

## Where it sits

| Need | Reach for | pytest-benchmem |
|---|---|---|
| CI regression, per-PR dashboard | **CodSpeed** | — (don't rebuild it) |
| Local timing + A/B compare | **pytest-benchmark** | rides it (timing is its job) |
| Rigorous perf history across commits | **ASV** | — (heavier, RSS memory) |
| **Precise local peak memory (numpy/C allocs)** | **memray** | ⭐ the core |
| Memory *in your pytest-benchmark tests* | — | ⭐ the `benchmark_memory` fixture |
| Same runs across installed versions | — | ⭐ `sweep` |

## The fixture

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

One run, one `run.json`, for each benchmark id:

- `stats: {min, mean, median, …}` — **timing**, from pytest-benchmark.
- `extra_info: {"peak_mib": 3.81}` — **peak memory**, from pytest-benchmem.

The two never overlap: pytest-benchmark times the action untracked, then memray
measures peak on a *separate, untimed* call — so the allocator hooks cost the
timing nothing. The parametrize `params` (`{"n": …}`) become the analysis dims
the plots scale by. Memory is opt-in per test — plain `benchmark` tests are
untouched.

## Reading it back

Timing rides pytest-benchmark's own tooling (`pytest-benchmark compare`,
`--benchmark-histogram`) — pytest-benchmem doesn't reimplement it. For the memory side,
and for dims-aware views over either metric:

```python
from pytest_benchmem import from_pytest_benchmark, memory_from_pytest_benchmark

_, timing, _ = from_pytest_benchmark("run.json")        # seconds, from stats
_, memory, _ = memory_from_pytest_benchmark("run.json")  # MiB, from extra_info
```

```bash
benchmem compare base.json head.json --metric memory   # per-id delta table
benchmem plot base.json head.json --metric memory       # interactive plotly view
```

Outside pytest, `measure_peak(lambda: build_model(1000))` is the bare memray
engine — a one-liner peak number for a REPL or notebook.

## Install

```bash
uv add pytest-benchmem            # the benchmark_memory fixture + memray engine
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
