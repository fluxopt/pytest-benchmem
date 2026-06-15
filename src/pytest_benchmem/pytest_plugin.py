"""pytest plugin — peak-memory alongside pytest-benchmark timing.

pytest-benchmark times your code but can't measure memory. This plugin adds a
memray peak-memory pass *to the same test, in the same run*, stored in
pytest-benchmark's own JSON (``extra_info.benchmem``) so timing and memory share
one node id. Two ways in:

- The ``benchmark_memory`` fixture — explicit, per-test::

      def test_build(benchmark_memory):
          benchmark_memory(build_model, 1000)

- The ``--benchmark-memory`` flag — augments the stock ``benchmark`` fixture, so
  an *existing* pytest-benchmark suite records memory with no code change::

      pytest --benchmark-only --benchmark-memory

Either way the two passes never overlap: pytest-benchmark times the action with
no tracker installed, then memray measures peak on a separate, untimed call — so
the allocator hooks cost the timing numbers nothing. Memory comes back out via
:func:`pytest_benchmem.memory_from_pytest_benchmark` into the unit-aware
``plot`` / ``compare``.

Registered via the ``pytest11`` entry point — installing pytest-benchmem is enough.
"""

from __future__ import annotations

import inspect
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from rich.console import Console

from pytest_benchmem.memray import MemoryResult, measure_memory
from pytest_benchmem.snapshot import BENCHMEM_KEY, _human_bytes

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


@dataclass
class _ProfileState:
    """Session state for ``--benchmark-memory-profile``: the output dir for the kept ``.bin``s,
    the temp dir staging each measured benchmark's profile, and the ``{fullname: staged}`` map.
    """

    out_dir: Path
    staging: tempfile.TemporaryDirectory[str]
    bins: dict[str, Path] = field(default_factory=dict)


#: Active memory-profile state for the session, or ``None`` when the flag is off.
_PROFILE: _ProfileState | None = None


