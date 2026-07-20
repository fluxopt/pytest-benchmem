# pytest-benchmem

[![PyPI](https://img.shields.io/pypi/v/pytest-benchmem)](https://pypi.org/project/pytest-benchmem/)
[![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://pypi.org/project/pytest-benchmem/)
[![CI](https://github.com/fluxopt/pytest-benchmem/actions/workflows/ci.yaml/badge.svg)](https://github.com/fluxopt/pytest-benchmem/actions/workflows/ci.yaml)
[![Docs](https://img.shields.io/badge/docs-mkdocs-blue)](https://fluxopt.github.io/pytest-benchmem/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

pytest-benchmem measures how much memory your code allocates, on the same benchmarks you
already time. It is for Python libraries and pipelines where memory is a real constraint:
large numpy arrays, pandas frames, solvers, C/Cython/Rust extensions. If you already track
performance in CI, you can track memory the same way and fail a PR when the footprint grows.

It builds on [pytest-benchmark]. Add one flag to an existing suite and a memray peak-memory
number lands next to the timings — same test, same run, one JSON file, no test changes.

📖 **[Full documentation](https://fluxopt.github.io/pytest-benchmem/)**

## Quickstart

Take an existing pytest-benchmark test. You don't change it:

```python
import pytest

@pytest.mark.parametrize("n", [10_000, 100_000, 1_000_000])
def test_sort(benchmark, n):
    benchmark(sorted, list(range(n, 0, -1)))
```

Add `--benchmark-memory` to the run:

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

The timing table is untouched. The memory pass is folded in to the right of the `│`. It runs
as a separate, untimed memray pass: `peak` spreads into min/mean/max, and `allocated` /
`allocations` are opt-in. A fourth metric, `rss`, is the whole-process physical peak the OOM
killer watches; opt in per test with `@pytest.mark.benchmem(isolate=True)`.

Already rebuild state with `benchmark.pedantic(setup=…)`? The same `setup` runs (untracked)
before each memory sample, so stateful benchmarks stay accurate with no extra changes.

## Plot across inputs and versions

Your `parametrize` params become plot axes on their own — no id parsing, no config. The `n`
in `parametrize("n", [...])` is a numeric x-axis, so `benchmem plot` draws a scaling curve
from it:

```bash
benchmem plot run.json --columns peak     # peak vs n
benchmem plot run.json --columns time     # the same axis, timing instead
```

The plots read pytest-benchmark's own JSON, so they work on your timing results whether or
not you ran the memory pass. Point `--columns` at `time`, `peak`, `allocated`, `allocations`,
or `rss`, and facet by any other param or dim:

```bash
benchmem plot run.json --columns time --facet node.func
```

Sweep across installed versions of a package from one command:

```bash
benchmem sweep mypkg 1.2.0 1.3.0 main --suite bench/
```

## Compare and gate CI

`benchmem compare` diffs two runs into a per-benchmark table. It shows `time │ peak` across
every stat, each cell a relative `(×)` multiplier against the best run. Add `--fail-on` to
fail CI on a regression:

```
test_build[n=5000]
             time (s)     time (s)      time (s)      time (s)      time (s)         peak (MiB)     peak (MiB)     peak (MiB)     peak (MiB)     peak (KiB)
 name             min          max          mean        median        stddev   │            min            max           mean         median         stddev
─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 (base)       2 (1.0)    2.3 (1.0)    2.12 (1.0)    2.08 (1.0)    0.09 (1.0)   │    60.00 (1.0)    60.50 (1.0)    60.23 (1.0)    60.20 (1.0)    210.41 (1.0)
 (head)   2.05 (1.02)   2.4 (1.04)   2.18 (1.03)   2.12 (1.02)   0.11 (1.22)   │   72.00 (1.20)   73.20 (1.21)   72.53 (1.20)   72.40 (1.20)   510.86 (2.43)
```

You can also gate inline during the run with `--benchmark-memory-compare-fail`. Pass
`--benchmark-memory-profile DIR` to keep the memray `.bin` of each offender, and
`benchmem flamegraph` then shows where the memory grew.

## Why memray, and where it sits

memray tracks the allocator directly. It catches the numpy/C-allocation detail that RSS
sampling (ASV's `peakmem`) misses, and folds out the interpreter baseline. pytest-benchmem
uses pytest-benchmark for timing and reads and writes its JSON. It does not reimplement
timing, a CI dashboard ([CodSpeed]), or cross-commit history ([ASV]).

**vs [pytest-memray]:** both wrap memray, pointed in opposite directions, and they complement
each other. pytest-memray is a guardrail — `limit_memory` and leak detection over the whole
test. pytest-benchmem is a benchmark: only the benchmarked action, measured alongside timing,
then compared, swept, and plotted across inputs and versions.

## Install

```bash
uv add pytest-benchmem            # the fixture + flag + memray engine
uv add "pytest-benchmem[plot]"    # + the benchmem plot/compare/sweep CLI (pandas, plotly, typer)
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
