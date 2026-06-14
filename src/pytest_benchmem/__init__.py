"""pytest-benchmem — the memory companion to pytest-benchmark.

pytest-benchmark times your code; pytest-benchmem adds a memray peak-memory pass to the
same test via the ``benchmark_memory`` fixture, stored in the same run, plus
dims-aware plots and cross-version sweeps it has no answer for.

Light to import: this re-exports only the engine (``measure_peak``) and the
readers/loader that turn pytest-benchmark JSON into a tidy frame. ``pytest_benchmem.plotting``
pulls numpy/plotly and ``pytest_benchmem.sweep`` shells out to ``uv`` — import those
submodules directly when needed. The ``benchmark_memory`` fixture is delivered by
the pytest plugin (entry point), not by import.
"""

from __future__ import annotations

from pytest_benchmem.memray import Measurement, MemoryResult, measure_memory, measure_peak
from pytest_benchmem.snapshot import (
    DimValue,
    Metric,
    Sample,
    discover_runs,
    from_pytest_benchmark,
    human_bytes,
    load_long_df,
    load_samples,
    memory_from_pytest_benchmark,
)

__all__ = [
    "DimValue",
    "Measurement",
    "MemoryResult",
    "Metric",
    "Sample",
    "discover_runs",
    "from_pytest_benchmark",
    "human_bytes",
    "load_long_df",
    "load_samples",
    "measure_memory",
    "measure_peak",
    "memory_from_pytest_benchmark",
]
