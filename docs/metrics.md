# Choosing a metric

One memray pass yields three numbers, not one. `peak` is the default and the headline, but
`allocated` and `allocations` often catch what `peak` hides. Pick by the question you're asking:

| Metric | What it is | Reach for it when |
|---|---|---|
| `peak` | high-water of *live* bytes — the most held at once | headline footprint; "how big did it get?" |
| `allocated` | sum of *every* allocation over the run | churn / temporary spikes `peak` smooths over |
| `allocations` | count of allocation calls | a near-deterministic, low-noise CI tripwire |

All three are memray's allocator demand — what your code *requested*, in-process and
byte-exact, so they see native (numpy / C-extension) allocations, not just Python objects.

## Three readings of one run

Take a workload that allocates a lot of *temporary* memory but holds little at its peak —
the place `peak` and `allocated` diverge most:

```python
# test_churn.py
def test_churn(benchmark):
    def work():
        total = 0
        for _ in range(200):
            total += sum([i * i for i in range(20_000)])
        return total
    benchmark(work)
```

Show all three in the table at once with `--benchmark-memory-columns`:

```bash
pytest test_churn.py --benchmark-only --benchmark-memory \
       --benchmark-memory-columns=peak,allocated,allocs
```

```
 Name (time in ms)        Min      │  peak (MiB)   allocated (MiB)   allocs
 ─────────────────────────────────────────────────────────────────────────
  test_churn          73.9735      │        1.16            294.07    9,001

 memory (right of │): a separate, untimed pass, not the timed rounds
```

`peak` stays small (one list lives at a time) while `allocated` is far larger (every list
summed) and `allocs` counts the calls. A peak gate would wave this churn through;
`allocated` catches it.

## Where to go next

- See these metrics in a delta table or plot, and gate CI on them → [Compare & gate CI](compare-plot.ipynb)
- Every flag and the blob schema → [Reference](reference.md)

---

## Going further

!!! tip "Picking one for a CI gate"
    `allocations` is often the best tripwire — it's near-deterministic, so a change there is
    almost always real behaviour, not measurement noise. `peak` answers the capacity
    question; `allocated` catches churn regressions a peak gate would miss. You can gate on
    several at once — see [Compare & gate CI](compare-plot.ipynb).

### Distribution across repeats

With `--benchmark-memory-repeats=N` (suite-wide) or `@pytest.mark.benchmem(repeats=N)`
(per test), every repeat is kept as a flat series in the blob. The headline `peak` is the
*minimum* (the cleanest floor); ask for any other stat over the series with `--stat`:

```bash
benchmem compare base.json head.json --metric peak --stat stddev   # how noisy is peak?
benchmem compare v1.json v2.json --metric allocated --stat mean
```

`--stat` takes `min` / `max` / `mean` / `median` / `stddev` and applies to any metric.
Peak is the noisy one (GC timing, page cache); `stddev` tells you how much.

The terminal table shows the spread too: with `repeats > 1`, every shown metric expands into
`min` / `mean` / `max` columns (`peak·min`, `peak·mean`, `peak·max`) — always, so the columns
don't shift between runs; a single pass stays one column. The table shows peak only by
default; add the rest with `--benchmark-memory-columns=peak,allocated,allocs` and pick the
spread stats with `--benchmark-memory-stats=min,stddev`.

### The raw blob

Each measured benchmark stores all three as flat per-repeat series under
`extra_info["benchmem"]` — one entry per memray pass. Every reported number derives from these:

```json
{"peak_bytes": [1221536], "allocations": [9001], "total_bytes": [308357376]}
```
