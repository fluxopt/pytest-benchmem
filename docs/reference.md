---
jupytext:
  text_representation:
    extension: .md
    format_name: myst
    format_version: 0.13
    jupytext_version: 1.19.3
kernelspec:
  display_name: Python 3 (ipykernel)
  language: python
  name: python3
---

# Reference

Every flag, marker, fixture, CLI command, and public function. The `benchmem` CLI
options are rendered live from `--help` below; everything else — pytest flags, the
marker, the fixture, the blob schema, the Python API — is curated here. For the
narrative versions see [Getting started](getting-started.ipynb),
[Metrics](metrics.ipynb), [Dims](dims.ipynb), and [Compare & plot](compare-plot.ipynb).

```{code-cell} ipython3
import os
import sys
from pathlib import Path

os.environ["FORCE_COLOR"] = "1"
os.environ["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"
```

## pytest command-line flags

The plugin adds these to any pytest run (alongside pytest-benchmark's own flags):

| Flag | Default | What |
|---|---|---|
| `--benchmark-memory` | off | record peak memory for **every** `benchmark()` call, no test changes. (The `benchmark_memory` fixture is always measured, with or without this flag.) |
| `--benchmark-memory-repeats=N` | `1` | default memray passes per benchmark, suite-wide (reported peak is the min). Per-test `@pytest.mark.benchmem(repeats=N)` overrides it. |
| `--benchmark-memory-columns=…` | `peak` | which memory metrics the table shows, comma-separated and in order: `peak`, `allocated`, `allocs`. Default is peak only; the table captions the rest as available. |
| `--benchmark-memory-stats=…` | `min,mean,max` | when a benchmark is measured more than once (`repeats > 1`), the stats each shown metric spreads into: `min`, `mean`, `max`, `median`, `stddev`. A single pass stays one column. |
| `--benchmark-memory-compare[=REF]` | off | compare this run's peak memory against a prior saved run (latest, or a pytest-benchmark storage ref like `0001`); folds `base` + `Δ peak` columns into the combined table. |
| `--benchmark-memory-compare-fail=FIELD:THRESHOLD` | — | fail the session on a memory regression (repeatable). Implies `--benchmark-memory-compare`. Fields: `peak`, `allocated`, `allocations`. |

Timing regressions still use pytest-benchmark's own `--benchmark-compare` /
`--benchmark-compare-fail`; the `--benchmark-memory-compare*` flags are the memory
mirror. Their baseline comes from pytest-benchmark's storage (`.benchmarks/`) — save
one first with `--benchmark-save=NAME` or `--benchmark-autosave`, or the gate finds
nothing and passes. See [Gate CI on regressions](compare-plot.ipynb#gate-ci-on-regressions).

## The `benchmem` marker

```python
@pytest.mark.benchmem(repeats=3)
def test_build(benchmark_memory):
    ...
```

| Kwarg | Default | What |
|---|---|---|
| `repeats` | `1` | measure this test with `N` memray passes. **Every** pass is kept (the blob stores the whole series); the headline `peak` is the *minimum* across them, and `--stat` reports any other. Overrides the suite-wide `--benchmark-memory-repeats` for this test. |
| `max_peak` | — | fail the test if the headline `peak` exceeds this **absolute** ceiling. A size string (`"100MiB"`, units `B`/`KiB`/`MiB`/`GiB`) or a bare int (bytes). |
| `max_allocated` | — | as `max_peak`, on `allocated` (total bytes). |
| `max_allocations` | — | as above, on the `allocations` *count* — a bare number (no unit). |

### Absolute ceilings — `max_peak` / `max_allocated` / `max_allocations`

```python
@pytest.mark.benchmem(max_peak="100MiB", max_allocations=5000)
def test_build(benchmark_memory):
    benchmark_memory(build_model, 1000)
```

A baseline-free guardrail: the test **fails** if the measured headline metric exceeds the
ceiling (`test_build: peak 117 MiB exceeds max_peak 100 MiB`). Thresholds are **absolute
only** — there's no saved run to take a percent of; for *relative* gating against a prior run
use `--benchmark-memory-compare-fail` or `benchmem compare --fail-on`. With `repeats > 1` the
gate reads the **headline min** (the same value the table and JSON report), so it's the
cleanest floor. The ceiling is enforced wherever memory is measured — the `benchmark_memory`
fixture *and* the `--benchmark-memory` patch — but a plain `benchmark()` call without
`--benchmark-memory` measures no memory, so the marker is a no-op there.

> **Scope:** this gates the **benchmarked action only** (the isolated call pytest-benchmem
> measures), not the whole test. For a *whole-test* limit or leak check, that's
> [pytest-memray]'s `limit_memory` / `limit_leaks` — see the README's "With pytest-memray".

[pytest-memray]: https://pytest-memray.readthedocs.io

Why once, when timing reruns many times? Peak memory is allocator demand — the bytes
your code requests for a given code path and inputs — not a wall-clock number, so it's
near-deterministic and one pass is usually representative. Raise `repeats` when the peak
*isn't* deterministic (hash randomization, GC timing, randomized inputs) to settle the
min floor and quantify the spread (the `min`/`mean`/`max` columns and `--stat stddev`).

## The `benchmark_memory` fixture

Depends on pytest-benchmark's `benchmark` fixture; times via pytest-benchmark, then
measures peak in a separate untimed pass.

**Order — timing first, then memory.** Every call form runs pytest-benchmark's timing
(calibration + all rounds) first, then the memray pass — so memory is measured on an
already-warmed function and the allocator hooks never touch the timing. This holds for
`__call__`, `pedantic`, and the `--benchmark-memory` patch alike. (The standalone
`measure_peak` / `measure_memory` have no timing phase, so they measure cold — warm up
first, or use `repeats > 1`, if a cold first call would distort the peak.)

**Call form** — times then measures `function(*args, **kwargs)`:

```python
benchmark_memory(sorted, data)
```

**Pedantic form** — explicit control, like pytest-benchmark's `pedantic` plus a
memory pass:

```python
benchmark_memory.pedantic(target, args=(), kwargs=None, setup=None,
                          rounds=1, warmup_rounds=0, iterations=1)
```

- `setup` — a callable run *untracked* before each measured call; if it returns
  `(args, kwargs)`, those supply the call's arguments. Use it to rebuild fresh state
  each round, essential for side-effectful workloads.
- `rounds`, `warmup_rounds`, `iterations` — as in pytest-benchmark.

**Mostly memory, little timing?** There's no memory-only switch — the entry rides
pytest-benchmark's timing. To trim it: `--benchmark-min-rounds=1 --benchmark-max-time=0`
(no test changes), or `pedantic(rounds=1, warmup_rounds=0)` for a single call. For pure
memory outside pytest, use `measure_peak` / `measure_memory`.

**Attributes** (available after a call):

| Attribute | What |
|---|---|
| `extra_info` | pytest-benchmark's per-benchmark dict. Set scalars here to attach analysis [dims](dims.ipynb); the memory blob lands here under the `benchmem` key. |
| `peak_bytes` | peak memory (bytes) from the last call, or `None` before any call. |
| `result` | the full `MemoryResult` from the last call, or `None`. |

## The `extra_info.benchmem` blob

Each measured benchmark stores this dict under `extra_info["benchmem"]` — three flat
per-repeat series, one entry per memray pass. Every reported number (headline `peak` =
min, any `--stat`) derives from these on read:

| Key | What |
|---|---|
| `peak_bytes` | per-repeat high-water of live bytes — the `peak` metric (headline = min) |
| `allocations` | per-repeat allocation count — the `allocations` metric |
| `total_bytes` | per-repeat total bytes allocated — the `allocated` metric (churn `peak` hides) |

```json
{"peak_bytes": [800000, 805000], "allocations": [12, 12], "total_bytes": [800000, 805000]}
```

See [Metrics](metrics.ipynb) for when to reach for each, and `--stat` for distributions.

## CLI — `benchmem`

Installed with `pytest-benchmem[plot]`. The two subcommands and their options,
straight from `--help`:

```{code-cell} ipython3
!benchmem --help
```

### `benchmem compare`

A per-id delta table (`b − a`) with percent change; ids in only one run show `—`.

```{code-cell} ipython3
!benchmem compare --help
```

**`--metric`** is one of `time`, `peak`, `allocated`, `allocations`, or `memory` (an
alias for `peak`); pair it with **`--stat`** (`min`/`max`/`mean`/`median`/`stddev`) for a
distribution over the per-repeat series. **`--fail-on FIELD:THRESHOLD`** (repeatable) exits
non-zero past a threshold; `FIELD` is `peak`, `allocated`, `allocations`, or `time`,
and `THRESHOLD` is either a **percent** (`peak:10%`) or an **absolute**:

- bytes fields (`peak`, `allocated`): `5MiB` (units `B`/`KiB`/`MiB`/`GiB`)
- `allocations`: a bare count, `5`
- `time`: `1ms` (units `s`/`ms`/`us`/`µs`/`ns`)

### `benchmem plot`

Writes an interactive plotly view to standalone HTML. The view auto-selects by run
count (1 → `scaling`, 2 → `scatter`, 3+ → `sweep`); override with `--view`.

```{code-cell} ipython3
!benchmem plot --help
```

`--facet` and `--label`/`-l` (a series label per run, repeatable, defaulting to the
file stem) accept the same [dims](dims.ipynb) your tests carry.

## Public Python API

Light to import — `pytest_benchmem` re-exports only the engine and the readers;
`pytest_benchmem.plotting` pulls plotly and `pytest_benchmem.sweep` shells to `uv`,
so import those submodules directly.

### Engine — `pytest_benchmem`

```python
measure_peak(action, repeats=1) -> int
measure_memory(action, repeats=1) -> MemoryResult
```

`action` is a zero-arg callable. `measure_peak` returns the bare peak in bytes;
`measure_memory` returns the full `MemoryResult` (`peak_bytes`, `peak_bytes_max`,
`allocations`, `total_bytes`, `repeats`).

### Readers & loader — `pytest_benchmem`

```python
from_pytest_benchmark(path, *, metric="min") -> (label, [Sample], unit)
memory_from_pytest_benchmark(path, *, field="peak_bytes") -> (label, [Sample], unit)
load_samples(path, *, metric="time", stat="min") -> (label, [Sample], unit)
load_long_df(runs, *, metric="time", stat="min") -> (DataFrame, unit)
discover_runs(root=".benchmarks") -> [Path]
human_bytes(n) -> str
```

- `from_pytest_benchmark` reads **timing** (seconds, from `stats`);
  `memory_from_pytest_benchmark` reads **memory** (bytes, from `extra_info.benchmem`).
  `load_samples` is the unified reader — `metric` is one of `time`/`peak`/`allocated`/
  `allocations`; `stat` (time only) is `min`/`median`/…
- `load_long_df` stacks runs into the tidy frame the plots pivot — columns
  `snapshot`, `id`, `value`, plus one per [dim](dims.ipynb).
- `discover_runs()` collects saved runs from `.benchmarks/` — pytest-benchmark's
  storage dir, where `--benchmark-save` / `--benchmark-autosave` write — so you can
  hand the readers a directory instead of listing files.
- A `Sample` is `(id, value, dims)`; `dims` is a mapping of dim name → `str`/`int`/
  `float`.

### Plotting — `pytest_benchmem.plotting`

Every `plot_*` returns `(figure, n_ids)`:

```python
plot_scaling(snapshots, *, metric="time", x=None, color=None, facet=None, log="auto", labels=None)
plot_scatter(snapshots, *, metric="time", facet=None, clip=None, labels=None)
plot_compare(snapshots, *, metric="time", sort="absolute", facet=None, clip=None, labels=None)
plot_sweep(snapshots,  *, metric="time", clip=None, labels=None)
```

`snapshots` is a list of run JSON paths. `labels` names the series per run (defaults
to the file stems) — the API behind `plot`'s `-l/--label`. `plot_compare`'s `sort` is
`"absolute"` (native units) or `"relative"` (percent).

### Sweeps — `pytest_benchmem.sweep`

```python
sweep(versions, run, **provision_kwargs) -> [failed_version_label]
```

See **[Cross-version sweeps](sweeps.md)** for the parameters and the `Venv` object.
