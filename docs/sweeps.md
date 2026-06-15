# Cross-version sweeps

To benchmark *across installed versions* of a package — something pytest-benchmark
has no answer for — pytest-benchmem provisions one fresh `uv` venv per version (with
import isolation) and runs your suite in each, writing a per-version JSON.

## The `benchmem sweep` CLI

For the common case — *"run this suite across these versions of one package"* — the
CLI is one line, no harness to write:

```bash
benchmem sweep mypkg 1.2.0 1.3.0 git+https://github.com/me/pkg@main \
    --suite benchmarks/ --out .benchmarks/sweep --memory
```

It provisions a venv per version (a plain version installs `mypkg==<version>`; a
`git+…`/pip spec is used verbatim), runs `pytest <suite> --benchmark-only` in each
writing `<out>/<version>.json`, then prints the `benchmem compare` / `plot` next
step. `--memory` adds the memory pass; forward any other pytest flag with
`--pytest-arg` (one token each, repeatable). `--pin`, `--as-of`, `--import-check`,
and `--copy-dir` map to the `provision` parameters below. A non-zero exit lists any
versions that failed to provision. See the [reference](reference.ipynb) for the live
`--help`.

## The `sweep()` API — custom `run`

When you need more than the CLI offers (a non-pytest command, custom post-processing),
`pytest_benchmem.sweep` calls your own `run` callback in each provisioned venv.
Everything package-specific is injected, so it isn't tied to any one library.

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

`sweep` returns the list of version labels that failed to provision (empty on full
success).

## The `run` callback and the `Venv` it receives

Your `run(venv)` callback is invoked once per version. The `Venv` it gets exposes
everything needed to launch the suite in isolation:

| Attribute | Type | What |
|---|---|---|
| `venv.version` | `str` | the version label (use it to name the output JSON) |
| `venv.python` | `Path \| None` | the venv's Python executable |
| `venv.cwd` | `Path \| None` | the isolation dir — holds the copied `copy_dir` |
| `venv.env` | `dict \| None` | environment with `PYTHONPATH` cleared |
| `venv.failed_at` | `str \| None` | `"venv"`, `"install"`, `"isolation"`, or `None` |

## `sweep` / `provision` parameters

`sweep(versions, run, **provision_kwargs)` forwards its keyword arguments to
`provision`, which yields the venvs:

| Parameter | Default | What |
|---|---|---|
| `versions` | — | version labels to sweep (pip specs, tags, or `git+…` refs) |
| `install_spec` | `lambda v: v` | maps a label to the pip spec for the package under test, e.g. `f"mypkg=={v}"` |
| `pins` | `()` | extra specs installed alongside (uv pip install) |
| `copy_dir` | `None` | a directory copied into each `venv.cwd`, so the suite imports *from here* and the package *from the venv* |
| `import_check` | `None` | a module name asserted to resolve to the venv before running — a preflight against import leakage |
| `as_of` | `None` | a `YYYY-MM-DD` date passed to uv's `--exclude-newer`, for reproducible resolution |
| `tmp_prefix` | `"pytest-benchmem-"` | prefix for the temp venv dirs |

## Viewing a sweep

For a table, hand the per-version JSONs straight to `benchmem compare` — it takes
**two or more** runs (oldest → newest) and renders one row per benchmark, one column
per version, with the lightest value tinted green and the heaviest red:

```bash
benchmem compare 1.2.0.json 1.3.0.json main.json --metric peak
```

For a picture, point `benchmem plot` at the same files — with 3+ it defaults to the
`sweep` view, a log₂ fold-change heatmap vs the baseline:

```bash
benchmem plot 1.2.0.json 1.3.0.json main.json --metric peak
```

Either way, pick `--metric time` or any memory metric. See **[Compare &
plot](compare-plot.ipynb)** for the other views and how to render them inline.