def _sanitize_id(fullname: str) -> str:
    """A filesystem-safe stem for a benchmark id (``pkg/t.py::test_x[1]`` → ``..._test_x_1_``)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", fullname)


def _profile_bin(fullname: str) -> Path | None:
    """Staged ``.bin`` path for ``fullname`` while profiling is on, registered for keeping."""
    if _PROFILE is None:
        return None
    binp = Path(_PROFILE.staging.name) / f"{_sanitize_id(fullname)}.bin"
    _PROFILE.bins[fullname] = binp
    return binp


def _save_profiles(write: Callable[[str], None], ids: Sequence[str] | None = None) -> None:
    """Copy staged ``.bin`` profiles into the output dir — ``ids``, or all measured if ``None``.

    Prints a ready-to-paste ``memray flamegraph`` line per saved profile (the same ``.bin``
    also feeds ``memray tree`` / ``summary`` / ``stats``).
    """
    st = _PROFILE
    if st is None:
        return
    saved: list[Path] = []
    for fid in st.bins if ids is None else ids:
        src = st.bins.get(fid)
        if src is None or not src.exists():
            continue
        dest = st.out_dir / f"{_sanitize_id(fid)}.bin"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        saved.append(dest)
    if saved:
        write(f"benchmem: saved {len(saved)} memory profile(s) to {st.out_dir} — render with:")
        for dest in saved:
            write(f"    memray flamegraph {dest}")


#: Name of the per-test marker: ``@pytest.mark.benchmem(repeats=N)``.
MARKER = "benchmem"

#: ``max_*`` ceiling kwargs on the marker → (per-repeat series field, display label, is_bytes).
#: The worst pass over its ceiling fails the test (it's a worst-case budget). Absolute only —
#: there's no baseline to take a percent of; bytes take a unit suffix (``"100MiB"``) or a bare
#: int, ``max_allocations`` a bare count. This is the action-scoped guardrail (vs pytest-memray's
#: whole-test ``limit_memory``); see #82.
_LIMIT_FIELDS = {
    "max_peak": ("peak_bytes", "peak", True),
    "max_allocated": ("total_bytes", "allocated", True),
    "max_allocations": ("allocations", "allocations", False),
}


def _global_repeats(config: Any) -> int | None:
    """Suite-wide fixed repeats from ``--benchmark-memory-repeats``; ``None`` = adaptive.

    ``None`` (the option's default) means no fixed count was requested, so
    :func:`~pytest_benchmem.memray.measure_memory` adapts the pass count.
    """
    if config is None:
        return None
    raw = config.getoption("--benchmark-memory-repeats")
    if raw is None:
        return None
    try:
        return max(1, int(raw))
    except (ValueError, TypeError):
        return None


def _repeats_from_node(node: Any) -> int | None:
    """Resolve a test's memray repeats: ``@pytest.mark.benchmem(repeats=N)`` wins,
    else the suite-wide ``--benchmark-memory-repeats``, else ``None`` (adaptive).
    """
    marker = node.get_closest_marker(MARKER) if node is not None else None
    if marker is not None and "repeats" in marker.kwargs:
        return max(1, int(marker.kwargs["repeats"]))
    return _global_repeats(getattr(node, "config", None))


def _max_time_from_node(node: Any) -> float | None:
    """Resolve the adaptive-sampling wall-clock budget from ``--benchmark-memory-max-time``.

    ``None`` (the default) means no time bound — the pass cap alone bounds adaptive sampling.
    Ignored when ``repeats`` forces a fixed count.
    """
    config = getattr(node, "config", None)
    if config is None:
        return None
    raw = config.getoption("--benchmark-memory-max-time")
    try:
        return float(raw) if raw is not None else None
    except (ValueError, TypeError):
        return None


def _parse_limit(kwarg: str, value: Any, *, is_bytes: bool) -> float:
    """Parse one ``max_*`` marker value → an absolute ceiling in base units (bytes or count).

    Accepts an int/float (already base units) or a string with an optional unit
    (``"100MiB"``), reusing ``compare``'s byte-unit grammar so it matches ``--fail-on``.
    A bad value raises :class:`ValueError`, which fails the one test whose marker is wrong.
    """
    if isinstance(value, bool):  # bool is an int subclass — reject before the numeric branch
        raise ValueError(f"{MARKER}({kwarg}=...): expected a size or count, not a bool")
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError(f"{MARKER}({kwarg}={value!r}): must be non-negative")
        return float(value)
    if not isinstance(value, str):
        raise ValueError(
            f"{MARKER}({kwarg}=...): expected a number or a string like '100MiB', "
            f"got {type(value).__name__}"
        )
    import re

    from pytest_benchmem.compare import _BYTE_UNITS

    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*([A-Za-zµ]*)\s*", value)
    if m is None:
        raise ValueError(
            f"{MARKER}({kwarg}={value!r}): expected a number with an optional unit, e.g. '100MiB'"
        )
    num, suffix = float(m.group(1)), m.group(2)
    if not is_bytes:
        if suffix:
            raise ValueError(
                f"{MARKER}({kwarg}={value!r}): a count takes no unit (drop {suffix!r})"
            )
        return num
    if suffix not in _BYTE_UNITS:
        known = ", ".join(k for k in _BYTE_UNITS if k)
        raise ValueError(f"{MARKER}({kwarg}={value!r}): unknown unit {suffix!r} (use {known})")
    return num * _BYTE_UNITS[suffix]


def _limits_from_node(node: Any) -> dict[str, float]:
    """Resolve a test's ``max_*`` ceilings from ``@pytest.mark.benchmem(...)`` → ``{kwarg:
    ceiling}`` in base units. Empty when there's no marker or no ``max_*`` kwarg on it.
    """
    marker = node.get_closest_marker(MARKER) if node is not None else None
    if marker is None:
        return {}
    return {
        kwarg: _parse_limit(kwarg, marker.kwargs[kwarg], is_bytes=is_bytes)
        for kwarg, (_attr, _label, is_bytes) in _LIMIT_FIELDS.items()
        if kwarg in marker.kwargs
    }


def _enforce_limits(result: MemoryResult, limits: Mapping[str, float], name: str) -> None:
    """Fail the test if any metric's *worst* pass exceeds its ``max_*`` ceiling.

    A ``max_*`` ceiling is a worst-case guardrail — the budget you must never exceed (e.g. to
    stay clear of OOM) — so it gates on the **maximum** across repeats, not the headline min.
    Gating the floor against a ceiling would pass even when most passes breach it; the max is
    the conservative, OOM-relevant reading. With a single pass the two coincide. Raises the
    first breach as an ``AssertionError`` (a test failure, not an error).
    """
    for kwarg, limit in limits.items():
        attr, label, is_bytes = _LIMIT_FIELDS[kwarg]
        actual = float(max(result.series(attr)))
        if actual > limit:
            shown = _human_bytes if is_bytes else (lambda v: f"{v:.0f}")
            where = f"{name}: " if name else ""
            raise AssertionError(f"{where}{label} {shown(actual)} exceeds {kwarg} {shown(limit)}")


def _record_memory(
    benchmark: BenchmarkFixture,
    action: Callable[[], Any],
    *,
    repeats: int | None = None,
    max_time: float | None = None,
    limits: Mapping[str, float] | None = None,
) -> MemoryResult:
    """Memory-profile ``action`` into ``benchmark.extra_info["benchmem"]``, once.

    Idempotent: if a blob is already recorded for this benchmark (e.g. the
    ``--benchmark-memory`` patch and the explicit fixture both fire), reuse it
    rather than measuring twice. ``repeats`` (``None`` = adaptive) and ``max_time``
    pass through to :func:`~pytest_benchmem.memray.measure_memory`. Any ``max_*`` ``limits``
    are enforced on the result (freshly measured or reused), so a breach fails the test once.
    """
    existing = benchmark.extra_info.get(BENCHMEM_KEY)
    if isinstance(existing, Mapping):
        result = MemoryResult.from_blob(existing)
    else:
        keep_bin = _profile_bin(getattr(benchmark, "fullname", "") or "")
        result = measure_memory(action, repeats=repeats, max_time=max_time, keep_bin=keep_bin)
        benchmark.extra_info[BENCHMEM_KEY] = result.as_dict()
    if limits:
        _enforce_limits(result, limits, getattr(benchmark, "fullname", "") or "")
    return result


class MemoryBenchmark:
    """Callable wrapper that times via pytest-benchmark, then memory-profiles.

    Mirrors the ``benchmark`` fixture's surface (``__call__`` and ``pedantic``)
    so it's a drop-in for tests that want memory too. After a call, the measured
    memory is on :attr:`result` (and :attr:`peak_bytes`) and in the benchmark's
    ``extra_info["benchmem"]``.
    """

    def __init__(
        self,
        benchmark: BenchmarkFixture,
        *,
        repeats: int | None = None,
        max_time: float | None = None,
        limits: Mapping[str, float] | None = None,
    ) -> None:
        self._benchmark = benchmark
        self._repeats = repeats
        self._max_time = max_time
        self._limits = dict(limits or {})
        self.result: MemoryResult | None = None

    @property
    def peak_bytes(self) -> int | None:
        """Peak memory (bytes) from the last call, or ``None`` before any call."""
        return None if self.result is None else self.result.peak_bytes

    @property
    def extra_info(self) -> dict[str, Any]:
        """pytest-benchmark's per-benchmark metadata dict.

        Set scalars here to attach analysis dims — ``benchmark_memory.extra_info["op"]
        = "sort"`` — and pytest-benchmem's readers pick them up as dims alongside the
        parametrize params. The memory blob is stored here too, under ``benchmem``.
        """
        return self._benchmark.extra_info

    def __call__(self, function_to_benchmark: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Time ``function_to_benchmark(*args, **kwargs)``, then record its peak memory."""
        result = self._benchmark(function_to_benchmark, *args, **kwargs)
        self.result = _record_memory(
            self._benchmark,
            lambda: function_to_benchmark(*args, **kwargs),
            repeats=self._repeats,
            max_time=self._max_time,
            limits=self._limits,
        )
        return result

    def pedantic(
        self,
        target: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: Mapping[str, Any] | None = None,
        setup: Callable[[], Any] | None = None,
        rounds: int = 1,
        warmup_rounds: int = 0,
        iterations: int = 1,
    ) -> Any:
        """Like :meth:`pytest_benchmark.fixture.BenchmarkFixture.pedantic`, plus a memory pass.

        ``setup`` runs untracked before the measured call (and, if it returns
        ``(args, kwargs)``, supplies them) — matching pytest-benchmark, and
        giving back the untimed-setup/measured-action split cleanly.
        """
        kwargs = dict(kwargs or {})
        result = self._benchmark.pedantic(  # type: ignore[no-untyped-call]
            target,
            args=args,
            kwargs=kwargs,
            setup=setup,
            rounds=rounds,
            warmup_rounds=warmup_rounds,
            iterations=iterations,
        )
        self.result = _record_memory(
            self._benchmark,
            _pedantic_action(target, args, kwargs, setup),
            repeats=self._repeats,
            max_time=self._max_time,
            limits=self._limits,
        )
        return result


