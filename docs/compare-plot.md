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

# Compare & gate CI

Two (or more) saved runs in, one comparison out — a table (`benchmem compare`) or an
interactive view (`benchmem plot`). The table shows `time` and `peak` across every stat by
default (pick metrics with `--columns`, a stat with `--stat`); the plot takes one
(`--columns`). Both group by the [dims](dims.md) your tests carry.

## A regression to catch

A benchmark builds a table of `(i, i²)` rows. On `main`, each row is a lightweight tuple:

```python
@pytest.mark.parametrize("n", [10_000, 50_000, 200_000, 500_000])
def test_build_rows(benchmark, n):
    benchmark(lambda: [(i, i * i) for i in range(n)])
```

A branch switches the rows to dicts for readability — a classic memory regression, since a
dict is several times heavier than a 2-tuple:

```python
@pytest.mark.parametrize("n", [10_000, 50_000, 200_000, 500_000])
def test_build_rows(benchmark, n):
    benchmark(lambda: [{"x": i, "sq": i * i} for i in range(n)])
```

Run each on its branch and save the `--benchmark-json` — here, `baseline.json` (main) and
`candidate.json` (the branch).

```{code-cell} ipython3
:tags: [hide-input]

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import plotly.io as pio

os.environ["FORCE_COLOR"] = "1"
os.environ["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"
pio.renderers.default = "notebook_connected"
_tmp = Path(tempfile.mkdtemp(prefix="pytest-benchmem-"))

suite = _tmp / "test_rows.py"
baseline, candidate = _tmp / "baseline.json", _tmp / "candidate.json"
_args = ["--benchmark-only", "--benchmark-memory", "--benchmark-columns=min",
         "-q", "-p", "no:cacheprovider"]
_suite = """
import pytest

@pytest.mark.parametrize("n", [10_000, 50_000, 200_000, 500_000])
def test_build_rows(benchmark, n):
    benchmark(lambda: %s)
"""
for _out, _row in [(baseline, "[(i, i * i) for i in range(n)]"),
                   (candidate, '[{"x": i, "sq": i * i} for i in range(n)]')]:
    suite.write_text(_suite % _row)
    subprocess.run([sys.executable, "-m", "pytest", str(suite), *_args,
                    f"--benchmark-json={_out}"], check=True, capture_output=True)
```

## `benchmem compare` — the comparison table

Modelled on pytest-benchmark's own table: one row per `(benchmark × run)`, columns are
`metric × stat`, and each cell carries a relative `(N.NN)` multiplier vs the column's best
run (best green, worst red). Rows are grouped into sub-tables by `--group-by` (default
`fullname`, so each benchmark's runs sit together and the multiplier reads as the cross-run
ratio). By default it shows `time` and `peak`, each across the full stat spread
(min/max/mean/median/stddev) — so no single statistic is privileged:

```{code-cell} ipython3
!benchmem compare {baseline} {candidate}
```

Pick the metrics with `--columns` (a comma list of `time` / `peak` / `allocated` /
`allocations`; a metric absent from every run is dropped) and the stat with `--stat`
(`min` / `max` / `mean` / `median` / `stddev`, or `all`):

```{code-cell} ipython3
!benchmem compare {baseline} {candidate} --columns peak --stat min
```

`--group-by` follows pytest-benchmark's grammar (`fullname` | `name` | `func` | `group` |
`module` | `class` | `param:NAME`, comma-composable); pass it to cluster param-variants
(`--group-by func`) or collapse everything into one table.

## One run, two configs — `--pivot`

Everything above compares **run-files**: `compare a.json b.json` lays one file against
another. But the file is just the *series axis* — the thing whose values sit side by side and
get the `(N.NN)` multiplier. **The series axis is a [dim](dims.md)**, and the run-file is only
the default one.

