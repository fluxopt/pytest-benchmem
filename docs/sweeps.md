# Cross-version sweeps

To benchmark *across installed versions* of a package — something pytest-benchmark has no
answer for — pytest-benchmem provisions one fresh `uv` venv per version (with import
isolation), runs your suite in each, and writes a per-version JSON.

## One line, no harness

For the common case — *"run this suite across these versions of one package"* — the CLI is
one line:

```bash
benchmem sweep mypkg 1.2.0 1.3.0 git+https://github.com/me/pkg@main \
    --suite benchmarks/ --out .benchmarks/sweep --memory
```

It provisions a venv per version (a plain version installs `mypkg==<version>`; a `git+…`/pip
spec is used verbatim), runs `pytest <suite> --benchmark-only` in each writing
`<out>/<version>.json`, then prints the `benchmem compare` / `plot` next step. `--memory`
adds the memory pass; forward any other pytest flag with `--pytest-arg` (one token each,
repeatable). A non-zero exit lists any versions that failed to provision.

## Viewing a sweep

Hand the per-version JSONs (oldest → newest) straight to `benchmem compare` for a table —
one row per benchmark, one column per version, lightest value tinted green, heaviest red:

<!-- termynal -->

```console
$ benchmem compare 1.2.0.json 1.3.0.json main.json --metric peak
```

For a picture, point `benchmem plot` at the same files — with 3+ runs it defaults to the
`sweep` view, a log₂ fold-change heatmap vs the baseline:

<!-- termynal -->

```console
$ benchmem plot 1.2.0.json 1.3.0.json main.json --metric peak
```

Either way, pick `--metric time` or any memory metric. See
[Compare & gate CI](compare-plot.md) for the other views.

---

## Going further

Every `benchmem sweep` option (`--suite`, `--out`, `--memory`, `--pin`, `--as-of`,
`--import-check`, `--copy-dir`, `--pytest-arg`) is documented in the
[Reference](reference.md#cli-benchmem).

Need more than the CLI offers — a non-pytest command, custom provisioning, or post-processing?
There's a programmatic `pytest_benchmem.sweep.sweep()` harness that calls your own `run`
callback in each provisioned venv. See the [Reference](reference.md#cli-benchmem) and its
source docstrings.
