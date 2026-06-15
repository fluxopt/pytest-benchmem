# Python API

For the pytest flags, the `benchmem` marker, the `benchmark_memory` fixture, the blob
schema, and the `benchmem` CLI, see the [Reference](reference.ipynb); for narrative
usage start with [Getting started](getting-started.ipynb).

`pytest_benchmem` is light to import — it re-exports only the engine and the
readers/loader. `pytest_benchmem.plotting` pulls plotly and `pytest_benchmem.sweep`
shells out to `uv`, so import those submodules directly.

## Engine — `pytest_benchmem`

::: pytest_benchmem.measure_peak

::: pytest_benchmem.measure_memory

::: pytest_benchmem.MemoryResult

::: pytest_benchmem.Measurement

## Readers & loader — `pytest_benchmem`

`from_pytest_benchmark` reads timing (seconds, from `stats`);
`memory_from_pytest_benchmark` reads memory (bytes, from `extra_info.benchmem`).
`load_samples` is the unified reader, and `load_long_df` stacks runs into the tidy frame
every plot pivots.

::: pytest_benchmem.from_pytest_benchmark

::: pytest_benchmem.memory_from_pytest_benchmark

::: pytest_benchmem.load_samples

::: pytest_benchmem.load_long_df

::: pytest_benchmem.discover_runs

::: pytest_benchmem.human_bytes

::: pytest_benchmem.Sample

## Plotting — `pytest_benchmem.plotting`

Every `plot_*` returns `(figure, n_ids)`. `snapshots` is a list of run JSON paths;
`labels` names the series per run (defaults to the file stems) — the API behind `plot`'s
`-l/--label`.

::: pytest_benchmem.plotting.plot_scaling

::: pytest_benchmem.plotting.plot_scatter

::: pytest_benchmem.plotting.plot_compare

::: pytest_benchmem.plotting.plot_sweep

## Sweeps — `pytest_benchmem.sweep`

See [Cross-version sweeps](sweeps.md) for the narrative walkthrough and the `Venv` the
`run` callback receives.

::: pytest_benchmem.sweep.sweep

::: pytest_benchmem.sweep.provision

::: pytest_benchmem.sweep.Venv
