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

A **drop-in** for an existing pytest-benchmark suite: add `--benchmark-memory` and every
`benchmark(...)` call also records peak memory — no test changes.

```python
import pytest


@pytest.mark.parametrize("n", [10_000, 100_000, 1_000_000])
def test_sort(benchmark, n):          # an ordinary pytest-benchmark test, unchanged
    benchmark(sorted, list(range(n, 0, -1)))
```

```bash
pytest --benchmark-only --benchmark-memory   # both metrics, in pytest-benchmark's own table
```

```
 Name (time in us)              Min                  Median         │  peak (MiB)
 ──────────────────────────────────────────────────────────────────────────────
  test_sort[10000]           32.5830 (1.0)         41.2080 (1.0)    │       0.08
  test_sort[100000]         321.2080 (9.86)       419.9160 (10.19)  │       0.76
  test_sort[1000000]      3,669.2920 (112.61)   4,331.5421 (105.11) │       7.63

 memory (right of │): a separate, untimed pass, not the timed rounds  •  also available via --benchmark-memory-columns: allocated, allocs
```

Left of the divider is pytest-benchmark's timing, untouched; right is pytest-benchmem's
memory. The two never overlap — memray measures peak on a *separate, untimed* call, so the
allocator hooks cost the timing nothing. It's opt-in at the run level: without the flag, your
suite runs exactly as before. Peak is the headline, so it shows by default; `allocated` and
`allocs` are one flag away (`--benchmark-memory-columns`).

Add `--benchmark-json=run.json` and both persist under one node id: timing in `stats`,
memory in `extra_info.benchmem`. Parametrize `params` become the dims the plots scale by —
see [Grouping by dims](https://fluxopt.github.io/pytest-benchmem/dims/).

## Memory on specific tests — the `benchmark_memory` fixture

`--benchmark-memory` measures the whole suite. To opt in *per test* instead — no run-level
flag — swap `benchmark` for the `benchmark_memory` fixture on just those tests; it's always
measured, and adds a `pedantic` form for explicit control:

```python
def test_sort(benchmark_memory):
    benchmark_memory(sorted, list(range(1_000_000, 0, -1)))
```

Memory passes are **adaptive** by default. Peak is allocator demand, not wall-clock jitter, so
each pass is exact; passes exist only to find the floor (this is sequential sampling, not
calibration). pytest-benchmem runs until the **minimum** peak settles (≥2 passes, so
the first pass's one-time warmup — lazy imports, arena growth — is discarded; capped at 10),
then reports that min. Deterministic code settles in a few passes; noisy code runs more, where
it helps. Force a fixed, reproducible count with `--benchmark-memory-repeats=N` (suite-wide) or
`@pytest.mark.benchmem(repeats=N)` (per test); every pass is kept and the headline is the min.

> **Your benchmark must be safe to re-run.** memray measures on an extra call, after
> pytest-benchmark's timing rounds — so a side-effectful action (mutates a fixture, fills a
> cache, drains an iterator, writes a file) records its already-warmed state, not a cold
> run, silently. Benchmark a pure call, or use the fixture's `pedantic` form with a `setup`
> that rebuilds fresh state each round.

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

Thresholds are percent (`peak:10%`) or absolute (`peak:5MiB`), on `peak`, `allocated`
(total bytes, catches churn peak hides), or `allocations` (count, near-deterministic and
often a better tripwire than peak bytes). Add `--benchmark-memory-profile DIR` to the inline
gate to keep the memray profile (`DIR/<id>.bin`) for each *regressing* id — render the call
paths behind the delta with `memray flamegraph` (the run prints the exact command), so a
failed gate is debuggable, not just red.

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
| Assert a memory limit / catch a leak *in a test* | **[pytest-memray]** | — (use it; see below) |
| *Which* function allocated, any test (flamegraph) | **[pytest-memray]** or `memray` | — (use them) |
| *Where* a benchmark's memory **regressed** | — | ⭐ `--benchmark-memory-profile` (keeps the `.bin`) |
| Memory *in your pytest-benchmark tests* | — | ⭐ fixture **or** `--benchmark-memory` |
| **Track/compare/plot** memory across inputs, versions, commits | — | ⭐ compare · sweep · plot |

In short: if your core need is *precise local memory* over the benchmarks you already
write — timing, sweeps, and plots in one vocabulary — that's pytest-benchmem.

### With pytest-memray

[pytest-memray] is the closest neighbor, and the two are **complements, not
rivals** — both are thin layers over the same memray engine, pointed in opposite
directions:

- **pytest-memray** is a *guardrail*: `@pytest.mark.limit_memory("100MiB")`,
  `limit_leaks`, and flamegraphs that fail or diagnose a test. It tracks the
  **whole test** (fixtures, data construction, teardown) — the right scope for
  *"did this test use too much / leak?"*.
- **pytest-benchmem** is a *benchmark*: it measures **only the benchmarked
  action**, alongside timing under one node id, and lets you **compare, sweep,
  and plot** that number across inputs, versions, and commits — *"how does memory
  scale / change?"*. It has no leak detection by design — but when a memory gate
  flags a regression, `--benchmark-memory-profile` keeps the offending ids' memray
  `.bin`s, so *which* allocation grew is a `memray flamegraph` away.

They coexist in one suite. One caveat: memray won't nest two trackers, so don't run
`pytest --memray` and a benchmem fixture on the *same* test.

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
[pytest-memray]: https://pytest-memray.readthedocs.io
[CodSpeed]: https://codspeed.io
[ASV]: https://asv.readthedocs.io
