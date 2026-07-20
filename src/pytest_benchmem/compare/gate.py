"""The regression gate behind ``benchmem compare --fail-on`` (and the inline memory gate).

Parse a threshold like ``peak:10%`` / ``peak:5MiB`` / ``allocations:5%`` / ``time:5%``, find the
ids whose chosen field grew past it, and hand them back so the CLI can exit non-zero in CI —
mirroring pytest-benchmark's ``--benchmark-compare-fail=min:5%`` grammar, for memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pytest_benchmem.compare.model import _BYTE_UNITS, _FIELD, _TIME_UNITS, _fmt_value
from pytest_benchmem.format import signed_pct
from pytest_benchmem.snapshot import (
    Metric,
    from_pytest_benchmark,
    load_long_df,
    memory_from_pytest_benchmark,
)


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
            f"({signed_pct(self.pct)})"
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


#: Raised when an ``rss`` gate has no data on both sides — `rss` exists only for isolated runs,
#: so silently passing would be a gate that can never fire. Loud beats a false green in CI.
_RSS_GATE_EMPTY = (
    "--fail-on rss: no benchmark carries rss in both runs — rss is recorded only for benchmarks "
    "marked @pytest.mark.benchmem(isolate=True). Mark the capacity benchmarks, or drop the rss "
    "gate."
)


def find_regressions(a: str | Path, b: str | Path, thresholds: list[Threshold]) -> list[Regression]:
    """Ids in both runs whose field grew past a threshold (only growth counts)."""
    regressions: list[Regression] = []
    for th in thresholds:
        base, head = _read_field(a, th.field), _read_field(b, th.field)
        if th.field == "rss" and not (base.keys() & head.keys()):
            raise ValueError(_RSS_GATE_EMPTY)
        regressions.extend(_regressions_for(base, head, th))
    return regressions


def find_pivot_regressions(
    run: str | Path, pivot: str, thresholds: list[Threshold]
) -> list[Regression]:
    """Regressions along a ``--pivot`` axis within *one* run — the gate generalized the same way
    the table is: with run-files the base is ``runs[0]`` and the head ``runs[-1]``; here the base
    is the first value of the ``pivot`` dim and the head the last (mirroring oldest→newest). Each
    fold-collapsed id is paired across them and flagged only on growth, reusing
    :func:`_regressions_for`.
    """
    regressions: list[Regression] = []
    for th in thresholds:
        # ``pivot`` folds the run so ``snapshot`` carries the dim's values and ``id`` is the
        # collapsed pairing key; the fail-on field doubles as the metric to read (headline scalar).
        df, _unit = load_long_df(run, metric=cast("Metric", th.field), pivot=pivot)
        labels = list(dict.fromkeys(df["snapshot"]))
        if len(labels) < 2:  # noqa: PLR2004 — a growth gate needs a base value and a head value
            raise ValueError(
                f"--fail-on with --pivot {pivot!r} needs two distinct values to gate; got "
                f"{labels}. Does the run vary {pivot!r}?"
            )
        base_label, head_label = labels[0], labels[-1]
        rows = zip(df["id"], df["value"], df["snapshot"], strict=True)
        side: dict[str, dict[str, float]] = {base_label: {}, head_label: {}}
        for test_id, value, label in rows:
            if label in side:
                side[label][test_id] = float(value)
        base, head = side[base_label], side[head_label]
        if th.field == "rss" and not (base.keys() & head.keys()):
            raise ValueError(_RSS_GATE_EMPTY)
        regressions.extend(_regressions_for(base, head, th))
    return regressions


#: Memory-blob key per fail-on field — the fields ``--benchmark-memory-compare-fail`` gates on.
_BLOB_FIELD = {
    "peak": "peak_bytes",
    "allocated": "total_bytes",
    "allocations": "allocations",
    "rss": "rss_bytes",
}


def memory_regressions(
    base_blobs: dict[str, dict[str, Any]],
    head_blobs: dict[str, dict[str, Any]],
    thresholds: list[Threshold],
) -> list[Regression]:
    """Regressions between two ``{id: benchmem-blob}`` maps (for the inline gate).

    Only ``peak`` / ``allocations`` are supported — timing is pytest-benchmark's
    own ``--benchmark-compare-fail``. Raises on an out-of-scope field.
    """
    from pytest_benchmem.memray import MemoryResult

    def headline(blobs: dict[str, dict[str, Any]], attr: str) -> dict[str, float]:
        # the blob is the per-repeat series; the gate reads its derived headline scalar.
        # ``rss`` is ``None`` for in-process blobs — skip those (nothing to gate there).
        out: dict[str, float] = {}
        for i, b in blobs.items():
            if "peak_bytes" not in b:
                continue
            scalar = getattr(MemoryResult.from_blob(b), attr)
            if scalar is not None:
                out[i] = float(scalar)
        return out

    regressions: list[Regression] = []
    for th in thresholds:
        if th.field not in _BLOB_FIELD:
            allowed = " or ".join(_BLOB_FIELD)
            raise ValueError(
                f"--benchmark-memory-compare-fail can't gate on {th.field!r}; use {allowed} "
                f"(timing is pytest-benchmark's own --benchmark-compare-fail)"
            )
        key = _BLOB_FIELD[th.field]
        base_h, head_h = headline(base_blobs, key), headline(head_blobs, key)
        if th.field == "rss" and not (base_h.keys() & head_h.keys()):
            raise ValueError(_RSS_GATE_EMPTY)
        regressions.extend(_regressions_for(base_h, head_h, th))
    return regressions
