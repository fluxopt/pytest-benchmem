"""Text comparison of two pytest-benchmark runs — keyed on the benchmark id.

:func:`compare_runs` prints the per-id delta table. The rest is the regression
gate behind ``benchmem compare --fail-on``: parse a threshold like ``peak:10%`` /
``peak:5MiB`` / ``allocations:5%`` / ``time:5%``, find the ids whose chosen field
grew past it, and hand them back so the CLI can exit non-zero in CI — mirroring
pytest-benchmark's ``--benchmark-compare-fail=min:5%`` grammar, for memory.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from pytest_benchmem.snapshot import (
    Metric,
    from_pytest_benchmark,
    human_bytes,
    load_long_df,
    memory_from_pytest_benchmark,
)

#: fail-on field → (reader kind, reader field/stat, display unit).
_FIELD = {
    "peak": ("memory", "peak_bytes", "B"),
    "allocated": ("memory", "total_bytes", "B"),
    "allocations": ("memory", "allocations", ""),
    "time": ("time", "min", "s"),
}

#: Absolute-threshold unit suffixes, per field family.
_BYTE_UNITS = {"": 1.0, "B": 1.0, "KiB": 1024.0, "MiB": 1024.0**2, "GiB": 1024.0**3}
_TIME_UNITS = {"": 1.0, "s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9}


def _fmt_value(field: str, value: float) -> str:
    """Format a value in its field's unit: ``4.1 MiB``, ``1.2e-05s``, ``40``."""
    unit = _FIELD[field][2]
    if unit == "B":
        return human_bytes(value)
    return f"{value:.4g}{unit}"


def _cell(value: float | None, unit: str) -> str:
    """One table cell — auto-scaled bytes, ``.4g`` otherwise, ``—`` for missing."""
    if value is None:
        return "—"
    return human_bytes(value) if unit == "B" else f"{value:.4g}"


def compare_runs(
    a: str | Path, b: str | Path, *, metric: Metric = "time", out: TextIO | None = None
) -> None:
    """Print a per-id table of ``a`` vs ``b`` (for ``metric``) with percent change.

    Reads the chosen metric (timing or memory) from two pytest-benchmark files.
    Ids present in only one run show ``—``.
    """
    out = out or sys.stdout
    df, unit = load_long_df([Path(a), Path(b)], metric=metric)
    labels = df["snapshot"].drop_duplicates().tolist()
    if len(labels) < 2:
        raise ValueError(
            f"compare needs two distinct runs; both resolve to {labels[0]!r} "
            f"(the same file given twice?). Pass two different files."
        )
    la, lb = labels[0], labels[1]
    wide = df.pivot(index="id", columns="snapshot", values="value")

    print(f"\n{'id':<70} {la:>12} {lb:>12} {'change':>10}  ({unit or 'count'})", file=out)
    print("-" * 108, file=out)
    for test_id in sorted(wide.index):
        va = wide.at[test_id, la] if la in wide.columns else None
        vb = wide.at[test_id, lb] if lb in wide.columns else None
        va = None if va is None or va != va else va  # noqa: PLR0124 — NaN check
        vb = None if vb is None or vb != vb else vb
        change = f"{(vb - va) / va * 100:+.1f}%" if va and vb and va > 0 else "—"
        short = test_id.split("::")[-1]
        print(f"{short:<70} {_cell(va, unit):>12} {_cell(vb, unit):>12} {change:>10}", file=out)
    print(file=out)


# --- regression gate (--fail-on) -------------------------------------------------


@dataclass(frozen=True)
class Threshold:
    """A parsed ``--fail-on`` rule: a ``field`` may grow by at most ``limit``."""

    field: str
    limit: float  # percent if is_pct, else absolute in the field's base unit
    is_pct: bool


@dataclass(frozen=True)
class Regression:
    """One id whose ``field`` grew past its threshold."""

    field: str
    id: str
    base: float
    head: float

    @property
    def pct(self) -> float:
        """Percent growth head-over-base (``inf`` if the baseline was zero)."""
        return (self.head - self.base) / self.base * 100 if self.base else float("inf")

    def format(self) -> str:
        """One human line: ``peak  test_x: 4.1 MiB → 5.0 MiB (+22.0%)``."""
        short = self.id.split("::")[-1]
        return (
            f"  {self.field:<12} {short}: "
            f"{_fmt_value(self.field, self.base)} → {_fmt_value(self.field, self.head)} "
            f"({self.pct:+.1f}%)"
        )