`--pivot DIM` re-points it at a data dim, so a **single combined run** is A/B'd along that dim —
the role a file-pair plays today, without splitting into N runs. Say `semantics` is a param
(so it's in the node id, `test_build[legacy-100]`, *and* a dim):

```python
@pytest.mark.parametrize("semantics", ["legacy", "v1"])
@pytest.mark.parametrize("n", [100, 200])
def test_build(benchmark, semantics, n):
    benchmark(build, semantics=semantics, n=n)
```

One `pytest` invocation produces one `build.json`; `--pivot param:semantics` folds it so rows
that differ *only* in `semantics` pair up (`legacy` ↔ `v1`) per `n`:

```bash
pytest benchmarks/ --benchmark-only --benchmark-memory --benchmark-json=build.json
benchmem compare build.json --pivot param:semantics --columns time,peak   # the A/B table
benchmem plot    build.json --pivot param:semantics --columns peak --view compare   # the A/B bars
benchmem plot    build.json --x n --facet semantics --columns peak     # --pivot optional here
```

Don't confuse it with `--group-by`, which touches the *other* axis: `--group-by` **partitions
rows** into sub-tables along a dim while the compared series stays the run-files (`legacy` and
`v1` would sit in separate sections, never set against each other); `--pivot` makes the dim
*itself* the compared series, folding rows that differ only in it into one ranked A/B row. They
compose on orthogonal axes — `--pivot param:semantics --group-by node.func` folds `legacy` ↔ `v1`
*and* clusters the folded rows into per-function sub-tables. In short: `--group-by` says which
rows belong together; `--pivot` says what you're comparing.

`--pivot` accepts the same dims as `--group-by`/`--facet` — `param:NAME` or a bare `extra_info`
name — and composes with `--columns`, `--stat`, `--facet`, `--where`, and `--sort` unchanged.
It's mutually exclusive with multiple runs (an A/B view has *one* series axis: comparing files
*and* folding a dim would be a 2-D matrix), and only the paired views consume it — on `plot`
it applies to `--view compare`/`scatter`; for `scaling`/`sweep` the dim is a normal `--x` /
`--facet` axis instead. One combined run then drives the A/B table, the A/B plot, the scaling
plot, *and* an external per-id gate (e.g. CodSpeed, which wants the config value in the node id
of one run) — no file-splitting, no per-config reruns.

`--fail-on` follows the same axis: it normally gates the first run vs the last, but with
`--pivot` it gates the **first dim value vs the last** (e.g. `legacy` → `v1`) out of the one
run — so the combined run also gates itself in CI, no second file required:

```bash
# fail if v1's peak grew >10% over legacy, for any benchmark, from one run:
pytest benchmarks/ --benchmark-only --benchmark-memory --benchmark-json=build.json
benchmem compare build.json --pivot param:semantics --fail-on peak:10%
```

> A `--pivot` param is lifted out of the id when rows fold (`test_build[legacy-100]` → `test_build[100]`),
> matched by value. A param given a custom `pytest.param(id=…)` whose label differs from its
> value won't fold — use a plain parametrize value, or an `extra_info` dim (which isn't in the
> id at all), for the comparison axis.

## Gate CI on a regression

`--fail-on` exits non-zero past a threshold — drop it into CI after the run. Thresholds are
percent (`peak:10%`) or absolute (`peak:5MiB`), on `peak`, `allocated`, or `allocations`
(repeatable):

```bash
# on the PR branch, against a baseline saved from main:
pytest --benchmark-only --benchmark-memory --benchmark-json=pr.json
benchmem compare main.json pr.json --fail-on peak:10% --fail-on allocations:5%
```

The dict rows blow past the threshold on every size, so the offending ids print and it exits
`1` — failing the CI job:

```{code-cell} ipython3
!benchmem compare {baseline} {candidate} --columns peak --fail-on peak:10% --fail-on allocations:5%; echo "exit: $?"
```

`allocations` is usually the steadiest tripwire — see [Choosing a metric](metrics.md).

## `benchmem plot` — interactive views

`benchmem plot` writes an interactive plotly view to standalone HTML, picking the view by run
count. **Scaling** (one run) draws cost vs. input size — the baseline's peak-memory curve:

