# pytest-benchmem

[![PyPI](https://img.shields.io/pypi/v/pytest-benchmem)](https://pypi.org/project/pytest-benchmem/)
[![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://pypi.org/project/pytest-benchmem/)
[![CI](https://github.com/fluxopt/pytest-benchmem/actions/workflows/ci.yaml/badge.svg)](https://github.com/fluxopt/pytest-benchmem/actions/workflows/ci.yaml)
[![Docs](https://img.shields.io/badge/docs-mkdocs-blue)](https://fluxopt.github.io/pytest-benchmem/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**On-demand memory profiling for your benchmarks.** pytest-benchmem measures how much memory your
code actually uses — and shows you *where* it goes — on the pytest-benchmark tests you already have.
Find the heavy path, fix it, confirm the drop. It's for Python libraries and pipelines where memory
is a real constraint: large numpy arrays, pandas frames, solvers, C/Cython/Rust extensions.

It builds on [pytest-benchmark]. Add one flag to an existing suite and a memray peak-memory number
lands next to the timings — same test, same run, no test changes. When a number looks heavy, keep
the profile and open a flamegraph to see the allocating call paths.

📖 **[Full documentation](https://fluxopt.github.io/pytest-benchmem/)**

## 1. Measure — spot the heavy benchmark

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

The timing table is untouched; the memray peak-memory pass is folded in to the right of the `│`,
as a separate, untimed run. `peak` spreads into min/mean/max; `allocated` / `allocations` are
opt-in. Already rebuild state with `benchmark.pedantic(setup=…)`? The same `setup` runs (untracked)
before each memory sample, so stateful benchmarks stay accurate with no extra changes.

## 2. Find where the memory goes

A peak number tells you *which* benchmark is heavy, not *where* the memory goes. Keep the memray
profile for the offenders, then render the allocating call paths:

```bash
pytest --benchmark-only --benchmark-memory --benchmark-memory-profile profiles/
benchmem flamegraph profiles/ --worst peak --open     # render the heaviest, open it
```

The `.bin` is memray's raw capture, so it also feeds `memray tree` / `summary` / `stats`. For a
native-backed workload (polars/Rust, numpy/C), add `--benchmark-memory-profile-native` so the
flamegraph attributes memory to the real C/Rust frames instead of one opaque bucket.

## 3. Confirm the fix

Change the code, re-run, and diff the two runs to see the peak actually dropped:

```bash
benchmem compare before.json after.json --columns peak --diff
```

`compare` reads pytest-benchmark's own JSON and lays the runs side by side, keyed on the benchmark
id — `--diff` shows a signed `Δ%` per benchmark so the win (or the regression) reads at a glance.

## Also available

Newer, less battle-tested than the profiling loop above — **feedback welcome**:

- **Guard CI** against a regression (`benchmem compare … --fail-on peak:10%`) or against an absolute
  ceiling (`@pytest.mark.benchmem(max_peak="500MiB")`).
- **Plot** scaling curves straight from your `parametrize` params (`benchmem plot run.json --columns
  peak`), and **sweep** a metric across installed package versions (`benchmem sweep mypkg 1.2 1.3 main`).
- **`rss`** — the whole-process physical peak the OOM killer watches — via
  `@pytest.mark.benchmem(isolate=True)`, for container/capacity questions.

## Why memray, and where it sits

memray tracks the allocator directly. It catches the numpy/C-allocation detail that RSS sampling
(ASV's `peakmem`) misses, and folds out the interpreter baseline. pytest-benchmem uses
pytest-benchmark for timing and reads and writes its JSON. It does not reimplement timing, a CI
dashboard ([CodSpeed]), or cross-commit history ([ASV]).

**For continuous CI tracking, reach for [CodSpeed]** — history, dashboards, PR annotations. It runs
pytest-benchmark's `benchmark()` too, so the *same tests* serve both: write the benchmark once, let
CodSpeed watch timing in CI and pytest-benchmem profile memory on demand. No rewrite, no second set
of benchmarks.

**vs [pytest-memray]:** both wrap memray, pointed in opposite directions, and they complement each
other. pytest-memray is a guardrail — `limit_memory` and leak detection over the whole test.
pytest-benchmem is a benchmark: only the benchmarked action, measured alongside timing, then
profiled, compared, and plotted across inputs and versions.

## Install

```bash
uv add pytest-benchmem            # the fixture + flag + memray engine
uv add "pytest-benchmem[plot]"    # + the benchmem plot/compare/sweep CLI (pandas, plotly, typer)
```

memray is Linux/macOS only; Windows installs cleanly with timing-only (the memory pass raises a
clear error there).

## Status

Early — extracted from the linopy benchmark suite. The measure → profile → fix loop is the hardened
core; the *Also available* features are newer and may move before 1.0. See the
[changelog](https://github.com/fluxopt/pytest-benchmem/blob/main/CHANGELOG.md).

[pytest-benchmark]: https://pytest-benchmark.readthedocs.io
[pytest-memray]: https://pytest-memray.readthedocs.io
[CodSpeed]: https://codspeed.io
[ASV]: https://asv.readthedocs.io
