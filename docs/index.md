# benchkit

A small, generic toolkit for **time and precise peak-memory** benchmarking,
built around one primitive — the `Case`.

Its reason to exist is the gap nothing else fills cleanly: **memray-precision
memory benchmarking** of your own code. pytest-benchmark times but can't measure
memory; ASV's `peakmem` is coarse RSS sampling; CodSpeed covers CI. benchkit is
the thin memray layer plus `Case` glue, with cross-version sweeps and plotly
views bundled in.

## Install

```bash
uv add benchkit              # core (stdlib only)
uv add "benchkit[all]"       # + memray, plotly/pandas/numpy, typer CLI
```

## The primitive

Everything consumes one thing — a `Case`: an `id`, structured `dims`, and a
context manager that does untimed setup, yields the measured action, and tears
down.

```python
from contextlib import contextmanager
from benchkit import Case, measure

@contextmanager
def to_lp_case(model, n):
    m = model.build(n)                       # setup — not measured
    yield lambda: m.to_file("/tmp/m.lp")     # the measured action

cases = [
    Case(id=f"to_lp[n={n}]", dims={"op": "to_lp", "n": n}, run=lambda n=n: to_lp_case(model, n))
    for n in (10, 100, 1000)
]

samples = measure(cases)      # list[Sample(id, value, dims)], peak MiB via memray
```

## Next

→ The **[Walkthrough](walkthrough.ipynb)** runs the library and its CLI
end-to-end: measure memory, time ad-hoc callables, write snapshots, then
`compare` / `plot` them.

See the [README on GitHub](https://github.com/fluxopt/benchkit) for where
benchkit sits relative to CodSpeed / ASV / pytest-benchmark.