```bash
benchmem plot baseline.json --columns peak -o scaling.html
```

```{code-cell} ipython3
:tags: [hide-input]

from pytest_benchmem import plotting

plotting.plot_scaling([baseline], metric="peak")[0]
```

**Scatter** (two runs) puts baseline cost on x (log) and the candidate/baseline ratio on y,
colour = absolute Δ. The top-right corner is "big *and* got bigger" — where a regression
actually costs you:

```bash
benchmem plot baseline.json candidate.json --columns peak -o scatter.html
```

```{code-cell} ipython3
:tags: [hide-input]

plotting.plot_scatter([baseline, candidate], metric="peak")[0]
```

## Where to go next

- Which metric to gate on → [Choosing a metric](metrics.md)
- Compare across *versions* of a package → [Cross-version sweeps](sweeps.md)
- Every CLI flag and option → [Reference](reference.md)

---

## Going further

> For *timing* comparisons you can also use pytest-benchmark's own tooling directly —
> `pytest-benchmark compare`, `--benchmark-histogram`. pytest-benchmem doesn't reimplement
> those; it adds the memory-aware, dims-aware views. Add `time` to `--columns` (or use
> `--columns time` on the plot) to put both on the same footing.

### More from `compare`

Order rows with `--sort` (`name` | `value` — largest last-run first — | `change`), and write
raw numbers for another tool with `--csv out.csv`:

```bash
benchmem compare baseline.json candidate.json --columns peak --sort value --csv peak.csv
```

### Gating without separate files

The approach above keeps two JSON files. Alternatively, gate **inline** against
pytest-benchmark's own storage — save a baseline once, then fail the next run against it.
`--benchmark-memory-compare-fail` implies `--benchmark-memory-compare`:

```bash
# on main — record the baseline into .benchmarks/ storage:
pytest --benchmark-only --benchmark-memory --benchmark-save=main

# on the PR branch — fail if peak grows >10% vs that baseline:
pytest --benchmark-only --benchmark-memory --benchmark-memory-compare-fail=peak:10%
```

> Without a prior saved run, the inline gate is a no-op — it prints *"no prior run with memory
> to compare against"* and passes. Save a baseline first.

### Profile the offenders

A `peak +20%` number says *that* a benchmark regressed, not *where*. Add
`--benchmark-memory-profile DIR` to keep the memray profile (`.bin`) for each regressing id,
so you can render the allocating call paths after the fact:

```bash
pytest --benchmark-only --benchmark-memory \
       --benchmark-memory-compare-fail=peak:10% \
       --benchmark-memory-profile profiles/
# -> profiles/<id>.bin for every id over threshold; clean ids get nothing
```

The run prints a ready-to-paste command per saved profile:

```text
benchmem: saved 1 memory profile(s) to profiles/ — render with:
    memray flamegraph profiles/test_solve.bin
```

The `.bin` is memray's raw capture, so the same file also feeds `memray tree` / `summary` /
`stats` — pick the lens you want. Off by default (retaining `.bin`s costs disk), and in CI
it's the natural artifact to upload and render locally on the PR.

#### One-step render — `benchmem flamegraph`

Instead of finding the right `.bin` and remembering the memray subcommand, point `benchmem
flamegraph` at the profile dir and name the test (an exact id or a unique substring):

```bash
benchmem flamegraph profiles/ test_solve          # → profiles/test_solve.flamegraph.html
benchmem flamegraph profiles/ --worst peak --open # auto-pick the heaviest, open it
benchmem flamegraph profiles/ test_solve --report tree   # terminal lens instead of HTML
```

`--worst peak|allocated|allocations` reads the metric straight from each `.bin` and renders the
heaviest, so you don't have to look up the id. `--report` passes through to any memray reporter
(`flamegraph` default, plus `table` / `tree` / `summary` / `stats`); HTML reports land next to
the `.bin` (override with `-o`, overwrite with `-f`). `--native` asserts the profile actually
carries native traces (see below) and errors with the fix if it doesn't.

#### Native-backed workloads: attribute the C/Rust memory

