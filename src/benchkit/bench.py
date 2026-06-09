"""Ad-hoc benchmarking of arbitrary callables — the interactive middle.

Time or memory-profile any callable, get a result object, inspect it as a
DataFrame or drop it into a snapshot the ``plot`` / ``compare`` machinery reads::

    from benchkit import bench

    r = bench.time(build_model, 100)
    r.to_snapshot("a.json", dims={"op": "build", "subject": "basic", "n": 100})
    bench.compare({"v1": f1, "v2": f2}).to_snapshot("cmp.json")

Timing uses :class:`timeit.Timer` (``autorange`` picks the inner iteration count
so resolution doesn't dominate) with a min-of-N convention. It is *not*
pytest-benchmark's timer, so compare ``bench`` to ``bench``, suite to suite.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median, stdev
from timeit import Timer
from typing import TYPE_CHECKING, Any, Literal

from benchkit.case import DimValue
from benchkit.snapshot import Sample, write_snapshot

if TYPE_CHECKING:
    import pandas as pd

__all__ = ["MemoryResult", "ResultSet", "TimingResult", "compare", "memory", "time"]

_ROUND_FLOOR = 5
_ROUND_CAP = 10_000


def _fn_name(fn: Callable[..., object]) -> str:
    """Best-effort label for a callable (``functools.partial`` has no name)."""
    return getattr(fn, "__name__", None) or repr(fn)


def _frame(samples: list[Sample]) -> pd.DataFrame:
    """A ``load_long_df``-shaped frame from in-process samples."""
    import pandas as pd

    return pd.DataFrame(
        [{"snapshot": s.id, "id": s.id, "value": s.value, **s.dims} for s in samples]
    )


def _html_table(kind: str, header: str, rows: Sequence[tuple[str, object]]) -> str:
    body = "".join(
        f"<tr><th style='text-align:left;padding-right:1em'>{k}</th><td>{v}</td></tr>"
        for k, v in rows
    )
    return f"<b>{kind}</b> <code>{header}</code><table style='font-size:90%'>{body}</table>"


@dataclass(frozen=True)
class TimingResult:
    """One timed callable: per-round stats with ``min`` as the headline."""

    label: str
    stats: dict[str, float]
    unit: Literal["s"] = "s"

    def to_snapshot(self, path: str | Path, *, dims: Mapping[str, DimValue] | None = None) -> Path:
        """Write a one-sample timing snapshot (seconds), with optional ``dims``."""
        return write_snapshot(
            path, self.label, [Sample(self.label, self.stats["min"], dims or {})], "s"
        )

    def to_df(self) -> pd.DataFrame:
        """``load_long_df``-shaped frame (one row, ``value`` = min seconds)."""
        return _frame([Sample(self.label, self.stats["min"], {})])

    def __repr__(self) -> str:
        return (
            f"TimingResult({self.label!r}, min={self.stats['min']:.4g}s, "
            f"rounds={int(self.stats['rounds'])}x{int(self.stats.get('iterations', 1))})"
        )

    def _repr_html_(self) -> str:
        rows = [
            ("min", f"{self.stats['min']:.4g} s"),
            ("median", f"{self.stats['median']:.4g} s"),
            ("mean", f"{self.stats['mean']:.4g} s"),
            ("max", f"{self.stats['max']:.4g} s"),
            ("stddev", f"{self.stats['stddev']:.4g} s"),
            ("rounds", int(self.stats["rounds"])),
        ]
        return _html_table("TimingResult", self.label, rows)


@dataclass(frozen=True)
class MemoryResult:
    """One memory-profiled callable: peak RSS in MiB."""

    label: str
    peak_mib: float
    unit: Literal["MiB"] = "MiB"

    def to_snapshot(self, path: str | Path, *, dims: Mapping[str, DimValue] | None = None) -> Path:
        """Write a one-sample memory snapshot (peak MiB), with optional ``dims``."""
        return write_snapshot(
            path, self.label, [Sample(self.label, self.peak_mib, dims or {})], "MiB"
        )

    def to_df(self) -> pd.DataFrame:
        """``load_long_df``-shaped frame (one row, ``value`` = peak MiB)."""
        return _frame([Sample(self.label, self.peak_mib, {})])

    def __repr__(self) -> str:
        return f"MemoryResult({self.label!r}, peak={self.peak_mib:.1f} MiB)"

    def _repr_html_(self) -> str:
        return _html_table("MemoryResult", self.label, [("peak", f"{self.peak_mib:.1f} MiB")])


@dataclass(frozen=True)
class ResultSet:
    """Several results of one kind (all timing, or all memory)."""

    results: list[TimingResult | MemoryResult] = field(default_factory=list)
    unit: Literal["s", "MiB"] = "s"

    def _samples(self) -> list[Sample]:
        return [
            Sample(
                r.label,
                r.stats["min"] if isinstance(r, TimingResult) else r.peak_mib,
                {},
            )
            for r in self.results
        ]

    def to_snapshot(self, path: str | Path) -> Path:
        """Write all results into one snapshot, each keyed by its label."""
        return write_snapshot(path, "compare", self._samples(), self.unit)

    def to_df(self) -> pd.DataFrame:
        """A ``load_long_df``-shaped frame, one row per result."""
        return _frame(self._samples())

    def __repr__(self) -> str:
        return f"ResultSet(unit={self.unit!r}, [{', '.join(r.label for r in self.results)}])"

    def _repr_html_(self) -> str:
        rows = [
            (
                r.label,
                f"{r.stats['min']:.4g} s"
                if isinstance(r, TimingResult)
                else f"{r.peak_mib:.1f} MiB",
            )
            for r in self.results
        ]
        return _html_table("ResultSet", self.unit, rows)


def time(
    fn: Callable[..., object],
    /,
    *args: object,
    rounds: int | None = None,
    warmup: int = 1,
    min_time: float = 0.5,
    label: str | None = None,
    **kwargs: object,
) -> TimingResult:
    """Time ``fn(*args, **kwargs)`` and return a :class:`TimingResult`.

    Built on :class:`timeit.Timer`: ``autorange`` first calibrates the inner
    iteration count so timer resolution doesn't dominate for fast callables;
    ``warmup`` rounds prime caches. With ``rounds`` set, run exactly that many;
    otherwise auto-tune until cumulative time reaches ``min_time`` (floor of 5).
    The headline is ``stats["min"]``. Not pytest-benchmark's timer.
    """
    timer = Timer(lambda: fn(*args, **kwargs))
    number, _ = timer.autorange()
    for _ in range(max(0, warmup)):
        timer.timeit(number)

    if rounds is not None:
        samples = [t / number for t in timer.repeat(repeat=max(1, rounds), number=number)]
    else:
        samples, total = [], 0.0
        while True:
            t = timer.timeit(number)
            samples.append(t / number)
            total += t
            if (len(samples) >= _ROUND_FLOOR and total >= min_time) or len(samples) >= _ROUND_CAP:
                break

    stats = {
        "min": min(samples),
        "max": max(samples),
        "mean": mean(samples),
        "median": median(samples),
        "stddev": stdev(samples) if len(samples) > 1 else 0.0,
        "rounds": float(len(samples)),
        "iterations": float(number),
    }
    return TimingResult(label=label or _fn_name(fn), stats=stats)


def memory(
    fn: Callable[..., object],
    /,
    *args: object,
    repeats: int = 1,
    label: str | None = None,
    **kwargs: object,
) -> MemoryResult:
    """Peak-RSS profile ``fn(*args, **kwargs)`` → :class:`MemoryResult` (memray)."""
    from benchkit.memray import measure_peak

    peak = measure_peak(lambda: fn(*args, **kwargs), repeats=repeats)
    return MemoryResult(label=label or _fn_name(fn), peak_mib=peak)


def compare(
    cases: dict[str, Callable[[], object]],
    *,
    kind: Literal["time", "memory"] = "time",
    **opts: Any,
) -> ResultSet:
    """Run each zero-arg callable in ``cases`` and collect a :class:`ResultSet`.

    ``kind`` selects timing (default) or memory; ``opts`` forward to :func:`time`
    / :func:`memory`. The dict key becomes each case's label.
    """
    if kind == "time":
        results: list[TimingResult | MemoryResult] = [
            time(fn, label=name, **opts) for name, fn in cases.items()
        ]
        return ResultSet(results=results, unit="s")
    if kind == "memory":
        results = [memory(fn, label=name, **opts) for name, fn in cases.items()]
        return ResultSet(results=results, unit="MiB")
    raise ValueError(f"kind must be 'time' or 'memory', got {kind!r}")
