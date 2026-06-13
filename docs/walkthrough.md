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

# pytest-benchmem — walkthrough

> ⚠️ **This `.md` is the source.** It renders as docs on GitHub *and*
> converts to a runnable notebook: `jupytext --to ipynb docs/walkthrough.md`,
> then open `walkthrough.ipynb` in JupyterLab / PyCharm / VSCode. The
> `.ipynb` is gitignored — edit the `.md`, re-convert.

pytest-benchmem is the **memory companion to pytest-benchmark**: you write ordinary
pytest-benchmark tests, swap the `benchmark` fixture for `benchmark_memory`, and
get a memray **peak-memory** number recorded right next to the timing — same
test, same run, same JSON file. This notebook runs that end to end: write a
benchmark suite, execute it, then read, compare, and plot both metrics.

The fixture and memray ship with the core install; the plots and CLI need
`pytest-benchmem[plot]`. Memory measurement is Linux/macOS only (timing works
everywhere).

## Setup

A scratch dir for the suite, the JSON runs, and the HTML plots the cells below
produce. `FORCE_COLOR` makes typer's CLI panels render in colour through the
`!`-cell pipe.

```{code-cell} ipython3
import os
import sys
import tempfile
from pathlib import Path

import plotly.io as pio

os.environ["FORCE_COLOR"] = "1"
# Make the `!pytest` / `!pytest-benchmem` cells resolve to this kernel's environment.
os.environ["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"
pio.renderers.default = "notebook_connected"  # load plotly.js from CDN — light pages
_tmp = Path(tempfile.mkdtemp(prefix="pytest-benchmem-"))
print(f"tempdir: {_tmp}")
```

## A memory benchmark — the `benchmark_memory` fixture

`benchmark_memory` depends on pytest-benchmark's `benchmark` fixture, so timing
rides pytest-benchmark exactly as usual. On top, it runs the action once more
under `memray.Tracker` — a **separate, untimed pass**, so the allocator hooks
never touch the timing — and stashes the memory blob (`extra_info.benchmem`:
peak in bytes, the spread across repeats, and the allocation count) in the
benchmark. One node id, one JSON entry, both metrics. Parametrize `params`
become the analysis `dims` for the plots, for free.

Here's a tiny suite — `sorted` over a range of input sizes:

```{code-cell} ipython3
suite = _tmp / "test_sortbench.py"
suite.write_text("""
import pytest

@pytest.mark.parametrize("n", [10_000, 50_000, 200_000, 500_000])
def test_sort(benchmark_memory, n):
    data = list(range(n, 0, -1))      # untimed: pytest-benchmark builds args per round
    benchmark_memory(sorted, data)    # times sorted(data), then memory-profiles it
""")
print(suite.read_text())
```

## Run it — one command, both metrics

A normal pytest invocation. `--benchmark-json` writes the same file
pytest-benchmark always writes; the only difference is each entry now also
carries `extra_info.benchmem`.

```{code-cell} ipython3
baseline = _tmp / "baseline.json"
!pytest {suite} --benchmark-only --benchmark-json={baseline} -q -p no:cacheprovider
```

## Read both metrics back

pytest-benchmem reads that one file *per metric*: `from_pytest_benchmark` pulls timing
(seconds, from `stats`), `memory_from_pytest_benchmark` pulls peak memory (bytes,
from `extra_info.benchmem`). Dims default to the parametrize `params`, so each sample
knows its `n` without anyone parsing the id.

```{code-cell} ipython3
from pytest_benchmem import from_pytest_benchmark, memory_from_pytest_benchmark

_, time_samples, tunit = from_pytest_benchmark(baseline)
_, mem_samples, munit = memory_from_pytest_benchmark(baseline)

print(f"timing ({tunit}):")
for s in time_samples:
    print(f"  {s.id.split('::')[-1]:<18} {s.value:.3e}  dims={dict(s.dims)}")
print(f"\nmemory ({munit}):")
for s in mem_samples:
    print(f"  {s.id.split('::')[-1]:<18} {s.value:>8.2f}  dims={dict(s.dims)}")
```

