# Cross-version sweeps

> **Newer feature** — less battle-tested than the [find & fix](profiling.md) core. It works, but
> feedback is welcome.

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
`<out>/<version>.json`, then prints the `benchmem compare` / `plot` next step. The harness
itself is installed into each venv automatically — `pytest-benchmem` (pytest, pytest-benchmark
and memray included) with `--memory`, plain `pytest-benchmark` without — so the swept package
doesn't need to depend on it; a `--pin` naming the package overrides the auto-install.
`--memory` adds the memory pass; forward any other pytest flag with `--pytest-arg` (one token
each, repeatable). A non-zero exit lists any versions that failed to provision.

Each version runs in an isolated working directory holding a *copy* of the suite (so a dev
checkout of the swept package can't shadow the venv-installed version). By default only the
`--suite` directory is copied — if your suite reaches outside it, say a repo-root
`conftest.py` or data files resolved relative to the test file
(`Path(__file__).parent.parent / "data"`), those benchmarks error under sweep even though
plain pytest runs them fine. Declare the suite's true root with `--copy-dir`:

```bash
benchmem sweep mypkg 1.2.0 1.3.0 --suite benchmarks/ --copy-dir . --memory
```

That stages the whole repo (minus `.venv`, `.git`, `.benchmarks`, `.pytest_cache` and
caches) into the isolated directory, so relative resolution works as it does locally.
One caveat: the wider the copy, the weaker the isolation. With a `src/` layout the copied
source can't shadow the venv-installed package (nothing importable sits next to the
tests), so `--copy-dir .` is safe. With a flat layout the copied package directory can
end up on `sys.path` ahead of the venv under pytest's path rules — there, prefer pointing
`--copy-dir` at a narrower directory holding just the suite's shared files (conftest,
data), or sanity-check a swept value that you know differs between the versions.

## Viewing a sweep

Hand the per-version JSONs (oldest → newest) straight to `benchmem compare` for a table —
one row per benchmark, one column per version, lightest value tinted green, heaviest red:

```bash
benchmem compare 1.2.0.json 1.3.0.json main.json --columns peak
```

For a picture, point `benchmem plot` at the same files — with 3+ runs it defaults to the
`sweep` view, a log₂ fold-change heatmap vs the baseline:

```bash
benchmem plot 1.2.0.json 1.3.0.json main.json --columns peak
```

`compare` shows `time` and `peak` across every stat by default (pick metrics with
`--columns`, a stat with `--stat`); `plot` takes one `--columns`. See
[Visualize memory](visualize.ipynb) for the other views.

---

## Going further

Every `benchmem sweep` option (`--suite`, `--out`, `--memory`, `--pin`, `--as-of`,
`--import-check`, `--copy-dir`, `--pytest-arg`) is documented in the
[Reference](reference.md#cli-benchmem).

Need more than the CLI offers — a non-pytest command, custom provisioning, or post-processing?
There's a programmatic `pytest_benchmem.sweep.sweep()` harness that calls your own `run`
callback in each provisioned venv. See the [Reference](reference.md#cli-benchmem) and its
source docstrings.
