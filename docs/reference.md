# Reference

Every flag, marker, fixture, CLI command, and public function. The CLI and Python API
below are rendered live from the source; the pytest surface (flags, marker, fixture, blob
schema) is curated here. For the narrative versions see [Quickstart](getting-started.md),
[Choosing a metric](metrics.md), [Grouping by dims](dims.md), and
[Compare & gate CI](compare-plot.ipynb).

## pytest command-line flags

The plugin adds these to any pytest run (alongside pytest-benchmark's own flags). This
table is generated from the plugin's own `--help` text, so it can't drift from the code:

[[[ pytest_flags_table() ]]]

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
| `repeats` | *auto* | force a fixed `N` memray passes for this test (default: adaptive — see below). **Every** pass is kept (the blob stores the whole series); the headline `peak` is the *minimum* across them, and `--stat` reports any other. Overrides the suite-wide `--benchmark-memory-repeats`. |
| `max_peak` | — | fail the test if the headline `peak` exceeds this **absolute** ceiling. A size string (`"100MiB"`, units `B`/`KiB`/`MiB`/`GiB`) or a bare int (bytes). |
| `max_allocated` | — | as `max_peak`, on `allocated` (total bytes). |
| `max_allocations` | — | as above, on the `allocations` *count* — a bare number (no unit). |

### Absolute ceilings — `max_peak` / `max_allocated` / `max_allocations`

```python
@pytest.mark.benchmem(max_peak="100MiB", max_allocations=5000)
def test_build(benchmark_memory):
    benchmark_memory(build_model, 1000)
```

A baseline-free guardrail: the test **fails** if the measured metric exceeds the
ceiling (`test_build: peak 117 MiB exceeds max_peak 100 MiB`). Thresholds are **absolute
only** — there's no saved run to take a percent of; for *relative* gating against a prior run
use `--benchmark-memory-compare-fail` or `benchmem compare --fail-on`. A ceiling is a
worst-case budget, so with `repeats > 1` (including adaptive sampling) the gate reads the
**worst pass** — not the headline min — and fails if *any* pass breaches it; the two coincide
for a single pass. The ceiling is enforced wherever memory is measured — the `benchmark_memory`
fixture *and* the `--benchmark-memory` patch — but a plain `benchmark()` call without
`--benchmark-memory` measures no memory, so the marker is a no-op there.

!!! note "Scope: the benchmarked action only"
    This gates the **benchmarked action only** (the isolated call pytest-benchmem
    measures), not the whole test. For a *whole-test* limit or leak check, that's
    [pytest-memray](https://pytest-memray.readthedocs.io)'s `limit_memory` / `limit_leaks`
    — see the README's "With pytest-memray".

How many passes? By default pytest-benchmem **samples adaptively** — it runs the memray pass
until the headline `min` floor settles (≥2 passes, so warmup is shed; capped at 10, or a
`--benchmark-memory-max-time` budget). Deterministic code settles in ~3 passes; noisy code runs
more. Set `repeats=N` (marker) or `--benchmark-memory-repeats=N` (suite) to force a fixed,
reproducible count — what CI gating against a saved baseline wants. Full rationale and the
noisy-workload guidance are in the guide: [Repeats & adaptive sampling](metrics.md#repeats-adaptive-sampling).

## The `benchmark_memory` fixture

Depends on pytest-benchmark's `benchmark` fixture; times via pytest-benchmark, then
measures peak in a separate untimed pass.

!!! info "Order — timing first, then memory"
    Every call form runs pytest-benchmark's timing (calibration + all rounds) first, then
    the memray pass — so memory is measured on an already-warmed function and the allocator
    hooks never touch the timing. This holds for `__call__`, `pedantic`, and the
    `--benchmark-memory` patch alike. (The standalone `measure_peak` / `measure_memory`
    have no timing phase, so the first pass is cold — but they sample adaptively the same way
    by default, taking ≥2 passes so the min discards that cold pass; pass `repeats=N` to
    force a fixed count instead.)

=== "Call form"

    Times then measures `function(*args, **kwargs)`:

    ```python
    benchmark_memory(sorted, data)
    ```

=== "Pedantic form"

    Explicit control, like pytest-benchmark's `pedantic` plus a memory pass:

    ```python
    benchmark_memory.pedantic(target, args=(), kwargs=None, setup=None,
                              rounds=1, warmup_rounds=0, iterations=1)
    ```

    - `setup` — a callable run *untracked* before each measured call; if it returns
      `(args, kwargs)`, those supply the call's arguments. Used for **both** the timed rounds
      **and** each (adaptive) memory sample — one `setup` rebuilds fresh state for both — so a
      stateful action's memory samples stay independent. The same applies to
      `benchmark.pedantic(setup=…)` under `--benchmark-memory`: no extra changes.
    - `rounds`, `warmup_rounds`, `iterations` — as in pytest-benchmark.

**Mostly memory, little timing?** There's no memory-only switch — the entry rides
pytest-benchmark's timing. To trim it: `--benchmark-min-rounds=1 --benchmark-max-time=0`
(no test changes), or `pedantic(rounds=1, warmup_rounds=0)` for a single call. For pure
memory outside pytest, use `measure_peak` / `measure_memory`.

**Attributes** (available after a call):

| Attribute | What |
|---|---|
| `extra_info` | pytest-benchmark's per-benchmark dict. Set scalars here to attach analysis [dims](dims.md); the memory blob lands here under the `benchmem` key. |
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

See [Choosing a metric](metrics.md) for when to reach for each, and `--stat` for distributions.

## CLI — `benchmem`

Installed with `pytest-benchmem[plot]`. The full command tree and every option, rendered
live from the typer app:

::: mkdocs-typer2
    :module: pytest_benchmem.cli
    :name: benchmem

## Public Python API

Light to import — `pytest_benchmem` re-exports only the engine and the readers;
`pytest_benchmem.plotting` pulls plotly and `pytest_benchmem.sweep` shells to `uv`,
so import those submodules directly.

### Engine

::: pytest_benchmem.measure_peak
::: pytest_benchmem.measure_memory
::: pytest_benchmem.MemoryResult
::: pytest_benchmem.Measurement

### Readers & loader

`from_pytest_benchmark` reads **timing** (seconds, from `stats`);
`memory_from_pytest_benchmark` reads **memory** (bytes, from `extra_info.benchmem`).
`load_samples` is the unified reader; `load_long_df` stacks runs into the tidy frame the
plots pivot. `discover_runs` collects saved runs from pytest-benchmark's `.benchmarks/`
storage, so you can hand the readers a directory instead of listing files.

::: pytest_benchmem.from_pytest_benchmark
::: pytest_benchmem.memory_from_pytest_benchmark
::: pytest_benchmem.load_samples
::: pytest_benchmem.load_long_df
::: pytest_benchmem.discover_runs
::: pytest_benchmem.Sample

### Plotting — `pytest_benchmem.plotting`

Every `plot_*` returns `(figure, n_ids)`. `snapshots` is a list of run JSON paths;
`labels` names the series per run (defaults to the file stems) — the API behind `plot`'s
`-l/--label`. `plot_compare`'s `sort` is `"absolute"` (native units) or `"relative"`
(percent).

::: pytest_benchmem.plotting.plot_scaling
::: pytest_benchmem.plotting.plot_scatter
::: pytest_benchmem.plotting.plot_compare
::: pytest_benchmem.plotting.plot_sweep

### Sweeps — `pytest_benchmem.sweep`

See [Cross-version sweeps](sweeps.md) for the narrative, the `Venv` object, and the
`provision` parameters.

::: pytest_benchmem.sweep.sweep
