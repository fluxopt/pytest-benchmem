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

# A netCDF memory spike, found and fixed

A worked story from the PyPSA ecosystem — [issue #1555][issue], fixed in
[PR #1830][pr]. Reading a network that carried **shape geometries** back from
netCDF made memory spike ~10×, big enough to OOM-kill loads that used to fit.
The timings barely moved; the peak is what gave it away.

Everything on this page **runs live** when the docs build. Here is the whole
example — a length-skewed set of WKT polygons (many tiny regions, a few detailed
coastlines) read two ways. Both return the same strings; only the dtype differs:

```{code-cell} ipython3
import numpy as np


def make_wkt_geometries(n_small: int = 500, n_detailed: int = 5, n_points: int = 6_000) -> list[str]:
    """A length-skewed set of WKT polygons: many tiny regions and a few detailed
    ones — the distribution that makes fixed-width padding pathological (the PR's
    own repro uses 200k points / ~6 GB; here it's dialled down to stay laptop-sized)."""
    tiny = ["POLYGON ((0 0, 1 0, 1 1, 0 0))"] * n_small
    detailed = ["POLYGON ((" + "0 0," * n_points + "0 0))"] * n_detailed
    return tiny + detailed


def to_fixed_width_array(geometries: list[str]) -> np.ndarray:
    """Before #1830: a fixed-width Unicode array. NumPy sizes the dtype to the
    longest string and pads every entry to it — n × 4 × len(longest) bytes."""
    return np.array(geometries, dtype="U")


def to_object_array(geometries: list[str]) -> np.ndarray:
    """After #1830: an object array. Each entry stays its own variable-length
    string, so the array costs the sum of the actual lengths."""
    return np.array(geometries, dtype=object)
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

_tmp = Path(tempfile.mkdtemp(prefix="pytest-benchmem-shapes-"))
_bench = ["--benchmark-only", "--benchmark-memory", "-q", "-p", "no:cacheprovider"]
# The pytest subprocesses can't see functions defined in this notebook, so each
# suite carries their source (straight off the cells above) plus its own test.
_defs = "import numpy as np\nimport pytest\n\n" + "\n\n".join(
    inspect.getsource(f) for f in (make_wkt_geometries, to_fixed_width_array, to_object_array)
)


def _run_suite(name: str, test_body: str, **env) -> str:
    suite = _tmp / name
    suite.write_text(_defs + "\n\n" + test_body)
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(suite), *_bench, *env.pop("_extra", [])],
        env={**os.environ, **env}, capture_output=True, text=True, check=True,
    ).stdout
```

## Discovery — the peak flags the culprit

Point a benchmark at both readers and add `--benchmark-memory`. It's an ordinary
`pytest-benchmark` test — the only new thing is the flag:

```python
READERS = {"fixed-width (before #1830)": to_fixed_width_array, "object (after #1830)": to_object_array}

@pytest.mark.parametrize("reader", READERS, ids=list(READERS))
def test_read_shapes(benchmark, reader):
    benchmark(READERS[reader], make_wkt_geometries())
```

The timing table is business as usual; the `peak` columns, right of the divider,
are not:

```{code-cell} ipython3
:tags: [hide-input]

_out = _run_suite(
    "bench_shapes.py",
    'READERS = {"fixed-width (before #1830)": to_fixed_width_array, "object (after #1830)": to_object_array}\n'
    '\n'
    '@pytest.mark.parametrize("reader", READERS, ids=list(READERS))\n'
    'def test_read_shapes(benchmark, reader):\n'
    '    benchmark(READERS[reader], make_wkt_geometries())\n',
    _extra=["--benchmark-columns=mean"],
)
print(_out[_out.index("benchmark:") :])  # drop pytest's session preamble, keep the table
```

Same 505 strings in, same strings out — and a **46 MiB peak against 4 KiB**. In the
real network that ratio was the difference between loading and dying. A timing-only
suite would have shrugged: the mean is slower, but "slower" isn't the symptom users
hit — the OOM is, and only the `peak` column names it.

## Examination — why the array is 300× its payload

The peak says *which* reader is heavy; look at *what* it built to see why. Nothing
memray-specific here — just the array's own dtype:

```{code-cell} ipython3
geometries = make_wkt_geometries()
arr = to_fixed_width_array(geometries)

print("dtype           :", arr.dtype)                          # sized to the longest string
print("array           :", round(arr.nbytes / 1e6, 1), "MB")
print("actual payload  :", round(sum(len(g) for g in geometries) / 1e6, 2), "MB")
```

There it is. A fixed-width Unicode array sizes its dtype to the **longest** string —
here one 24,015-character coastline — and pads *every* entry to it, at 4 bytes per
character (UTF-32). So 505 strings whose real payload is 0.14 MB inflate to
`505 × 4 × 24015 ≈ 48.5 MB`. The tiny rectangles are each paying the coastline's
weight. On the full network, with a 200k-point shape, that same padding is gigabytes.

## Fix — object array, confirmed with `compare`

[PR #1830][pr]'s fix is one dtype: keep the strings as variable-length Python objects,
so the array costs the sum of the real lengths, not the longest repeated. Run the
reader before and after into two JSON files and diff them:

```bash
benchmem compare before.json after.json --columns peak --diff
```

```{code-cell} ipython3
:tags: [hide-input]

_test = (
    "import os\n"
    "READER = {'padded': to_fixed_width_array, 'object': to_object_array}[os.environ['SHAPE_READER']]\n"
    "def test_read_shapes(benchmark):\n"
    "    benchmark(READER, make_wkt_geometries())\n"
)
before, after = _tmp / "before.json", _tmp / "after.json"
# Same suite file for both runs, so the benchmark node id matches and compare aligns them.
_run_suite("bench_read.py", _test, SHAPE_READER="padded", _extra=[f"--benchmark-json={before}"])
_run_suite("bench_read.py", _test, SHAPE_READER="object", _extra=[f"--benchmark-json={after}"])
print(subprocess.run(
    ["benchmem", "compare", str(before), str(after), "--columns", "peak", "--diff"],
    env=os.environ, capture_output=True, text=True, check=True,
).stdout)
```

The peak is gone. Wire that same diff into CI with `--fail-on peak:20%`
([Catch regressions in CI](../catch-regressions.md)) and the spike can't come back
unnoticed — the next PR that reintroduces fixed-width padding turns the build red
instead of shipping an OOM.

## The loop, on your own code

Nothing here is shape-specific. Any allocation whose *size* dwarfs its *payload* —
a padded array, a densified sparse matrix, a duplicated frame, a solver's working
set — shows up the same way: a peak that timing can't see, a heavy line you can
point at, and a `compare` that proves the fix. Start at the
[Quickstart](../getting-started.md) with a benchmark you already have.

[issue]: https://github.com/PyPSA/PyPSA/issues/1555
[pr]: https://github.com/PyPSA/PyPSA/pull/1830