def parse_threshold(expr: str) -> Threshold:
    """Parse ``FIELD:THRESHOLD`` → :class:`Threshold` (``peak:10%``, ``peak:5MiB``)."""
    field, sep, raw = expr.partition(":")
    field, raw = field.strip().lower(), raw.strip()
    if not sep or not raw:
        raise ValueError(f"bad --fail-on {expr!r}: expected FIELD:THRESHOLD, e.g. peak:10%")
    if field not in _FIELD:
        raise ValueError(
            f"bad --fail-on {expr!r}: unknown field {field!r} (use {', '.join(_FIELD)})"
        )
    if raw.endswith("%"):
        return Threshold(field, _to_float(raw[:-1], expr), is_pct=True)
    return Threshold(field, _parse_abs(field, raw, expr), is_pct=False)


def _to_float(raw: str, expr: str) -> float:
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"bad --fail-on {expr!r}: {raw!r} is not a number") from None


def _parse_abs(field: str, raw: str, expr: str) -> float:
    """Parse an absolute threshold with an optional unit suffix → base units."""
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*([A-Za-zµ]*)", raw)
    if m is None:
        raise ValueError(f"bad --fail-on {expr!r}: {raw!r} is not a number with an optional unit")
    num, suffix = float(m.group(1)), m.group(2)
    if field == "allocations":
        if suffix:
            raise ValueError(f"bad --fail-on {expr!r}: allocations is a count, drop {suffix!r}")
        return num
    units = _BYTE_UNITS if field in ("peak", "allocated") else _TIME_UNITS
    if suffix not in units:
        known = ", ".join(k for k in units if k)
        raise ValueError(f"bad --fail-on {expr!r}: unknown unit {suffix!r} (use {known})")
    return num * units[suffix]


def _read_field(path: str | Path, field: str) -> dict[str, float]:
    """``{id: value}`` for one fail-on field out of a pytest-benchmark file."""
    metric, key, _unit = _FIELD[field]
    if metric == "time":
        _l, samples, _u = from_pytest_benchmark(path, metric=key)
    else:
        _l, samples, _u = memory_from_pytest_benchmark(path, field=key)
    return {s.id: s.value for s in samples}


def _regressions_for(
    base: dict[str, float], head: dict[str, float], th: Threshold
) -> list[Regression]:
    """Shared core: ids in both maps whose value grew past ``th`` (growth only)."""
    out: list[Regression] = []
    for test_id in sorted(base.keys() & head.keys()):
        vb, vh = base[test_id], head[test_id]
        grew = vh - vb
        if grew <= 0:
            continue
        over = (vb > 0 and grew / vb * 100 > th.limit) if th.is_pct else grew > th.limit
        if over:
            out.append(Regression(th.field, test_id, vb, vh))
    return out


def find_regressions(a: str | Path, b: str | Path, thresholds: list[Threshold]) -> list[Regression]:
    """Ids in both runs whose field grew past a threshold (only growth counts)."""
    regressions: list[Regression] = []
    for th in thresholds:
        base, head = _read_field(a, th.field), _read_field(b, th.field)
        regressions.extend(_regressions_for(base, head, th))
    return regressions


#: Memory-blob key per fail-on field — the fields ``--benchmark-memory-compare-fail`` gates on.
_BLOB_FIELD = {"peak": "peak_bytes", "allocated": "total_bytes", "allocations": "allocations"}


def memory_regressions(
    base_blobs: dict[str, dict[str, Any]],
    head_blobs: dict[str, dict[str, Any]],
    thresholds: list[Threshold],
) -> list[Regression]:
    """Regressions between two ``{id: benchmem-blob}`` maps (for the inline gate).

    Only ``peak`` / ``allocations`` are supported — timing is pytest-benchmark's
    own ``--benchmark-compare-fail``. Raises on an out-of-scope field.
    """
    regressions: list[Regression] = []
    for th in thresholds:
        if th.field not in _BLOB_FIELD:
            allowed = " or ".join(_BLOB_FIELD)
            raise ValueError(
                f"--benchmark-memory-compare-fail can't gate on {th.field!r}; use {allowed} "
                f"(timing is pytest-benchmark's own --benchmark-compare-fail)"
            )
        key = _BLOB_FIELD[th.field]
        base = {i: float(b[key]) for i, b in base_blobs.items() if key in b}
        head = {i: float(h[key]) for i, h in head_blobs.items() if key in h}
        regressions.extend(_regressions_for(base, head, th))
    return regressions
