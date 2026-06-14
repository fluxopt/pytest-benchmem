# Reference

Every flag, marker, fixture, CLI command, and public function — in one place. For the
narrative versions see [Getting started](getting-started.ipynb), [Metrics](metrics.ipynb),
[Dims](dims.ipynb), and [Compare & plot](compare-plot.ipynb).

## pytest command-line flags

The plugin adds these to any pytest run (alongside pytest-benchmark's own flags):

| Flag | Default | What |
|---|---|---|
| `--benchmark-memory` | off | record peak memory for **every** `benchmark()` call, no test changes. (The `benchmark_memory` fixture is always measured, with or without this flag.) |
| `--benchmark-memory-compare[=REF]` | off | compare this run's peak memory against a prior saved run (latest, or a pytest-benchmark storage ref like `0001`); prints a per-id memory delta in the summary. |
| `--benchmark-memory-compare-fail=FIELD:THRESHOLD` | — | fail the session on a memory regression (repeatable). Implies `--benchmark-memory-compare`. Fields: `peak`, `allocated`, `allocations`. |

Memory rides `--benchmark-only` runs the same as timing. Timing regressions still use
pytest-benchmark's own `--benchmark-compare` / `--benchmark-compare-fail`; the
`--benchmark-memory-compare*` flags are the memory mirror.

## The `benchmem` marker

```python
@pytest.mark.benchmem(repeats=3)
def test_build(benchmark_memory):
    ...
```

| Kwarg | Default | What |
|---|---|---|
| `repeats` | `1` | run `N` memray passes and keep the **min** — peak memory is noisy (GC timing, lazy imports, page cache), so min-of-N is the cleanest floor. |

## The `benchmark_memory` fixture

Depends on pytest-benchmark's `benchmark` fixture; times via pytest-benchmark, then
measures peak in a separate untimed pass.

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

**Attributes** (available after a call):

| Attribute | What |
|---|---|
| `extra_info` | pytest-benchmark's per-benchmark dict. Set scalars here to attach analysis [dims](dims.ipynb); the memory blob lands here under the `benchmem` key. |
| `peak_bytes` | peak memory (bytes) from the last call, or `None` before any call. |
| `result` | the full `MemoryResult` from the last call, or `None`. |

## The `extra_info.benchmem` blob

Each measured benchmark stores this dict under `extra_info["benchmem"]` (the
serialized `MemoryResult`):

| Key | What |
|---|---|
| `peak_bytes` | high-water of live bytes — the `peak` metric |
| `peak_bytes_max` | worst peak across `repeats` — the `peak_max` metric |
| `allocations` | total allocation count — the `allocations` metric |
| `total_bytes` | total bytes allocated — the `allocated` metric (catches churn `peak` hides) |
| `repeats` | number of passes |
| `mode` | the metric family, `"heap"`; readers refuse to compare across modes |

See [Metrics](metrics.ipynb) for when to reach for each.

## CLI — `benchmem`

Installed with `pytest-benchmem[plot]`. Both subcommands take `--metric`, one of:
`time`, `peak`, `peak_max`, `allocated`, `allocations`, or `memory` (an alias for
`peak`).

### `benchmem compare`

```bash
benchmem compare BASE.json HEAD.json --metric peak
benchmem compare BASE.json HEAD.json --fail-on peak:10% --fail-on allocations:5%
```

A per-id delta table (`b − a`) with percent change; ids in only one run show `—`.

| Option | Default | What |
|---|---|---|
| `--metric` | `time` | which metric to diff |
| `--fail-on FIELD:THRESHOLD` | — | exit non-zero past a threshold (repeatable). |

**`--fail-on` grammar.** `FIELD` is `peak`, `allocated`, `allocations`, or `time`.
`THRESHOLD` is either a **percent** (`peak:10%`) or an **absolute**:

- bytes fields (`peak`, `allocated`): `5MiB` (units `B`/`KiB`/`MiB`/`GiB`)
- `allocations`: a bare count, `5`
- `time`: `1ms` (units `s`/`ms`/`us`/`µs`/`ns`)

### `benchmem plot`

```bash
benchmem plot RUN.json [RUN2.json …] --metric peak -o out.html
```

Writes an interactive plotly view to standalone HTML. View auto-selects by run count
(1 → `scaling`, 2 → `scatter`, 3+ → `sweep`); override with `--view`.

| Option | Default | What |
|---|---|---|
| `--metric` | `time` | which metric to plot |
| `--view compare\|scatter\|sweep\|scaling` | by run count | force a view |
| `--facet DIM` | — | small-multiple by a dim (incl. `node.*`) |
| `--x DIM` | auto | x-axis dim for `scaling` (numeric dim auto-picked) |
| `--clip FLOAT` | — | clamp the colour scale |
| `-o, --output PATH` | `.benchmarks/plots/{view}-{metric}.html` | HTML output |
| `--open / --no-open` | `--no-open` | open the browser after rendering |

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
`allocations`, `total_bytes`, `repeats`, `mode`).

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
- A `Sample` is `(id, value, dims)`; `dims` is a mapping of dim name → `str`/`int`/
  `float`.

### Plotting — `pytest_benchmem.plotting`

Every `plot_*` returns `(figure, n_ids)`:

```python
plot_scaling(snapshots, *, metric="time", x=None, color=None, facet=None, log="auto")
plot_scatter(snapshots, *, metric="time", facet=None, clip=None)
plot_compare(snapshots, *, metric="time", sort="absolute", facet=None, clip=None)
plot_sweep(snapshots,  *, metric="time", clip=None)
```

`snapshots` is a list of run JSON paths. `plot_compare`'s `sort` is `"absolute"`
(native units) or `"relative"` (percent).

### Sweeps — `pytest_benchmem.sweep`

```python
sweep(versions, run, **provision_kwargs) -> [failed_version_label]
```

See **[Cross-version sweeps](sweeps.md)** for the parameters and the `Venv` object.
