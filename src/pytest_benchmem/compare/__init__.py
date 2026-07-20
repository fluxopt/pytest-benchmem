"""Compare one or more pytest-benchmark runs — the ``benchmem compare`` command's engine.

Two things live here, split across the package:

- The **table** (:func:`compare_runs`, in :mod:`.run` over :mod:`.table` / :mod:`.diff`): a
  per-``(benchmark × run)`` view keyed on the benchmark id, as a rich terminal table or markdown.
  With two or more runs each cell carries a relative ``(N.NN)`` multiplier vs its column's best;
  ``diff=True`` collapses it to a baseline Δ% view. :mod:`.model` is the shared loading substrate.
- The **regression gate** (:mod:`.gate`) behind ``benchmem compare --fail-on`` and the inline
  memory gate: parse a threshold, find the ids whose field grew past it, exit non-zero in CI.

This ``__init__`` is the package's public facade; import from it (not the submodules).
"""

from __future__ import annotations

from pytest_benchmem.compare.gate import _BLOB_FIELD as _BLOB_FIELD  # re-export for the inline gate
from pytest_benchmem.compare.gate import (
    Regression,
    Threshold,
    find_pivot_regressions,
    find_regressions,
    memory_regressions,
    parse_threshold,
)
from pytest_benchmem.compare.model import _BYTE_UNITS as _BYTE_UNITS  # re-export for the CLI parser
from pytest_benchmem.compare.run import compare_runs

__all__ = [
    "Regression",
    "Threshold",
    "compare_runs",
    "find_pivot_regressions",
    "find_regressions",
    "memory_regressions",
    "parse_threshold",
]
