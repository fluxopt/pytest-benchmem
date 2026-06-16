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

<!-- termynal -->

```console
$ pytest test_churn.py --benchmark-only --benchmark-memory --benchmark-memory-columns=peak,allocated,allocations
 Name (time in ms)        Min      │  peak (MiB)   allocated (MiB)   allocations
 ──────────────────────────────────────────────────────────────────────────────
  test_churn          73.9735      │        1.16            294.07         9,001

 memory (right of │): a separate, untimed pass, not the timed rounds
```

`peak` stays small (one list lives at a time) while `allocated` is far larger (every list
summed) and `allocations` counts the calls. A peak gate would wave this churn through;
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

### Repeats & adaptive sampling

Each benchmark is memory-profiled more than once, and the headline `peak` is the **minimum**
across those passes — the cleanest floor. How many passes run is **adaptive** by default:
pytest-benchmem keeps measuring until that floor settles, then stops.

#### Why the minimum?

Peak memory is allocator *demand* — the bytes a code path requests for given inputs — so it has a
real, irreducible floor. What varies run-to-run is **upward**: GC timing, page cache, lazy
imports, and short-lived temporaries whose high-water mark depends on scheduling. The minimum
strips that transient inflation and recovers the floor — the least memory the operation can
complete in. It's also the most reproducible summary, which is why it's what `--fail-on` gates
and the JSON reports. The `mean` / `max` are kept too (they tell you the *worst-case headroom*),
but they wander; the `min` doesn't.

#### How it decides

The loop runs a pass, then asks whether to run another:

- **Always take at least 2.** The first pass carries one-time warmup — lazy imports, allocator
  arena growth — that the `min` discards. One pass would report exactly that contaminated number.
- **Stop when the floor settles** — once 2 consecutive passes set no new low, the min has
  converged and more passes won't lower it.
- **Never exceed 10 passes** (a hard cap), or an optional `--benchmark-memory-max-time` wall-clock
  budget, whichever comes first.

In practice: **deterministic code settles in ~3 passes**; **noisy code runs more**, up to the cap
— exactly where extra passes pay off.

!!! note "Adaptive sampling, not calibration"
    The UX echoes pytest-benchmark — you don't pick a count — but the mechanism is different, so
    it's worth being precise. pytest-benchmark *calibrates*: it runs the function many times to
    tune its measurement against the timer's coarse resolution. memray has no such problem — a
    single pass gives the **exact** peak for that run. So passes here aren't fighting measurement
    error; they're **sequential sampling** to *find the floor and measure its spread*. That's why
    the minimum is just 2, not pytest-benchmark's `min_rounds=5`. A fixed count would be
    simultaneously too many for deterministic code (every pass identical → wasted runtime) and too
    few for noisy code (a rare floor needs many tries to catch) — hence: adapt.

#### Forcing a fixed count

For **reproducible** numbers — CI gating against a saved baseline, where the pass count must not
vary run-to-run — pin it:

```bash
pytest --benchmark-memory --benchmark-memory-repeats=5     # suite-wide, exactly 5 passes
```

```python
@pytest.mark.benchmem(repeats=5)        # per test; overrides the suite-wide flag
def test_build(benchmark_memory):
    ...
```

An explicit count runs *exactly* that many passes — no adaptation, no cap, no time budget.

#### Bounding cost

Adaptive sampling runs the action up to 10 times, so its cost is up to 10× the action's runtime.
For a benchmark that's both **slow and noisy** (so it never settles and keeps hitting the cap),
cap the wall-clock instead:

```bash
pytest --benchmark-memory --benchmark-memory-max-time=3    # ≤3 s of adaptive sampling per benchmark
```

!!! tip "Noisy peak? Remove the noise, don't average it"
    A wide `peak·min`…`peak·max` spread usually means the workload allocates many short-lived
    temporaries whose high-water mark depends on timing — classic with **multithreaded
    allocators** (e.g. a library that builds output through `polars`, whose worker pool holds a
    varying number of buffers at once). Pinning the source of non-determinism
    (`POLARS_MAX_THREADS=1`) collapses the spread far more effectively, and more honestly, than
    piling on repeats. Extra passes only sharpen the `min`; they can't make a genuinely bursty
    workload reproducible.

#### Reading the distribution

Every pass is kept as a flat series in the [blob](#the-raw-blob), so any stat is available after
the fact. Ask for one over the series with `--stat`:

```bash
benchmem compare base.json head.json --metric peak --stat stddev   # how noisy is peak?
benchmem compare v1.json v2.json --metric allocated --stat mean
```

`--stat` takes `min` / `max` / `mean` / `median` / `stddev` and applies to any metric. Peak is
the noisy one (GC timing, page cache); `stddev` tells you how much.

The terminal table shows the spread too: when a benchmark ran more than once, every shown metric
expands into `min` / `mean` / `max` columns (`peak·min`, `peak·mean`, `peak·max`) — always, so the
columns don't shift between runs; a single (forced) pass stays one column. The table shows peak
only by default; add the rest with `--benchmark-memory-columns=peak,allocated,allocations` and
pick the spread stats with `--benchmark-memory-stats=min,stddev`.

Scaling plots show the spread too: `benchmem plot --view scaling` draws each point at the
headline (the min floor) with `min`…`max` whiskers up to the worst pass, so a noisy series is
visible at a glance. It's on where there's spread; `--band minmax` forces it, `--band none`
hides it.

### The raw blob

Each measured benchmark stores all three as flat per-repeat series under
`extra_info["benchmem"]` — one entry per memray pass. Every reported number derives from these:

```json
{"peak_bytes": [1221536], "allocations": [9001], "total_bytes": [308357376]}
```