def _pedantic_action(
    target: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
    setup: Callable[[], Any] | None,
) -> Callable[[], Any]:
    """Build the zero-arg measured action for a pedantic call, honoring ``setup``."""

    def action() -> Any:
        call_args, call_kwargs = args, dict(kwargs)
        if setup is not None:
            produced = setup()
            if produced is not None:
                call_args, call_kwargs = produced
        return target(*call_args, **call_kwargs)

    return action


@pytest.fixture
def benchmark_memory(
    benchmark: BenchmarkFixture, request: pytest.FixtureRequest
) -> MemoryBenchmark:
    """Time *and* peak-memory-profile a callable in one pytest-benchmark test.

    Depends on the ``benchmark`` fixture, so timing rides pytest-benchmark fully;
    the memray memory pass is added on top and stored in the same entry. By default the
    pass count adapts (run until the min floor settles); ``@pytest.mark.benchmem(
    repeats=N)`` forces a fixed ``N`` passes (every pass kept; the headline peak is the min),
    overriding ``--benchmark-memory-repeats``. For an existing suite, prefer the
    ``--benchmark-memory`` flag over rewriting tests.
    """
    return MemoryBenchmark(
        benchmark,
        repeats=_repeats_from_node(request.node),
        max_time=_max_time_from_node(request.node),
        limits=_limits_from_node(request.node),
    )


