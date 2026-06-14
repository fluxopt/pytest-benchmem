"""Cross-version sweep — run benchmarks against several installed versions of a
package in fresh, isolated ``uv`` venvs.

Generic: the package install spec, the extra pins, the directory to copy for
import isolation, and *what to run* in each venv are all injected. A consumer
(e.g. linopy) wires ``install_spec=lambda v: f"linopy=={v}"`` and a ``run``
callback that invokes its pytest / memory command.

Isolation: if the repo root contains a dev copy of the package under test, it
would shadow the venv's installed version on ``sys.path``. So each venv runs
with ``cwd`` set to a fresh tempdir holding only a *copy* of ``copy_dir`` — the
benchmark code imports from there, while the package-under-test resolves to the
venv. A preflight asserts that resolution held.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

_PLAIN_VERSION_RE = re.compile(r"^\d+(\.\d+)*([a-z]+\d*)?$")


def version_label(version: str) -> str:
    """Filesystem-safe label from a version/pip-spec (part after the last ``@``)."""
    label = version.rsplit("@", 1)[-1] if "@" in version else version
    return re.sub(r"[^0-9A-Za-z._-]+", "-", label).strip("-._") or "spec"


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


@dataclass(frozen=True)
class Venv:
    """One provisioned per-version venv (or a failure)."""

    version: str
    python: Path | None
    env: dict[str, str] | None
    cwd: Path | None
    failed_at: str | None  # "venv" | "install" | "isolation" | None

    @classmethod
    def failure(cls, version: str, stage: str) -> Venv:
        """A provisioning failure at ``stage`` — no python/env/cwd, just the reason."""
        return cls(version, None, None, None, stage)


def provision(
    versions: Sequence[str],
    *,
    install_spec: Callable[[str], str] = lambda v: v,
    pins: Sequence[str] = (),
    copy_dir: str | Path | None = None,
    import_check: str | None = None,
    as_of: str | None = None,
    tmp_prefix: str = "pytest-benchmem-",
) -> Iterator[Venv]:
    """Yield one fresh ``uv`` venv per version.

    ``install_spec(v)`` → the pip spec for the package under test (default:
    ``v`` verbatim, so ``"pkg==1.2"`` works). ``pins`` are extra specs installed
    alongside. ``copy_dir`` is copied into each venv's cwd for import isolation.
    ``import_check`` is a module name asserted to resolve to the venv (preflight).
    ``as_of`` (``YYYY-MM-DD``) freezes the whole resolution via ``--exclude-newer``.
    """
    if shutil.which("uv") is None:
        raise RuntimeError("uv not found on PATH — https://docs.astral.sh/uv/")

    for version in versions:
        with tempfile.TemporaryDirectory(prefix=tmp_prefix) as tmp:
            venv = Path(tmp) / "venv"
            r = subprocess.run(["uv", "venv", "--python", sys.executable, str(venv)], check=False)
            if r.returncode != 0:
                yield Venv.failure(version, "venv")
                continue

            vpy = _venv_python(venv)
            spec = install_spec(version) if _PLAIN_VERSION_RE.match(version) else version
            install = [
                "uv",
                "pip",
                "install",
                "--python",
                str(vpy),
                *(["--exclude-newer", as_of] if as_of else []),
                *pins,
                spec,
            ]
            if subprocess.run(install, check=False).returncode != 0:
                yield Venv.failure(version, "install")
                continue

            cwd = Path(tmp) / "iso"
            cwd.mkdir()
            if copy_dir is not None:
                src = Path(copy_dir)
                shutil.copytree(
                    src,
                    cwd / src.name,
                    ignore=shutil.ignore_patterns("__pycache__", "*.ipynb", ".DS_Store"),
                )
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)

            if import_check is not None:
                pre = subprocess.run(
                    [
                        str(vpy),
                        "-c",
                        f"import {import_check} as _m; "
                        f"assert {str(venv)!r} in _m.__file__, _m.__file__",
                    ],
                    cwd=str(cwd),
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if pre.returncode != 0:
                    yield Venv.failure(version, "isolation")
                    continue

            yield Venv(version, vpy, env, cwd, None)


def sweep(
    versions: Sequence[str],
    run: Callable[[Venv], None],
    **provision_kwargs: object,
) -> list[str]:
    """Provision a venv per version and call ``run(venv)`` in each.

    ``run`` does whatever the consumer needs (invoke pytest / a memory command
    with ``venv.python`` and ``cwd=venv.cwd``). Returns the list of versions
    that failed to provision.
    """
    failed: list[str] = []
    for prov in provision(versions, **provision_kwargs):  # type: ignore[arg-type]
        if prov.failed_at:
            failed.append(prov.version)
            continue
        run(prov)
    return failed
