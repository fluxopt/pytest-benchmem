# Quickstart

pytest-benchmem is a **drop-in** for an existing pytest-benchmark suite: add one flag and
every `benchmark(...)` call records peak memory too — no test changes. The memray pass is
Linux/macOS only; timing works everywhere.

## 1. You already have a benchmark

A normal pytest-benchmark test — nothing pytest-benchmem-specific. If you have a suite
already, you're done with this step:

```python
# test_sortbench.py
import pytest


@pytest.mark.parametrize("n", [10_000, 100_000, 1_000_000])
def test_sort(benchmark, n):
    benchmark(sorted, list(range(n, 0, -1)))
```

## 2. Run it with `--benchmark-memory`

Add the flag and peak memory appends to pytest-benchmark's own table:

```bash
pytest test_sortbench.py --benchmark-only --benchmark-memory
```

```
 Name (time in us)              Min                  Median         │  peak (MiB)
 ──────────────────────────────────────────────────────────────────────────────
  test_sort[10000]           32.5830 (1.0)         41.2080 (1.0)    │       0.08
  test_sort[100000]         321.2080 (9.86)       419.9160 (10.19)  │       0.76
  test_sort[1000000]      3,669.2920 (112.61)   4,331.5421 (105.11) │       7.63
```

That's it. Left of the divider is pytest-benchmark's timing, untouched; `peak` (right) is a
separate, untimed memray pass on the same call — so the allocator hooks cost the timing
nothing. It's opt-in at the run level: **without** the flag, your suite runs exactly as
before. Add `--benchmark-json=run.json` to save both metrics to one file.

## 3. Where to go next

- Want `allocated` / `allocations` too, or a different table layout? → [Choosing a metric](metrics.md)
- Want to diff two runs or fail CI on a regression? → [Compare & gate CI](compare-plot.ipynb)
- Want to slice tables and plots by an axis (input size, op, …)? → [Grouping by dims](dims.md)

---

## Going further

!!! tip "Want memory on specific tests only? Use the `benchmark_memory` fixture"
    `--benchmark-memory` measures the whole suite. To opt **in** per test instead — no
    run-level flag — swap `benchmark` for `benchmark_memory` on just those tests; it's
    always measured:

    ```python
    def test_sort(benchmark_memory, n):
        benchmark_memory(sorted, list(range(n, 0, -1)))
    ```

    The fixture also gives you the [`pedantic` form](reference.md#the-benchmark_memory-fixture)
    for explicit control (a `setup` that rebuilds fresh state each round, custom rounds).

!!! warning "Your benchmark must be safe to re-run"
    Memory rides a *separate* invocation, after pytest-benchmark has already called your
    function many times for timing — so a side-effectful call (mutates a fixture, fills a
    cache, drains an iterator) silently records its **warmed** state, not a cold one.
    Benchmark a pure call, or use the
    [`pedantic` form](reference.md#the-benchmark_memory-fixture) with a `setup` that rebuilds
    fresh state each round.

### Read the numbers back in Python

`load_long_df` stacks one or more saved run JSONs into a tidy frame — one row per
`(run, id)` for the chosen metric, one column per [dim](dims.md):

```python
from pytest_benchmem import load_long_df

df, unit = load_long_df(["run.json"], metric="peak")   # unit: "B"
```

For the per-metric readers and the bare `measure_peak` engine, see the
[Reference](reference.md#public-python-api).