# --- --benchmark-memory: augment the stock `benchmark` fixture --------------------

_PATCHED: tuple[Any, Any, Any] | None = None


#: pedantic kwargs the patch passes through — guard against a version that drops one.
_PEDANTIC_PARAMS = frozenset({"args", "kwargs", "setup", "rounds", "warmup_rounds", "iterations"})


def _patch_compatible(fixture_cls: Any) -> bool:
    """True if ``BenchmarkFixture.pedantic`` still takes the kwargs the patch passes.

    (``__call__`` is invoked positionally, so it needs no signature guard.)
    """
    try:
        pedantic_params = set(inspect.signature(fixture_cls.pedantic).parameters)
    except (TypeError, ValueError, AttributeError):
        return False
    return pedantic_params >= _PEDANTIC_PARAMS


def _install_auto_memory() -> None:
    """Wrap ``BenchmarkFixture.__call__``/``.pedantic`` to also record peak memory."""
    global _PATCHED
    if _PATCHED is not None:
        return
    import pytest_benchmark
    from pytest_benchmark.fixture import BenchmarkFixture

    if not _patch_compatible(BenchmarkFixture):
        raise pytest.UsageError(
            f"--benchmark-memory: pytest-benchmark {pytest_benchmark.__version__} has a "
            f"BenchmarkFixture.pedantic() signature pytest-benchmem doesn't recognize, so "
            f"the auto-memory patch can't apply safely. Either:\n"
            f"  - install a pytest-benchmark version pytest-benchmem supports, or\n"
            f"  - drop --benchmark-memory (timing still runs normally), or\n"
            f"  - report it so we add support: "
            f"https://github.com/fluxopt/pytest-benchmem/issues"
        )

    orig_init = BenchmarkFixture.__init__
    orig_call = BenchmarkFixture.__call__
    orig_pedantic = BenchmarkFixture.pedantic

    def init(self: BenchmarkFixture, node: Any, *a: Any, **k: Any) -> None:
        orig_init(self, node, *a, **k)  # type: ignore[no-untyped-call]
        setattr(self, "_benchmem_node", node)  # noqa: B010 — stash for the marker read

    def _repeats(self: BenchmarkFixture) -> int | None:
        return _repeats_from_node(getattr(self, "_benchmem_node", None))

    def _max_time(self: BenchmarkFixture) -> float | None:
        return _max_time_from_node(getattr(self, "_benchmem_node", None))

    def _limits(self: BenchmarkFixture) -> dict[str, float]:
        return _limits_from_node(getattr(self, "_benchmem_node", None))

    def call(
        self: BenchmarkFixture, function_to_benchmark: Callable[..., Any], *a: Any, **k: Any
    ) -> Any:
        result = orig_call(self, function_to_benchmark, *a, **k)  # type: ignore[no-untyped-call]
        _record_memory(
            self,
            lambda: function_to_benchmark(*a, **k),
            repeats=_repeats(self),
            max_time=_max_time(self),
            limits=_limits(self),
        )
        return result

    def pedantic(
        self: BenchmarkFixture,
        target: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: Mapping[str, Any] | None = None,
        setup: Callable[[], Any] | None = None,
        rounds: int = 1,
        warmup_rounds: int = 0,
        iterations: int = 1,
    ) -> Any:
        kwargs = dict(kwargs or {})
        result = orig_pedantic(  # type: ignore[no-untyped-call]
            self,
            target,
            args=args,
            kwargs=kwargs,
            setup=setup,
            rounds=rounds,
            warmup_rounds=warmup_rounds,
            iterations=iterations,
        )
        _record_memory(
            self,
            _pedantic_action(target, args, kwargs, setup),
            repeats=_repeats(self),
            max_time=_max_time(self),
            limits=_limits(self),
        )
        return result

    BenchmarkFixture.__init__ = init  # type: ignore[method-assign]
    BenchmarkFixture.__call__ = call  # type: ignore[method-assign]
    BenchmarkFixture.pedantic = pedantic  # type: ignore[method-assign,assignment]
    _PATCHED = (orig_init, orig_call, orig_pedantic)


