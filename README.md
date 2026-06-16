# pytest-benchmem

[![PyPI](https://img.shields.io/pypi/v/pytest-benchmem)](https://pypi.org/project/pytest-benchmem/)
[![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://pypi.org/project/pytest-benchmem/)
[![CI](https://github.com/fluxopt/pytest-benchmem/actions/workflows/ci.yaml/badge.svg)](https://github.com/fluxopt/pytest-benchmem/actions/workflows/ci.yaml)
[![Docs](https://img.shields.io/badge/docs-mkdocs-blue)](https://fluxopt.github.io/pytest-benchmem/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**The memory companion to [pytest-benchmark].** It times your code; pytest-benchmem adds a
memray **peak-memory** pass to the *same test, in the same run* — one node id, one JSON file,
both metrics. memray-precision (it sees numpy/C allocations), not coarse RSS sampling.

📖 **[Full documentation](https://fluxopt.github.io/pytest-benchmem/)**

## Quickstart

A **drop-in** for an existing pytest-benchmark suite — add `--benchmark-memory`, no test changes:

```bash
pytest --benchmark-only --benchmark-memory --benchmark-columns=min,mean,median
```

```
  Name (time in us)                    Min                  Mean                Median   │   peak·min (KiB)   peak·mean   peak·max
 ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  test_sort[10000]           30.2079 (1.0)         37.3511 (1.0)         38.6250 (1.0)   │            78.12       78.12      78.12
  test_sort[100000]        299.2500 (9.91)      404.0027 (10.82)      408.5415 (10.58)   │           781.25      781.25     781.25
  test_sort[1000000]   3,667.6250 (121.41)   4,427.5485 (118.54)   4,361.7500 (112.93)   │         7,812.50    7,812.50   7,812.50
```

Your pytest-benchmark timing table, untouched, with the memory pass folded in right of the `│`
— a *separate, untimed* memray pass (`peak` spreads into min/mean/max; `allocated` /
`allocations` are opt-in). Already use `benchmark.pedantic(setup=…)` to rebuild state for
timing? That same `setup` is reused — untracked — before each memory sample, so stateful
benchmarks stay accurate with **no extra changes**.

## Compare, gate, plot

**`benchmem compare`** — a per-benchmark table (`time │ peak` across every stat, each cell a
relative `(×)` multiplier vs the best run), or `--fail-on` to fail CI on a regression:

```
test_build[n=5000]
             time (s)     time (s)      time (s)      time (s)      time (s)         peak (MiB)     peak (MiB)     peak (MiB)     peak (MiB)     peak (KiB)
 name             min          max          mean        median        stddev   │            min            max           mean         median         stddev
─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 (base)       2 (1.0)    2.3 (1.0)    2.12 (1.0)    2.08 (1.0)    0.09 (1.0)   │    60.00 (1.0)    60.50 (1.0)    60.23 (1.0)    60.20 (1.0)    210.41 (1.0)
 (head)   2.05 (1.02)   2.4 (1.04)   2.18 (1.03)   2.12 (1.02)   0.11 (1.22)   │   72.00 (1.20)   73.20 (1.21)   72.53 (1.20)   72.40 (1.20)   510.86 (2.43)
```

Gate inline in the run too (`--benchmark-memory-compare-fail`), and `--benchmark-memory-profile
DIR` keeps the memray `.bin` of each offender so `memray flamegraph` shows *where* it grew.

**`benchmem plot` / `sweep`** — dims-aware plotly views (scaling vs input size, A/B scatter,
version sweeps) and cross-version runs from one command:

```bash
benchmem plot run.json --columns peak
benchmem sweep mypkg 1.2.0 1.3.0 main --suite bench/
```

## Why memray, and where it sits

memray tracks the allocator directly, so it catches the numpy/C-allocation detail that RSS
sampling (ASV's `peakmem`) misses and folds out interpreter baseline. pytest-benchmem rides
pytest-benchmark for timing and reads/writes its JSON — it doesn't reimplement timing, a CI
dashboard ([CodSpeed]), or cross-commit history ([ASV]).

**vs [pytest-memray]** — complements, not rivals; both wrap memray, pointed opposite ways.
pytest-memray is a *guardrail* (`limit_memory` / leak detection over the whole test);
pytest-benchmem is a *benchmark* — only the benchmarked action, alongside timing, **compared,
swept, and plotted** across inputs and versions.

## Install

```bash
uv add pytest-benchmem            # the fixture + flag + memray engine
uv add "pytest-benchmem[plot]"    # + the plot/compare/sweep CLI (pandas, plotly, typer)
```

memray is Linux/macOS only; Windows installs cleanly with timing-only (the memory pass raises a
clear error there).

## Status

Early — extracted from the linopy benchmark suite. API may move before 1.0; see the
[changelog](https://github.com/fluxopt/pytest-benchmem/blob/main/CHANGELOG.md).

[pytest-benchmark]: https://pytest-benchmark.readthedocs.io
[pytest-memray]: https://pytest-memray.readthedocs.io
[CodSpeed]: https://codspeed.io
[ASV]: https://asv.readthedocs.io
