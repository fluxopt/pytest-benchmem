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

# Metrics: peak, allocated, allocations

> ⚠️ The `.md` is the source; the `.ipynb` is generated (`jupytext --to ipynb
> docs/metrics.md`) and gitignored.

One memray pass yields more than a single number. Every measured benchmark stores
three memory metrics, and `compare` / `plot` / the readers take any of them — `peak`
is the default, but `allocated` and `allocations` often catch what `peak` hides.

| Metric | Blob key | What it is | Reach for it when |
|---|---|---|---|
| `peak` | `peak_bytes` | high-water of *live* bytes — the most allocated at once | headline footprint; "how big did it get" |
| `allocated` | `total_bytes` | sum of *every* allocation over the run | churn / temporary spikes `peak` smooths over |
| `allocations` | `allocations` | count of allocation calls | a near-deterministic, low-noise tripwire |

`peak_max` (the worst peak across `repeats`) rides alongside as `peak_max`. All three
are memray's **allocator demand** — what your code *requested*, in-process and
byte-exact, so they see native (numpy / C-extension) allocations, not just Python
objects. The blob also carries a `mode` tag (`"heap"`); the readers refuse to compare
or co-plot blobs of different modes rather than mislead.

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

## Three readings of one run

A workload that allocates a lot of *temporary* memory but holds little at its peak —
the place `peak` and `allocated` diverge most:

```{code-cell} ipython3
suite = _tmp / "test_churn.py"
suite.write_text("""
def test_churn(benchmark_memory):
    def work():
        total = 0
        for _ in range(200):
            total += sum([i * i for i in range(20_000)])
        return total
    benchmark_memory(work)
""")
run = _tmp / "churn.json"
!pytest {suite} --benchmark-only --benchmark-json={run} --benchmark-columns=min,median -q -p no:cacheprovider
```

The same run read three ways — `peak` stays small (one list lives at a time) while
`allocated` is far larger (every list summed) and `allocations` counts the calls:

```{code-cell} ipython3
from pytest_benchmem import human_bytes, load_long_df

for metric in ("peak", "allocated", "allocations"):
    df, unit = load_long_df([run], metric=metric)
    v = df["value"].iloc[0]
    shown = human_bytes(v) if unit == "B" else f"{v:.0f}"
    print(f"{metric:<12} {shown}")
```

The raw blob, for reference:

```{code-cell} ipython3
import json

json.loads(run.read_text())["benchmarks"][0]["extra_info"]["benchmem"]
```

## Picking one for a gate

For CI gating, `allocations` is often the best tripwire — it's near-deterministic, so
a change there is almost always a real change in behaviour, not measurement noise.
`peak` answers the capacity question; `allocated` catches churn regressions a peak
gate would miss. You can gate on several at once — see
[Compare & plot](compare-plot.ipynb) and the
[reference](reference.ipynb#benchmem-compare).

## Next

- **[Grouping by dims](dims.ipynb)** — the axes plots scale by.
- **[Compare & plot](compare-plot.ipynb)** — diff two runs on any of these metrics.
- **[Reference](reference.ipynb)** — every blob key and `--metric` value.
