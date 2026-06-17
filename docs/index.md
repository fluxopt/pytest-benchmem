# pytest-benchmem

The memory companion to [pytest-benchmark](https://pytest-benchmark.readthedocs.io). A
**drop-in** for your existing suite: add one flag and a memray **peak-memory** number lands
next to the timing — same test, same run, one JSON file. No test changes.

```python
@pytest.mark.parametrize("n", [10_000, 100_000, 1_000_000])
def test_sort(benchmark, n):          # your existing pytest-benchmark test, unchanged
    benchmark(sorted, list(range(n, 0, -1)))
```

Peak appears in pytest-benchmark's own table, appended after the timing columns — no
second tool:

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

## Is this for you?

**Reach for it when** you already use pytest-benchmark (or want to) and want a memory
number on the *same* benchmarks — peak footprint, allocation churn, or a CI gate that
fails a PR when memory regresses.

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
| Know which of peak / allocated / allocations to track | [Choosing a metric](metrics.md) |
| Diff two runs and fail CI on a regression | [Compare & gate CI](compare-plot.ipynb) |
| Slice plots and tables by an axis (input size, op, …) | [Grouping by dims](dims.md) |
| Benchmark across installed versions of a package | [Cross-version sweeps](sweeps.md) |
| Look up a specific flag, marker, or function | [Reference](reference.md) |

## Status

Early. Extracted from the linopy internal benchmark suite, where it's the local
memory-profiling layer. The API may move before 1.0.
