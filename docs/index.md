# pytest-benchmem

**The memory companion to [pytest-benchmark](https://pytest-benchmark.readthedocs.io).**
It times your code; pytest-benchmem adds a memray **peak-memory** pass to the *same
test, in the same run* — one node id, one JSON file, both metrics. Plus dims-aware
plots and cross-version sweeps it has no answer for.

Its reason to exist is the gap nothing else fills cleanly: **memray-precision
memory benchmarking** of your own code, right where you already benchmark. ASV's
`peakmem` is coarse RSS sampling; CodSpeed covers CI timing. pytest-benchmem is the thin
memray layer on top of pytest-benchmark.

## Install

```bash
uv add pytest-benchmem            # the benchmark_memory fixture + memray engine
uv add "pytest-benchmem[plot]"    # + the plot/compare CLI (pandas, plotly, typer)
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
*and* `extra_info.benchmem` (peak memory in bytes + allocation count, from
pytest-benchmem). The two passes never overlap, so memray's hooks cost the timing
nothing; parametrize `params` become the dims the plots scale by.

Because memory rides a *separate* invocation (after the timing passes), the
benchmarked code must be safe to re-run — a side-effectful call records its
already-warmed state, not a cold one. Benchmark a pure call, or use the
`benchmark_memory` `pedantic` form with a `setup` that rebuilds fresh state.

## Grouping axes (dims)

Every plot and `compare` groups by **dims** — the axes a result varies over. Dims
come from two places, no id parsing:

- your `@pytest.mark.parametrize` **`params`**, and
- any scalar you put in **`benchmark_memory.extra_info`**.

`params` covers the common case for free — `parametrize("n", [...])` gives you an
`n` axis. Only **scalars** (`str`/`int`/`float`) become dims; a `list`/`dict`, or
an object pytest-benchmark couldn't serialize, is dropped — it's not a usable axis.

So when the thing you want to group by *isn't* a plain scalar param, add it
yourself via `extra_info` — you choose the name and the value:

```python
# An operation/phase axis, when you have one test function per operation.
# (params can't carry it — it lives in the function name, which dims never parse.)
def test_to_lp(benchmark_memory):
    benchmark_memory.extra_info["phase"] = "to_lp"   # → a dim named "phase"
    benchmark_memory(model.to_lp, path)
```

Set it once for a whole suite with an autouse fixture instead of per test:

```python
# conftest.py — label every benchmark with its function name as "phase"
import pytest


@pytest.fixture(autouse=True)
def _phase(request, benchmark_memory):
    benchmark_memory.extra_info["phase"] = request.node.function.__name__
```

**Parametrizing over a complex object?** Don't rely on the object as a dim — it
serializes to an opaque `UNSERIALIZABLE[...]` string and gets dropped. Pass a
*meaningful scalar* derived from it instead:

```python
@pytest.mark.parametrize("spec", [BenchSpec("basic", n=10), BenchSpec("dense", n=250)])
def test_solve(benchmark_memory, spec):
    benchmark_memory.extra_info["case"] = spec.name   # "basic" / "dense" — a clean label axis
    benchmark_memory.extra_info["n"] = spec.n          # numeric → usable as a scaling x axis
    # no obvious field? fall back to a stable scalar: str(spec) / a short id / a hash
    benchmark_memory(solve, spec)
```

A scalar *field* (`spec.name`, `spec.n`) makes the best axis — readable label, and
a numeric one can be the x of a scaling plot. Reach for `str(spec)` only when
there's no better handle; it's still far better than the dropped object.

> Using the plain `benchmark` fixture (or `--benchmark-memory`)? Same recipe —
> write to `benchmark.extra_info` exactly as above.

## Next

→ The **[Walkthrough](walkthrough.ipynb)** runs it end-to-end: write a suite,
execute it, read both metrics back, then `compare` / `plot` them — per metric.

See the [README on GitHub](https://github.com/fluxopt/pytest-benchmem) for where
pytest-benchmem sits relative to CodSpeed / ASV / pytest-benchmark.