def _remove_auto_memory() -> None:
    global _PATCHED
    if _PATCHED is None:
        return
    from pytest_benchmark.fixture import BenchmarkFixture

    BenchmarkFixture.__init__, BenchmarkFixture.__call__, BenchmarkFixture.pedantic = _PATCHED  # type: ignore[method-assign]
    _PATCHED = None


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--benchmark-memory`` flags."""
    group = parser.getgroup("pytest-benchmem", "peak-memory benchmarking")
    group.addoption(
        "--benchmark-memory",
        action="store_true",
        default=False,
        help="Record peak memory (a memray pass) for every benchmark() call, not just "
        "the benchmark_memory fixture — no test changes. Off by default; the fixture is "
        "always measured, with or without this flag.",
    )
    group.addoption(
        "--benchmark-memory-repeats",
        action="store",
        type=int,
        default=None,
        metavar="N",
        help="Force a fixed number of memray passes per benchmark, suite-wide; the reported "
        "peak is the minimum across them. Overridden per-test by @pytest.mark.benchmem("
        "repeats=N). Default: adaptive — run passes until the min floor settles (≥2, "
        "cap 10). Set this for a fixed, "
        "reproducible count (e.g. CI gating against a saved baseline).",
    )
    group.addoption(
        "--benchmark-memory-max-time",
        action="store",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Wall-clock budget for the adaptive memory passes (the analogue of "
        "--benchmark-max-time): caps how long adaptive sampling spends per benchmark. Ignored "
        "when --benchmark-memory-repeats forces a fixed count. Default: no time bound — the "
        "pass cap alone bounds it.",
    )
    group.addoption(
        "--benchmark-memory-compare",
        action="store",
        nargs="?",
        default=False,
        const=True,
        metavar="REF",
        help="Compare this run's peak memory against a prior saved run (a pytest-benchmark "
        "storage ref like 0001, or the latest if no value is given); folds base and "
        "delta-peak columns into the table.",
    )
    group.addoption(
        "--benchmark-memory-compare-fail",
        action="append",
        metavar="FIELD:THRESHOLD",
        help="Fail the session on a memory regression, e.g. peak:10%, peak:5MiB, "
        "allocations:5% (repeatable). Fields: peak, allocated, allocations. "
        "Implies --benchmark-memory-compare.",
    )
    group.addoption(
        "--benchmark-memory-profile",
        action="store",
        default=None,
        metavar="DIR",
        help="Save the memray profile (<id>.bin) into DIR for memory regressions, to render "
        "later with `memray flamegraph` (or tree/summary). With --benchmark-memory-compare-fail, "
        "only the offending ids; otherwise every measured benchmark. Off by default (disk cost).",
    )
    group.addoption(
        "--benchmark-memory-table",
        action="store",
        choices=["combined", "split"],
        default="combined",
        help="Layout for the memory metrics: combined (default) folds them into "
        "pytest-benchmark's timing table; split prints a separate memory table.",
    )
    group.addoption(
        "--benchmark-memory-columns",
        action="store",
        default=None,
        metavar="peak,allocated,allocations",
        help="Which memory metrics the table shows, comma-separated and in order: "
        "peak, allocated, allocations. Default: peak only.",
    )
    group.addoption(
        "--benchmark-memory-stats",
        action="store",
        default=None,
        metavar="min,mean,max",
        help="With repeats > 1, the stats each shown metric spreads into: "
        "min, mean, max, median, stddev. A single pass stays one column. "
        "Default: min,mean,max.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``benchmem`` marker; patch ``benchmark`` if ``--benchmark-memory`` is set."""
    config.addinivalue_line(
        "markers",
        "benchmem(repeats=N, max_peak=..., max_allocated=..., max_allocations=N): "
        "pytest-benchmem peak-memory options — repeats forces a fixed number of memray passes "
        "(the reported peak is the min; default adapts the count); max_peak / "
        "max_allocated / max_allocations fail the "
        "test if the worst measured pass exceeds an absolute ceiling (e.g. "
        "max_peak='100MiB', max_allocations=5000).",
    )
    _memory_column_opts(config)  # validate --benchmark-memory-columns/-stats fail-fast
    if config.getoption("--benchmark-memory"):
        _install_auto_memory()
    _configure_profiles(config)