By default the capture records **Python** frames only. For a native-backed workload
(polars/Rust, numpy/C, solver bindings) the bulk of peak memory is allocated *inside* the
extension, so the flamegraph collapses it into one unresolved `??? at ???` bucket — exactly
the part you wanted to localize. Add `--benchmark-memory-profile-native` to also capture native
stacks:

```bash
pytest --benchmark-only --benchmark-memory \
       --benchmark-memory-profile profiles/ \
       --benchmark-memory-profile-native
```

Now the flamegraph attributes memory to the real frames (e.g. jemalloc `_rjem_je_*` under
`rayon` workers, reached via the polars write path) instead of an opaque native bucket. It's
**opt-in** — native traces cost runtime and produce bigger `.bin`s — and only applies on the
`--benchmark-memory-profile` path (without a kept profile there's nothing to enrich, so the
flag errors rather than silently doing nothing). Scope it to one test with
`@pytest.mark.benchmem(profile_native=True)` instead of the suite-wide flag.

!!! note "Symbols sharpen native frames"
    Native traces resolve against interpreter/library symbols. On a stripped build memray warns
    `No symbol information was found for the Python interpreter`; frames then show as mangled
    Rust/`<unknown>` but stay attributable by symbol name (`_rjem_je_*`, `rayon_*`). A
    debug-symbol interpreter sharpens the picture.

**Which benchmarks get a profile** follows the gate:

- **with** `--benchmark-memory-compare-fail` → only the **regressing** ids (keep the failing
  run cheap and the output small);
- **without** a fail-gate → **every measured benchmark** — drop the gate and keep
  `--benchmark-memory-profile DIR` alone to archive them all, regressing or not.

A minimal GitHub Actions job using the two-file approach, caching the baseline across runs:

```yaml
- uses: actions/cache@v4
  with:
    path: main.json
    key: benchmem-baseline-${{ github.base_ref }}
- run: pytest --benchmark-only --benchmark-memory --benchmark-json=pr.json
- run: benchmem compare main.json pr.json --fail-on peak:10% --fail-on allocations:5%
```

### The other two views

`plot` auto-selects by run count; override with `--view`:

| Runs | Default view | Answers |
|---|---|---|
| 1 | `scaling` | how does cost grow with input size? |
| 2 | `scatter` | which ids moved, and were they already big? |
| 2 | `compare` (`--view compare`) | ranked — what moved *most*, in native units? |
| 3+ | `sweep` | fold-change across versions, one cell per (id, run) |

`--pivot` re-points the series axis of the paired views (`compare`/`scatter`) from the run-file
onto a dim, folding a single run along it (see [One run, two configs](#one-run-two-configs-pivot)).
`--facet` splits any view into small multiples by a [dim](dims.md) (including `node.*`),
`--where` keeps only rows matching a `dim=value` filter (repeatable, AND-combined),
`--free-axes` unmatches a faceted axis from the shared default, and `--label`/`-l` names
the series per run (defaulting to the file stems):

```bash
benchmem plot run.json --columns peak --facet node.func             # one panel per operation
benchmem plot run.json --facet node.func --free-axes y             # ...each on its own cost scale
benchmem plot run.json --where axis=n                              # one sweep at a time
benchmem plot v1.json v2.json v3.json -l 0.6 -l 0.7 -l 0.8         # name series, not file stems
```

Faceted panels **share axes by default** — right when they're commensurable (the same `n`
grid across functions). Two cases want them unmatched, and they free *different* axes:

- **Different cost scales** — `--facet node.func` where one function is far costlier flattens
  the cheap panels on a shared y. `--free-axes y` gives each its own cost range.
- **Incommensurable sweeps** — a run mixing sizes `n` (10–10⁴) and a 0–100 `severity` under one
  numeric dim squishes both onto one x. `--free-axes x` (or filter to one with `--where axis=n`).

`--free-axes both` frees each panel entirely. `--where` is the cleaner reach when you only
care about one slice — it drops the rest rather than just rescaling.
