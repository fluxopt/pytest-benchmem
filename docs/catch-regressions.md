# Catch regressions in CI

You already fail a PR when it gets slower. This does the same for **memory**: run the suite with
`--benchmark-memory`, then fail the job when a benchmark's footprint grows past a threshold.

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

Run each on its branch and save the `--benchmark-json` — here `baseline.json` (main) and
`pr.json` (the branch).

## The gate — `--fail-on`

`benchmem compare --fail-on` exits non-zero past a threshold — drop it into CI after the run.
Thresholds are percent (`peak:10%`) or absolute (`peak:5MiB`), on `peak`, `allocated`, or
`allocations`, and it's repeatable:

```bash
# on the PR branch, against a baseline saved from main:
pytest --benchmark-only --benchmark-memory --benchmark-json=pr.json
benchmem compare baseline.json pr.json --fail-on peak:10% --fail-on allocations:5%
```

The dict rows blow past the threshold on every size, so the offending ids print and it exits `1`
— failing the CI job:

```text
8 regression(s) over threshold:
  peak         test_build_rows[10000]: 83.1 KiB → 2.08 MiB (+2463.8%)
  peak         test_build_rows[200000]: 22.5 MiB → 46.5 MiB (+106.4%)
  peak         test_build_rows[500000]: 61 MiB → 120 MiB (+96.8%)
  peak         test_build_rows[50000]: 4.42 MiB → 10.4 MiB (+135.6%)
  allocations  test_build_rows[10000]: 39 → 41 (+5.1%)
  allocations  test_build_rows[200000]: 85 → 109 (+28.2%)
  allocations  test_build_rows[500000]: 129 → 188 (+45.7%)
  allocations  test_build_rows[50000]: 57 → 63 (+10.5%)
```

`allocations` is usually the steadiest tripwire — see [Choosing a metric](metrics.md). To see the
full before/after table (not just the failures), read [Compare two runs](compare-runs.md).

## In GitHub Actions

A minimal job using the two-file approach, caching the baseline across runs:

```yaml
- uses: actions/cache@v4
  with:
    path: main.json
    key: benchmem-baseline-${{ github.base_ref }}
- run: pytest --benchmark-only --benchmark-memory --benchmark-json=pr.json
- run: benchmem compare main.json pr.json --fail-on peak:10% --fail-on allocations:5%
```

## Gating without separate files

The approach above keeps two JSON files. Alternatively, gate **inline** against pytest-benchmark's
own storage — save a baseline once, then fail the next run against it.
`--benchmark-memory-compare-fail` implies `--benchmark-memory-compare`:

```bash
# on main — record the baseline into .benchmarks/ storage:
pytest --benchmark-only --benchmark-memory --benchmark-save=main

# on the PR branch — fail if peak grows >10% vs that baseline:
pytest --benchmark-only --benchmark-memory --benchmark-memory-compare-fail=peak:10%
```

> Without a prior saved run, the inline gate is a no-op — it prints *"no prior run with memory to
> compare against"* and passes. Save a baseline first.

## Gating one combined run — `--pivot`

If a single run varies a config dim (say `semantics=legacy` vs `v1`), you can gate it against
*itself* — no second file. `--fail-on` follows the `--pivot` axis, gating the dim's **first value
vs its last** (e.g. `legacy` → `v1`):

```bash
# fail if v1's peak grew >10% over legacy, for any benchmark, from one run:
pytest benchmarks/ --benchmark-only --benchmark-memory --benchmark-json=build.json
benchmem compare build.json --pivot param:semantics --fail-on peak:10%
```

The base (the `--fail-on` reference) is the dim's *first* value in parametrize / collection order —
reorder the list to flip it. See [Compare two runs → `--pivot`](compare-runs.md#one-run-two-configs-pivot)
for how the fold works.

## Where to go next

- The full before/after table, `--diff`, and sharing it in a PR → [Compare two runs](compare-runs.md)
- A `peak +20%` says *that* it grew, not *where* → [Find where memory goes](profiling.md)
- Which metric to gate on → [Choosing a metric](metrics.md)