def _configure_profiles(config: pytest.Config) -> None:
    """Arm ``--benchmark-memory-profile``: open a staging dir for the retained ``.bin``s."""
    global _PROFILE
    out = config.getoption("--benchmark-memory-profile")
    if out is None:
        return
    _PROFILE = _ProfileState(
        out_dir=Path(out),
        staging=tempfile.TemporaryDirectory(prefix="pytest-benchmem-profile-"),
    )


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore the stock ``benchmark`` fixture and drop the profile staging dir."""
    global _PROFILE
    _remove_auto_memory()
    if _PROFILE is not None:
        _PROFILE.staging.cleanup()
        _PROFILE = None


# --- --benchmark-memory-compare[-fail]: inline memory gating ---------------------


class MemoryRegression(Exception):
    """Raised from the terminal summary to fail a run on a memory regression."""


def _compare_requested(config: pytest.Config) -> tuple[object, list[str]]:
    """``(compare_ref, fail_exprs)`` — ``compare_ref`` is False/True/str; fail implies compare."""
    compare = config.getoption("--benchmark-memory-compare")
    fail_exprs = config.getoption("--benchmark-memory-compare-fail") or []
    if fail_exprs and compare is False:
        compare = True  # --…-fail with no explicit --…-compare means compare against latest
    return compare, fail_exprs


def _memory_blobs(benchmarks: Any) -> dict[str, dict[str, Any]]:
    """``{fullname: benchmem-blob}`` (the per-repeat series) for benchmarks with memory."""
    blobs: dict[str, dict[str, Any]] = {}
    for bm in benchmarks:
        extra = getattr(bm, "extra_info", None)
        blob = extra.get(BENCHMEM_KEY) if isinstance(extra, Mapping) else None
        if isinstance(blob, Mapping):
            blobs[bm.fullname] = dict(blob)
    return blobs


def _load_baseline(storage: Any, compare: object) -> tuple[str | None, dict[str, dict[str, Any]]]:
    """Resolve a baseline via pytest-benchmark storage → ``(label, {id: blob})``.

    Mirrors pytest-benchmark's own ref handling: ``True`` → the latest run, a
    string → runs matching that ref (the most recent wins).
    """
    loaded = list(storage.load()) if compare is True else list(storage.load(compare))
    if not loaded:
        return None, {}
    path, data = loaded[-1]
    blobs: dict[str, dict[str, Any]] = {}
    for bench in data.get("benchmarks", []):
        blob = bench.get("extra_info", {}).get(BENCHMEM_KEY)
        if isinstance(blob, Mapping):
            blobs[bench["fullname"]] = dict(blob)
    return str(path), blobs


def pytest_sessionstart(session: pytest.Session) -> None:
    """Snapshot the comparison baseline *before* this run is saved (no self-compare)."""
    config = session.config
    compare, fail_exprs = _compare_requested(config)
    if compare is False and not fail_exprs:
        return
    bs = getattr(config, "_benchmarksession", None)
    if bs is None:  # pytest-benchmark not active for this run
        return
    try:
        label, blobs = _load_baseline(bs.storage, compare)
    except Exception as exc:  # noqa: BLE001 — storage problems shouldn't crash the session
        label, blobs = None, {}
        bs.logger.warning(f"benchmem: could not load comparison baseline ({exc}).")
    config._benchmem_baseline = (label, blobs)  # type: ignore[attr-defined]


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    """In combined mode, suppress pytest-benchmark's table so we can render one of our own.

    Runs ``trylast`` so pytest-benchmark's own ``pytest_sessionfinish`` (which calls
    ``finish()`` and populates ``bs.groups``) has already run, but before its
    ``pytest_terminal_summary`` prints — the window to set ``bs.quiet``. Fires whenever
    memory was recorded; a ``--benchmark-memory-compare`` baseline folds into the same
    table (see :func:`pytest_terminal_summary`).
    """
    config = session.config
    if config.getoption("--benchmark-memory-table") != "combined":
        return
    bs = getattr(config, "_benchmarksession", None)
    if bs is None or not getattr(bs, "groups", None) or not _memory_blobs(bs.benchmarks):
        return
    bs.quiet = True  # pytest-benchmark skips its table; we print the combined one instead
    config._benchmem_combined = True  # type: ignore[attr-defined]


def _parse_memory_thresholds(fail_exprs: list[str]) -> list[Any]:
    """Parse + validate ``--benchmark-memory-compare-fail`` exprs (a bad one is a UsageError)."""
    from pytest_benchmem.compare import _BLOB_FIELD, parse_threshold

    if not fail_exprs:
        return []
    try:
        thresholds = [parse_threshold(expr) for expr in fail_exprs]
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc
    bad = [t.field for t in thresholds if t.field not in _BLOB_FIELD]
    if bad:
        raise pytest.UsageError(
            f"--benchmark-memory-compare-fail can't gate on {', '.join(bad)}; "
            f"use {' or '.join(_BLOB_FIELD)} "
            f"(timing is pytest-benchmark's --benchmark-compare-fail)"
        )
    return thresholds


def _memory_column_opts(config: pytest.Config) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Parse + validate ``--benchmark-memory-columns`` / ``-stats`` → ``(metrics, stats)``.

    A bad metric or stat name is a :class:`pytest.UsageError`, not a traceback.
    """
    from pytest_benchmem.tables import parse_metrics, parse_stats

    def _split(raw: object) -> list[str] | None:
        return [tok.strip() for tok in str(raw).split(",") if tok.strip()] if raw else None

    try:
        metrics = parse_metrics(_split(config.getoption("--benchmark-memory-columns")))
        stats = parse_stats(_split(config.getoption("--benchmark-memory-stats")))
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc
    return metrics, stats


