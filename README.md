# pytest-benchmem

[![PyPI](https://img.shields.io/pypi/v/pytest-benchmem)](https://pypi.org/project/pytest-benchmem/)
[![Python versions](https://img.shields.io/pypi/pyversions/pytest-benchmem)](https://pypi.org/project/pytest-benchmem/)
[![CI](https://github.com/fluxopt/pytest-benchmem/actions/workflows/ci.yaml/badge.svg)](https://github.com/fluxopt/pytest-benchmem/actions/workflows/ci.yaml)
[![Docs](https://img.shields.io/badge/docs-mkdocs-blue)](https://fluxopt.github.io/pytest-benchmem/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**The memory companion to [pytest-benchmark].** It times your code; pytest-benchmem adds a
memray **peak-memory** pass to the *same test, in the same run* — one node id, one JSON file,
both metrics. memray-precision (it sees numpy/C allocations), not coarse RSS sampling.

📖 **[Full documentation](https://fluxopt.github.io/pytest-benchmem/)**

## Quickstart

A **drop-in** for an existing pytest-benchmark suite: add `--benchmark-memory` and every
`benchmark(...)` call also records peak memory — no test changes.

```bash
pytest --benchmark-only --benchmark-memory
```

```
 Name (time in us)              Min                  Median         │  peak (MiB)
 ──────────────────────────────────────────────────────────────────────────────
  test_sort[10000]           32.5830 (1.0)         41.2080 (1.0)    │       0.08
  test_sort[100000]         321.2080 (9.86)       419.9160 (10.19)  │       0.76
  test_sort[1000000]      3,669.2920 (112.61)   4,331.5421 (105.11) │       7.63

 memory (right of │): a separate, untimed pass  •  more via --benchmark-memory-columns: allocated, allocations
```

Timing on the left is pytest-benchmark's, untouched; memory on the right is a *separate,
untimed* memray pass. Add `--benchmark-json=run.json` to persist both under one id; for memory
on only a few tests, use the `benchmark_memory` fixture instead of the flag.
→ [Getting started](https://fluxopt.github.io/pytest-benchmem/getting-started/) ·
[Metrics & `--stat`](https://fluxopt.github.io/pytest-benchmem/metrics/)

## The CLI

**Compare & gate CI.** A per-benchmark table — `time` and `peak` across the full
`min`/`max`/`mean`/`median`/`stddev` grid by default — or fail the build on a regression:

```bash
benchmem compare base.json head.json                      # the table below
benchmem compare base.json head.json --fail-on peak:10%   # exit non-zero past a threshold
```

```
test_build[n=5000]
             time (s)     time (s)      time (s)      time (s)      time (s)     peak (MiB)     peak (MiB)     peak (MiB)     peak (MiB)      peak (KiB)
 name             min          max          mean        median        stddev            min            max           mean         median          stddev
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 (base)       2 (1.0)    2.3 (1.0)    2.12 (1.0)    2.08 (1.0)    0.09 (1.0)    60.00 (1.0)    60.50 (1.0)    60.23 (1.0)    60.20 (1.0)    210.41 (1.0)
 (head)   2.05 (1.02)   2.4 (1.04)   2.18 (1.03)   2.12 (1.02)   0.11 (1.22)   72.00 (1.20)   73.20 (1.21)   72.53 (1.20)   72.40 (1.20)   510.86 (2.43)
```

One sub-table per benchmark, a row per run; each cell is relative to that benchmark's best run
as a `(×)` multiplier (best green, worst red), so the `peak +20%` regression shows across every
stat at once. Narrow with `--columns` / `--stat` / `--group-by`. Gate **inline** in the run
too, and add `--benchmark-memory-profile DIR` to keep the memray `.bin` of each offending id so
`memray flamegraph` shows *where* it grew.
→ [Compare & gate CI](https://fluxopt.github.io/pytest-benchmem/compare-plot/)

**Plot across inputs & versions.** Dims-aware plotly views — scaling (cost vs input size),
A/B scatter, version sweeps:

```bash
benchmem plot run.json --columns peak                       # peak vs the parametrized dim
benchmem sweep mypkg 1.2.0 1.3.0 main --suite bench/        # run a suite across versions → compare/plot
```

`@pytest.mark.parametrize` params become the dims the plots scale by, and
`@pytest.mark.benchmem(max_peak="100MiB")` sets an absolute per-test ceiling.
→ [Plot](https://fluxopt.github.io/pytest-benchmem/compare-plot/) ·
[Sweeps](https://fluxopt.github.io/pytest-benchmem/sweeps/) ·
[Dims](https://fluxopt.github.io/pytest-benchmem/dims/)

## Why memray, and where it sits

memray tracks the allocator directly, so it catches the numpy/C-allocation detail that RSS
sampling (ASV's `peakmem`) misses and folds out interpreter baseline. pytest-benchmem rides
pytest-benchmark for timing and reads/writes its JSON — it doesn't reimplement timing, a CI
dashboard ([CodSpeed]), or cross-commit history ([ASV]).

**vs [pytest-memray]** — complements, not rivals; both are thin layers over memray, pointed
opposite ways. pytest-memray is a *guardrail*: `limit_memory` / leak detection over the
**whole test**. pytest-benchmem is a *benchmark*: it measures **only the benchmarked action**,
alongside timing, and lets you **compare, sweep, and plot** it across inputs and versions.
(Don't run `pytest --memray` and a benchmem fixture on the *same* test — memray won't nest two
trackers.)

## Install

```bash
uv add pytest-benchmem            # the fixture + flag + memray engine
uv add "pytest-benchmem[plot]"    # + the plot/compare/sweep CLI (pandas, plotly, typer)
```

memray is Linux/macOS only, so Windows installs cleanly with timing-only (the memory pass
raises a clear error there).

## Status

Early — extracted from the linopy benchmark suite. API may move before 1.0; see the
[changelog](https://github.com/fluxopt/pytest-benchmem/blob/main/CHANGELOG.md).

[pytest-benchmark]: https://pytest-benchmark.readthedocs.io
[pytest-memray]: https://pytest-memray.readthedocs.io
[CodSpeed]: https://codspeed.io
[ASV]: https://asv.readthedocs.io
