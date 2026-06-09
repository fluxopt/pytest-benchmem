"""benchkit — generic time + peak-memory benchmarking around a ``Case``.

Light to import: only the core (``Case``, the memray engine, snapshots) is
re-exported here. ``benchkit.plotting`` pulls numpy/plotly, ``benchkit.cli``
pulls typer, and ``benchkit.sweep`` shells out to ``uv`` — import those
submodules directly when needed.
"""

from __future__ import annotations

from benchkit import bench
from benchkit.case import Action, Case, CaseFactory, DimValue
from benchkit.memray import measure, measure_peak
from benchkit.snapshot import (
    Sample,
    from_pytest_benchmark,
    load_long_df,
    load_snapshot,
    write_snapshot,
)

__all__ = [
    "Action",
    "Case",
    "CaseFactory",
    "DimValue",
    "Sample",
    "bench",
    "from_pytest_benchmark",
    "load_long_df",
    "load_snapshot",
    "measure",
    "measure_peak",
    "write_snapshot",
]
