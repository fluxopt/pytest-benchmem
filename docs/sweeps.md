# Cross-version sweeps

To benchmark *across installed versions* of a package — something pytest-benchmark
has no answer for — `pytest_benchmem.sweep` provisions one fresh `uv` venv per
version (with import isolation) and calls your `run` callback in each. The callback
just runs your pytest suite in that venv, writing a per-version JSON. Everything
package-specific is injected, so it isn't tied to any one library.

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

## Plotting a sweep

Point `benchmem plot` at the per-version JSONs — with 3+ it defaults to the `sweep`
view, a log₂ fold-change heatmap vs the baseline — and pick `--metric time` or any
memory metric for either picture across versions:

```bash
benchmem plot 1.2.0.json 1.3.0.json main.json --metric peak
```

See **[Compare & plot](compare-plot.ipynb)** for the other views and how to render them
inline.
