# Grouping by dims

Every plot and `compare` groups results by **dims** — the axes a result varies over. The
common case needs zero work: your `@pytest.mark.parametrize` params *are* your dims, with
**no id parsing**.

## `params` just work

`parametrize("n", [...])` gives you an `n` axis for free:

```python
# test_params.py
import pytest

@pytest.mark.parametrize("n", [10_000, 100_000])
def test_sort(benchmark, n):
    benchmark(sorted, list(range(n, 0, -1)))
```

After a run, `n` is a real, numeric axis your plots and compares group by — `benchmem plot`
picks it up as the x of a scaling curve with no extra flags:

<!-- termynal -->

```console
$ benchmem plot run.json --metric peak     # scaling: peak vs n, auto-inferred
```

Only **scalars** (`str`/`int`/`float`) become dims; a `list`/`dict`, or an object
pytest-benchmark couldn't serialize, is dropped — it's not a usable axis. When the axis you
want isn't a plain scalar param, set it yourself (below).

## Where to go next

- Use a dim to facet or scale a plot → [Compare & gate CI](compare-plot.ipynb)
- The full dim resolution order and the `node.*` keys → [Reference](reference.md)

---

## Going further

Dims come from three places, in order: your parametrize **params** (above), any scalar you
set on **`extra_info`**, and four structural **`node.*`** dims (opt-in).

### `extra_info` — when the axis isn't a plain param

Add your own axis by writing a scalar to `extra_info` — you choose the name and value. With
the drop-in flag this is `benchmark.extra_info`; with the fixture, `benchmark_memory.extra_info`:

```python
# An operation/phase axis, when you have one test function per operation.
# (params can't carry it — it lives in the function name, which dims never parse.)
def test_to_lp(benchmark):
    benchmark.extra_info["phase"] = "to_lp"   # → a dim named "phase"
    benchmark(model.to_lp, path)
```

Set it once for a whole suite with an autouse fixture instead of per test:

```python
# conftest.py — label every benchmark with its function name as "phase"
import pytest


@pytest.fixture(autouse=True)
def _phase(request, benchmark):
    benchmark.extra_info["phase"] = request.node.function.__name__
```

#### Parametrizing over a complex object

Don't rely on the object itself as a dim — it serializes to an opaque `UNSERIALIZABLE[...]`
string and gets dropped. Pass a *meaningful scalar* derived from it instead:

```python
@pytest.mark.parametrize("spec", [BenchSpec("basic", n=10), BenchSpec("dense", n=250)])
def test_solve(benchmark, spec):
    benchmark.extra_info["case"] = spec.name   # "basic" / "dense" — a clean label axis
    benchmark.extra_info["n"] = spec.n          # numeric → usable as a scaling x axis
    # no obvious field? fall back to a stable scalar: str(spec) / a short id / a hash
    benchmark(solve, spec)
```

A scalar *field* (`spec.name`, `spec.n`) makes the best axis. Reach for `str(spec)` only
when there's no better handle; it's still far better than the dropped object.

### Built-in `node.*` dims

You also get four structural dims derived from each benchmark's pytest node id and group —
no `extra_info`, no test changes:

- `node.module` — the test file (`bench/test_ops.py`)
- `node.func` — the test function (`test_to_lp`)
- `node.class` — the test class, if any
- `node.group` — pytest-benchmark's `group`, if set

These are most useful when the axis you care about *is* the test — e.g. one function per
operation. Facet a plot by it directly:

<!-- termynal -->

```console
$ benchmem plot run.json --metric peak --facet node.func
```

They're selectable but never auto-chosen: a plot only splits by a `node.*` dim when you name
it, so single-function suites and existing plots are unaffected. An `extra_info["node.func"]`
you set yourself still wins. For a cleaner label than the raw function name (`to_lp` vs
`test_to_lp`), set your own `phase` dim as above.
