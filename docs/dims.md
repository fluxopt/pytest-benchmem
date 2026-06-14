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

# Grouping by dims

> ⚠️ The `.md` is the source; the `.ipynb` is generated (`jupytext --to ipynb
> docs/dims.md`) and gitignored.

Every plot and `compare` groups results by **dims** — the axes a result varies over.
Dims come from three places, with **no id parsing**:

- your `@pytest.mark.parametrize` **`params`**,
- any scalar you put in **`benchmark_memory.extra_info`**, and
- four structural **`node.*`** dims derived from the pytest node id (opt-in).

## Setup

```{code-cell} ipython3
import os
import sys
import tempfile
from pathlib import Path

os.environ["FORCE_COLOR"] = "1"
os.environ["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"
_tmp = Path(tempfile.mkdtemp(prefix="pytest-benchmem-"))
```

## `params` — free, for the common case

`parametrize("n", [...])` gives you an `n` axis with zero extra work. Only
**scalars** (`str`/`int`/`float`) become dims; a `list`/`dict`, or an object
pytest-benchmark couldn't serialize, is dropped — it's not a usable axis.

```{code-cell} ipython3
suite = _tmp / "test_params.py"
suite.write_text("""
import pytest

@pytest.mark.parametrize("n", [10_000, 100_000])
def test_sort(benchmark_memory, n):
    benchmark_memory(sorted, list(range(n, 0, -1)))
""")
run = _tmp / "params.json"
!pytest {suite} --benchmark-only --benchmark-json={run} --benchmark-columns=min,median -q -p no:cacheprovider
```

```{code-cell} ipython3
from pytest_benchmem import load_long_df

df, _ = load_long_df([run], metric="peak")
df[["id", "value", "n"]]
```

The `n` column is a real, numeric axis — a scaling plot can use it as its x.

## `extra_info` — when the axis isn't a plain param

When the thing you want to group by *isn't* a scalar param, add it yourself via
`extra_info` — you choose the name and the value:

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

> Using the plain `benchmark` fixture (or `--benchmark-memory`)? Same recipe — write
> to `benchmark.extra_info` exactly as above.

### Parametrizing over a complex object

Don't rely on the object itself as a dim — it serializes to an opaque
`UNSERIALIZABLE[...]` string and gets dropped. Pass a *meaningful scalar* derived
from it instead:

```python
@pytest.mark.parametrize("spec", [BenchSpec("basic", n=10), BenchSpec("dense", n=250)])
def test_solve(benchmark_memory, spec):
    benchmark_memory.extra_info["case"] = spec.name   # "basic" / "dense" — a clean label axis
    benchmark_memory.extra_info["n"] = spec.n          # numeric → usable as a scaling x axis
    # no obvious field? fall back to a stable scalar: str(spec) / a short id / a hash
    benchmark_memory(solve, spec)
```

A scalar *field* (`spec.name`, `spec.n`) makes the best axis — readable label, and a
numeric one can be the x of a scaling plot. Reach for `str(spec)` only when there's
no better handle; it's still far better than the dropped object.

## Built-in `node.*` dims

You also get four structural dims for free, derived from each benchmark's pytest node
id and group — no `extra_info`, no test changes:

- `node.module` — the test file (`bench/test_ops.py`)
- `node.func` — the test function (`test_to_lp`)
- `node.class` — the test class, if any
- `node.group` — pytest-benchmark's `group`, if set

These are most useful when the axis you care about *is* the test — e.g. one function
per operation. Facet a plot by it directly:

```bash
benchmem plot run.json --metric peak --facet node.func
```

They're **selectable but never auto-chosen**: a plot only splits by a `node.*` dim
when you name it, so single-function suites and existing plots are unaffected. The
`node.` namespace can't collide with your `params`/`extra_info`, and an
`extra_info["node.func"]` you set yourself still wins. For a cleaner label than the
raw function name (`to_lp` vs `test_to_lp`), set your own `phase` dim as above.

## Next

- **[Compare & plot](compare-plot.ipynb)** — these dims become the plot axes.
- **[Reference](reference.ipynb)** — the readers and `load_long_df` in full.