def _render_combined(
    config: pytest.Config,
    bs: Any,
    *,
    metrics: Sequence[str],
    stats: Sequence[str],
    baseline: dict[str, dict[str, Any]] | None = None,
    baseline_label: str | None = None,
) -> None:
    """Render the combined timing+memory table, optionally folding in a baseline compare."""
    from functools import partial

    from pytest_benchmem.combined import render_combined_tables

    render_combined_tables(
        bs.groups,
        columns=bs.columns,
        sort=bs.sort,
        name_format=bs.name_format,
        scale_unit=partial(config.hook.pytest_benchmark_scale_unit, config=config),
        metrics=metrics,
        stats=stats,
        baseline=baseline,
        baseline_label=baseline_label,
    )


def _print_memory_table(
    config: pytest.Config,
    bs: Any,
    current: dict[str, dict[str, Any]],
    *,
    combined: bool,
    metrics: Sequence[str],
    stats: Sequence[str],
    baseline: dict[str, dict[str, Any]] | None = None,
    baseline_label: str | None = None,
) -> None:
    """Print the run's memory — folded into the combined timing table, or standalone.

    A ``baseline`` (if any) folds into the *same* table either way; the standalone
    path renders nothing when no memory was recorded this run.
    """
    if combined:
        _render_combined(
            config,
            bs,
            metrics=metrics,
            stats=stats,
            baseline=baseline,
            baseline_label=baseline_label,
        )
    elif current:
        from pytest_benchmem.tables import build_run_table

        Console().print(
            build_run_table(
                current,
                metrics=metrics,
                stats=stats,
                baseline=baseline,
                baseline_label=baseline_label,
            )
        )


