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

# The same benchmarks CodSpeed runs, measured locally

[linopy](https://github.com/PyPSA/linopy) benchmarks its model construction with
`pytest-benchmark` and runs that suite on [CodSpeed](https://codspeed.io) — which, since
its 2026 memory instrument, tracks memory as well as time. `pytest-benchmem` reuses those
exact tests: the `benchmark(...)` call is all it reads. No second suite, no new markers —
point it at the benchmarks you already have and get a memray memory profile **locally, on
demand**, without a CI round-trip or an account. It was extracted from linopy's suite to
be exactly that: the terminal companion for the numbers CodSpeed keeps in CI.

Here is the suite's model — linopy's "basic problem", an N×N LP — construction plus a
couple of `LinearExpression` operations, sized by `n`:

```{code-cell} ipython3
from numpy import arange

import linopy


def create_model(n: int) -> linopy.Model:
    m = linopy.Model()
    N, M = arange(n), arange(n)
    x = m.add_variables(coords=[N, M], name="x")
    y = m.add_variables(coords=[N, M], name="y")
    m.add_constraints(x - y >= N)
    m.add_constraints(x + y >= 0)
    m.add_objective(2 * x.sum() + y.sum())
    return m
```

```{code-cell} ipython3
:tags: [hide-input]

import inspect
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["FORCE_COLOR"] = "1"
os.environ["COLUMNS"] = "96"
os.environ["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"

_tmp = Path(tempfile.mkdtemp(prefix="pytest-benchmem-linopy-"))
# The pytest subprocess can't see this notebook's functions, so the suite carries
# create_model's source (straight off the cell above) plus its own test.
_defs = "from numpy import arange\nimport linopy\nimport pytest\n\n" + inspect.getsource(create_model)


def _run_suite(name: str, test_body: str, **extra) -> str:
    suite = _tmp / name
    suite.write_text(_defs + "\n\n" + test_body)
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(suite),
         "--benchmark-only", "--benchmark-memory", "-q", "-p", "no:cacheprovider", *extra.get("args", [])],
        env=os.environ, capture_output=True, text=True, check=True,
    ).stdout
```

## The same test, in your terminal

An ordinary `pytest-benchmark` test — the one already in the suite — with
`--benchmark-memory` adding the peak on the same call it already times:

```python
@pytest.mark.parametrize("n", [100, 200, 400])
def test_create_model(benchmark, n):
    benchmark(create_model, n)
```

```{code-cell} ipython3
:tags: [hide-input]

_out = _run_suite(
    "bench_linopy.py",
    '@pytest.mark.parametrize("n", [100, 200, 400])\n'
    'def test_create_model(benchmark, n):\n'
    '    benchmark(create_model, n)\n',
    args=["--benchmark-columns=mean", "--benchmark-sort=name"],
)
print(_out[_out.index("benchmark:") :])  # drop pytest's session preamble, keep the table
```

Peak next to the time, straight from the call. The peak climbs with the square of `n`
(~2 → ~35 MiB here) while the timer, mostly fixed overhead at this size, barely moves —
the kind of thing you want to catch before it becomes a model that won't build.

## The local half of the loop

CodSpeed keeps the history, the dashboards, the PR annotations. `pytest-benchmem` is the
offline companion on the *same* tests, for the tight loop where a CI round-trip is too
slow — run it, then [diff two runs](../compare-runs.md), [flamegraph where it
allocated](../profiling.md), [chart the scaling](../visualize.ipynb), or [sweep across
installed linopy versions](../sweeps.md), all in the terminal:

```bash
benchmem compare base.json head.json --columns peak          # what moved
benchmem flamegraph profiles/ --worst peak --open            # where it allocated
benchmem sweep linopy 0.7.0 0.8.0 --suite bench/             # across versions
```

One suite, measured both ways. The [Quickstart](../getting-started.md) starts from
benchmarks you already have.
