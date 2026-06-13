# peakbench

**The memory companion to [pytest-benchmark](https://pytest-benchmark.readthedocs.io).**
It times your code; peakbench adds a memray **peak-memory** pass to the *same
test, in the same run* — one node id, one JSON file, both metrics. Plus dims-aware
plots and cross-version sweeps it has no answer for.

Its reason to exist is the gap nothing else fills cleanly: **memray-precision
memory benchmarking** of your own code, right where you already benchmark. ASV's
`peakmem` is coarse RSS sampling; CodSpeed covers CI timing. peakbench is the thin
memray layer on top of pytest-benchmark.

## Install

```bash
uv add peakbench            # the benchmark_memory fixture + memray engine
uv add "peakbench[plot]"    # + the plot/compare CLI (pandas, plotly, typer)
```

pytest-benchmark and memray are core deps; memray is Linux/macOS only.

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

One run, one file: each benchmark id gets `stats` (timing, from pytest-benchmark)
*and* `extra_info.peak_mib` (peak memory, from peakbench). The two passes never
overlap, so memray's hooks cost the timing nothing; parametrize `params` become
the dims the plots scale by.

## Next

→ The **[Walkthrough](walkthrough.ipynb)** runs it end-to-end: write a suite,
execute it, read both metrics back, then `compare` / `plot` them — per metric.

See the [README on GitHub](https://github.com/fluxopt/peakbench) for where
peakbench sits relative to CodSpeed / ASV / pytest-benchmark.