def pytest_terminal_summary(terminalreporter: Any, config: pytest.Config) -> None:
    """Print the memory table — combined with timing, folding in a baseline compare if asked."""
    bs = getattr(config, "_benchmarksession", None)
    current = _memory_blobs(bs.benchmarks) if bs is not None else {}
    write = terminalreporter.write_line
    combined = bool(getattr(config, "_benchmem_combined", False)) and bs is not None

    compare, fail_exprs = _compare_requested(config)
    comparing = compare is not False or bool(fail_exprs)
    thresholds = _parse_memory_thresholds(fail_exprs)  # validate up front, any mode
    metrics, stats = _memory_column_opts(config)  # validate column selection up front

    if not comparing:
        # No comparison requested: just the table, like pytest-benchmark's own.
        _print_memory_table(config, bs, current, combined=combined, metrics=metrics, stats=stats)
        _save_profiles(write)  # no gate → every measured benchmark
        return

    default: tuple[str | None, dict[str, dict[str, Any]]] = (None, {})
    label, baseline = getattr(config, "_benchmem_baseline", default)

    if not current:
        write(
            "benchmem-compare: no memory recorded this run "
            "(use benchmark_memory or --benchmark-memory)."
        )
        return

    # Render once — the baseline (if any) folds into the same table.
    _print_memory_table(
        config,
        bs,
        current,
        combined=combined,
        metrics=metrics,
        stats=stats,
        baseline=baseline or None,
        baseline_label=label,
    )

    if not baseline:
        write("benchmem-compare: no prior run with memory to compare against.")
        if not thresholds:  # no gate → profile every measured benchmark
            _save_profiles(write)
        return
    if thresholds:
        from pytest_benchmem.compare import Regression, memory_regressions

        regressions: list[Regression] = memory_regressions(baseline, current, thresholds)
        if regressions:
            write("Memory regressions over threshold:")
            for reg in regressions:
                write(reg.format())
            _save_profiles(write, [reg.id for reg in regressions])  # offenders only
            raise MemoryRegression(f"{len(regressions)} memory regression(s) over threshold.")
        return
    _save_profiles(write)  # --compare without a fail-gate → every measured benchmark