`load_long_df` stacks one or more runs into the tidy frame every plot pivots —
one row per `(run, id)` for the chosen metric, one column per dim:

```{code-cell} ipython3
from pytest_benchmem import load_long_df

df, unit = load_long_df([baseline], metric="peak")
print(f"unit: {unit}")
df
```

## Resident footprint: the `rss` mode (opt-in)

Everything above used `heap` — memray's **allocator demand** (what your code *requested*):
byte-exact, low-noise, the default, and the right metric for regression detection.

`rss` answers a different question: the workload's peak **resident set** (`ru_maxrss`),
measured by running it in a forked child — what the OS actually had to *hold*, including the
allocator/hashtable over-allocation and fragmentation `heap` can't see. It's a kernel
high-water (so it can't miss a spike), and on typical Python it differs from `heap` by
~15–40%, in both directions. Linux/macOS only.

Here's a workload that builds a `dict` **inside** the measured call — run once per mode:

```{code-cell} ipython3
idx_suite = _tmp / "test_index.py"
idx_suite.write_text("""
def test_build_index(benchmark_memory):
    benchmark_memory(lambda: {f"key-{i}": i for i in range(300_000)})
""")
heap_json, rss_json = _tmp / "idx_heap.json", _tmp / "idx_rss.json"
!pytest {idx_suite} --benchmark-only --benchmark-memory-mode=heap --benchmark-json={heap_json} -q -p no:cacheprovider
!pytest {idx_suite} --benchmark-only --benchmark-memory-mode=rss  --benchmark-json={rss_json}  -q -p no:cacheprovider
```

Same workload, the two metrics side by side — `rss` is meaningfully higher: the dict's
allocated bytes (`heap`) vs the pages it actually occupies (`rss` net, after subtracting a
forked no-op baseline; the gross/capacity figure is kept alongside):

```{code-cell} ipython3
import json

from pytest_benchmem import human_bytes

hb = json.loads(heap_json.read_text())["benchmarks"][0]["extra_info"]["benchmem"]
rb = json.loads(rss_json.read_text())["benchmarks"][0]["extra_info"]["benchmem"]
print(f"heap (allocated):    {human_bytes(hb['peak_bytes'])}")
print(f"rss net (resident):  {human_bytes(rb['peak_bytes'])}   gross {human_bytes(rb['gross_bytes'])}")
print(f"rss/heap = {rb['peak_bytes'] / hb['peak_bytes']:.2f}x  — allocator overhead heap can't see")
```

### The one gotcha: build inputs *inside* the call

Because `rss` runs in a forked child, it charges the workload for memory it merely **reads** —
in CPython, reading an object bumps its refcount, which dirties (so makes resident) the page it
lives on. A call that reads a big input built *beforehand* therefore attributes that input to
the workload, even though it allocated nothing:

```{code-cell} ipython3
from pytest_benchmem import measure_memory

big = list(range(2_000_000))   # built out here — the forked child "inherits" it
heap = measure_memory(lambda: sum(big), mode="heap").peak_bytes
rss = measure_memory(lambda: sum(big), mode="rss").peak_bytes
print(f"sum(inherited list)   heap={human_bytes(heap)} (allocates ~nothing)   "
      f"rss net={human_bytes(rss)} (charged for reading it!)")
```

So build the workload's inputs inside the measured call (as the dict example does), or use the
fixture's `pedantic` form with a `setup` that constructs them fresh each round. `heap` doesn't
have this problem — it counts allocations, not touches.

Finally, `heap` and `rss` are different quantities wearing the same byte unit, so the readers
**refuse to compare or co-plot across modes** rather than mislead:

```{code-cell} ipython3
from pytest_benchmem import load_long_df

try:
    load_long_df([heap_json, rss_json], metric="peak")
except ValueError as exc:
    print(f"refused: {exc}")
```

## Quick one-off — `measure_peak`

Outside pytest — in a REPL or notebook — `measure_peak` is the bare engine: hand
it a zero-arg callable, get the peak in bytes. (`repeats > 1` takes the min, since
peak memory is noisy; `measure_memory` returns the full result — peak, spread,
allocation count.)

```{code-cell} ipython3
from pytest_benchmem import measure_peak

measure_peak(lambda: [0] * 5_000_000)
```

## A second run to diff

On a real change you'd run the suite on `main`, then on your branch. Here we just
run it twice — same code, so the deltas below are measurement noise; on a real
change they'd move.

```{code-cell} ipython3
candidate = _tmp / "candidate.json"
!pytest {suite} --benchmark-only --benchmark-json={candidate} -q -p no:cacheprovider
```

## CLI — `benchmem compare`

A per-id delta table with percent change, for whichever `--metric` you ask for.
Ids in only one run show `—`.

```{code-cell} ipython3
!benchmem compare {baseline} {candidate} --metric peak
```

```{code-cell} ipython3
!benchmem compare {baseline} {candidate} --metric time
```

> For *timing* comparisons you can also use pytest-benchmark's own tooling
> directly — `pytest-benchmark compare`, `--benchmark-histogram`. pytest-benchmem
> doesn't reimplement those; it adds the memory-aware, dims-aware views.

## CLI — `benchmem plot`

`benchmem plot` writes an interactive plotly view to standalone HTML, picking a
view by run count (1 → `scaling`, 2 → `scatter`, 3+ → `sweep`) and the metric you
pass:

```{code-cell} ipython3
!benchmem plot --metric peak {baseline} {candidate} -o {_tmp / "scatter.html"}
```

Every view is a `plot_*` function over the same `load_long_df` seam — call them
directly to render the *same figures* inline, no HTML round-trip. Each takes a
`metric` and returns `(figure, n_ids)`.

**Scatter** — x = baseline cost (log), y = candidate/baseline ratio, colour =
absolute Δ. Top-right is the "big and got bigger" zone. Here on memory:

```{code-cell} ipython3
from pytest_benchmem import plotting

plotting.plot_scatter([baseline, candidate], metric="peak")[0]
```

**Compare** — the "did anything regress, ranked by impact" bar chart, sorted by
absolute delta, diverging colour around zero. On timing this time:

```{code-cell} ipython3
plotting.plot_compare([baseline, candidate], metric="time")[0]
```

**Scaling** — a single run, cost vs. size. `plot_scaling` auto-infers the x-axis
from the numeric `n` dim, so the baseline alone draws `sorted`'s peak-memory
curve:

```{code-cell} ipython3
plotting.plot_scaling([baseline], metric="peak")[0]
```

## Cross-version sweeps — `pytest_benchmem.sweep`

To benchmark *across installed versions* of a package — something
pytest-benchmark has no answer for — `sweep` provisions one fresh `uv` venv per
version (with import isolation) and calls your `run` callback in each. The
callback just runs your pytest suite in that venv, writing a per-version JSON.
Everything package-specific is injected, so it isn't tied to any one library:

```python
import subprocess
from pytest_benchmem.sweep import sweep

failed = sweep(
    ["1.2.0", "1.3.0", "git+https://github.com/me/pkg@main"],
    run=lambda venv: subprocess.run(
        [str(venv.python), "-m", "pytest", "benchmarks/",
         "--benchmark-only", f"--benchmark-json={venv.version}.json"],
        cwd=venv.cwd, env=venv.env,
    ),
    install_spec=lambda v: f"mypkg=={v}",
    copy_dir="benchmarks",   # copied in so it imports from here, pkg from the venv
    import_check="mypkg",    # preflight: assert pkg resolved to the venv
)
```

Point `benchmem plot` at the per-version JSONs — with 3+ it defaults to the
`sweep` view, a log₂ fold-change heatmap — and pick `--metric time` or
`--metric peak` for either picture across versions.
