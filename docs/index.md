# pytest-benchmem

Measure how much memory your code allocates, on the same benchmarks you already time. For
Python libraries and pipelines where memory is a real constraint — large numpy arrays,
pandas frames, solvers, C/Cython/Rust extensions. Track it in CI the way you track
performance, and fail a PR when the footprint grows.

It builds on [pytest-benchmark](https://pytest-benchmark.readthedocs.io). Take an existing
test — you don't change it:

```python
@pytest.mark.parametrize("n", [10_000, 100_000, 1_000_000])
def test_sort(benchmark, n):          # your existing pytest-benchmark test, unchanged
    benchmark(sorted, list(range(n, 0, -1)))
```

Add one flag, and peak memory appears in pytest-benchmark's own table, after the timing
columns. Same test, same run, one JSON file, no second tool:

<!-- termynal -->

```console
$ pytest --benchmark-only --benchmark-memory
 Name (time in us)              Min                  Median         │  peak (MiB)
 ──────────────────────────────────────────────────────────────────────────────
  test_sort[10000]           32.5830 (1.0)         41.2080 (1.0)    │       0.08
  test_sort[100000]         321.2080 (9.86)       419.9160 (10.19)  │       0.76
  test_sort[1000000]      3,669.2920 (112.61)   4,331.5421 (105.11) │       7.63
```

[Quickstart →](getting-started.md){ .md-button .md-button--primary }

## Plots from your params

Your `parametrize` params become plot axes on their own — no id parsing, no config. The `n`
above is a numeric x-axis, so `benchmem plot` draws a scaling curve from it. The plots read
pytest-benchmark's JSON, so they work on your timing results too, not just memory:

```bash
benchmem plot run.json --columns peak     # peak vs n
benchmem plot run.json --columns time     # the same axis, timing instead
```

See [Grouping by dims](dims.md) for how params, `extra_info`, and `node.*` map to axes.

## Is this for you?

**Yes, if** you maintain code where memory is a real constraint — large arrays, dataframes,
solvers, C/Rust extensions — and you want a footprint regression to fail a PR the way a
slowdown does. You measure it on the benchmarks you already time, at allocator precision,
and gate, plot, or sweep it across inputs and versions.

**Look elsewhere when** you want a whole-test memory limit or leak check rather than a
number on one benchmarked call — that's [pytest-memray](https://pytest-memray.readthedocs.io).
For where it sits against ASV, CodSpeed, and plain memray, see the
[README](https://github.com/fluxopt/pytest-benchmem#why-memray-and-where-it-sits).

!!! note "Want memory on specific tests only?"
    `--benchmark-memory` measures the whole suite. To opt in per test instead, swap
    `benchmark` for the `benchmark_memory` fixture on just those tests — it's always
    measured, and adds a `pedantic` form for explicit control. See the
    [Quickstart](getting-started.md).

## Install

=== "Core"

    The `benchmark_memory` fixture + the memray engine.

    ```bash
    uv add pytest-benchmem
    ```

=== "With plots & CLI"

    Adds the `benchmem` compare/plot/sweep CLI (pandas, plotly, typer).

    ```bash
    uv add "pytest-benchmem[plot]"
    ```

pytest-benchmark and memray are core deps. The memory pass needs memray, which is
**Linux/macOS only** — timing works everywhere.

## Where to next

| If you want to… | Go to |
|---|---|
| Run your first benchmark and read both metrics | [Quickstart](getting-started.md) |
| Know which of peak / allocated / allocations / rss to track | [Choosing a metric](metrics.md) |
| Diff two runs and see what moved | [Compare two runs](compare-runs.md) |
| Fail CI when memory grows | [Catch regressions in CI](catch-regressions.md) |
| Find where the memory actually goes | [Find where memory goes](profiling.md) |
| Slice plots and tables by an axis (input size, op, …) | [Grouping by dims](dims.md) |
| Benchmark across installed versions of a package | [Cross-version sweeps](sweeps.md) |
| Look up a specific flag, marker, or function | [Reference](reference.md) |

## Status

Early. Extracted from the linopy internal benchmark suite, where it's the local
memory-profiling layer. The API may move before 1.0.
